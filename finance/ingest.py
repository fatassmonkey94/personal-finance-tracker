"""Turn uploaded files into a clean, categorised, deduplicated transaction list."""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from .describe import summarise
from .model import ParsedDocument, Transaction
from .parse_pdf import parse_pdf
from .parse_tabular import parse_tabular
from .rules import (
    DEFAULT_TRANSFER_REVIEW_THRESHOLD,
    Categoriser,
    merchant_key,
)

TABULAR_EXT = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls", ".xltx")
PDF_EXT = (".pdf",)


def parse_upload(data: bytes, filename: str, account_hint: str = "",
                 fallback_month: Optional[str] = None,
                 pdf_password: Optional[str] = None) -> ParsedDocument:
    lower = filename.lower()
    if lower.endswith(PDF_EXT):
        return parse_pdf(data, filename, account_hint, fallback_month, pdf_password)
    if lower.endswith(TABULAR_EXT):
        year = None
        if fallback_month:
            try:
                year = int(fallback_month.split("-")[0])
            except ValueError:
                year = None
        return parse_tabular(data, filename, account_hint, year)
    doc = ParsedDocument(filename=filename, account=account_hint, doc_type="unknown")
    doc.warnings.append(
        f"{filename}: unsupported file type. Upload CSV, Excel (.xlsx/.xls) or PDF."
    )
    return doc


def enrich(transactions: List[Transaction], categoriser: Categoriser) -> None:
    """Assign a category and a short description to each transaction, in place."""
    for txn in transactions:
        category, rule, needs_review, note = categoriser.categorise(
            txn.raw_description, txn.direction, txn.amount_sgd
        )
        txn.category = category
        txn.rule_matched = rule
        if needs_review and not txn.needs_review:
            txn.needs_review = True
            txn.review_note = note
        elif needs_review and note and note not in txn.review_note:
            txn.review_note = (txn.review_note + " " + note).strip()
        txn.description = summarise(txn.raw_description, category, txn.direction)


def dedupe(transactions: List[Transaction]) -> Tuple[List[Transaction], List[str]]:
    """Drop repeats caused by uploading the same statement twice.

    Only repeats across *different* files are dropped. A bank never lists the
    same transaction twice in one export, so two identical rows in one file are
    two real transactions — buying the same coffee twice on the same day is
    ordinary, and deleting one would silently lose money.
    """
    seen = {}
    kept: List[Transaction] = []
    notes: List[str] = []

    for txn in transactions:
        key = txn.dedupe_key()
        previous = seen.get(key)
        if previous is not None and previous.source_doc != txn.source_doc:
            notes.append(
                f"Dropped duplicate of the same transaction found in two files: "
                f"{txn.date} {txn.description} S${txn.amount_sgd:,.2f} "
                f"({txn.source_file} also in {previous.source_file})"
            )
            continue
        seen[key] = txn
        kept.append(txn)

    # Same date + amount + direction on two different accounts is usually the
    # same statement uploaded twice in two formats. Flag, don't delete.
    cross: Dict[tuple, List[Transaction]] = {}
    for txn in kept:
        cross.setdefault((txn.date, round(txn.amount_sgd, 2), txn.direction), []).append(txn)
    for (day, amount, direction), group in cross.items():
        if len(group) < 2:
            continue
        files = {t.source_file for t in group}
        if len(files) > 1:
            notes.append(
                f"Possible duplicate across files on {day}: S${amount:,.2f} {direction} "
                f"appears in {', '.join(sorted(files))} — check you have not uploaded "
                f"the same statement twice."
            )
    return kept, notes


def ingest_files(files: List[Tuple[str, bytes]], parent_names=None,
                 employer_keywords=None, fallback_month: Optional[str] = None,
                 account_hints: Optional[Dict[str, str]] = None,
                 pdf_password: Optional[str] = None,
                 overrides_path: Optional[str] = None,
                 transfer_review_threshold: float = DEFAULT_TRANSFER_REVIEW_THRESHOLD):
    """Parse every uploaded file and return (transactions, documents, notes)."""
    categoriser = Categoriser(parent_names, employer_keywords, overrides_path,
                              transfer_review_threshold)
    docs: List[ParsedDocument] = []
    all_txns: List[Transaction] = []

    for doc_index, (filename, data) in enumerate(files):
        hint = (account_hints or {}).get(filename, "")
        doc = parse_upload(data, filename, hint, fallback_month, pdf_password)
        for txn in doc.transactions:
            txn.source_doc = doc_index
        enrich(doc.transactions, categoriser)
        docs.append(doc)
        all_txns.extend(doc.transactions)

    all_txns, notes = dedupe(all_txns)
    all_txns.sort(key=lambda t: (t.date or __import__("datetime").date.min,
                                 t.source_account, t.description))
    return all_txns, docs, notes


def apply_override(overrides: dict, raw_description: str, category: str) -> dict:
    key = merchant_key(raw_description)
    if key:
        overrides[key] = category
    return overrides


def default_overrides_path(base_dir: str) -> str:
    return os.path.join(base_dir, "data", "category_overrides.json")
