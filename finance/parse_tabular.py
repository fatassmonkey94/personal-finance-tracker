"""Parse CSV / Excel statement exports.

Bank exports are messy: the header is rarely on row 1, columns are named a
dozen different ways, and amounts arrive as either a signed column or a
debit/credit pair. This module sniffs all of that out rather than requiring a
fixed template.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import List, Optional, Tuple

import pandas as pd

from .model import CREDIT, DEBIT, ParsedDocument, Transaction

# ---------------------------------------------------------------------------
# Column synonyms. Matched case-insensitively against normalised headers.
# ---------------------------------------------------------------------------
DATE_COLS = [
    "transaction date", "txn date", "trans date", "date", "posting date",
    "post date", "value date", "transaction dt", "date of transaction",
    "tran date", "booking date", "settlement date", "entry date",
]
POST_DATE_COLS = ["posting date", "post date", "value date"]
DESC_COLS = [
    "description", "transaction description", "details", "transaction details",
    "particulars", "narrative", "reference", "remarks", "merchant",
    "transaction ref1", "transaction ref2", "transaction ref3",
    "transaction reference", "payee", "name", "memo", "transaction",
]
DEBIT_COLS = [
    "debit amount", "withdrawal", "withdrawal amount", "debit", "money out",
    "paid out", "withdrawals sgd", "debit sgd", "dr amount", "amount paid",
    "withdrawal sgd", "out",
]
CREDIT_COLS = [
    "credit amount", "deposit", "deposit amount", "credit", "money in",
    "paid in", "deposits sgd", "credit sgd", "cr amount", "amount received",
    "deposit sgd", "in",
]
# The settled SGD figure. Checked before AMOUNT_COLS, because UOB card exports
# put "Transaction Amount(Foreign)" to the LEFT of "Transaction Amount(Local)"
# and a plain search for "amount" would grab the foreign figure.
LOCAL_AMOUNT_COLS = [
    "transaction amount local", "amount local", "local amount",
    "local currency amount", "amount sgd", "sgd amount", "amount in sgd",
    "transaction amount sgd", "settlement amount", "billing amount",
]
AMOUNT_COLS = [
    "amount", "transaction amount", "value", "amt", "gross amount",
]
# Headers that clearly refer to the pre-conversion figure. Never treated as the
# SGD amount, whatever else they match.
_FOREIGN_MARKERS = ("foreign", "original", "source currency", "overseas")

CURRENCY_COLS = [
    "local currency type", "local currency", "settlement currency",
    "currency", "ccy", "transaction currency", "curr", "currency code",
]
FOREIGN_CURRENCY_COLS = [
    "foreign currency type", "foreign currency", "original currency",
    "source currency", "overseas currency",
]
FOREIGN_AMOUNT_COLS = [
    "transaction amount foreign", "foreign amount", "original amount",
    "foreign currency amount", "source amount", "overseas amount",
]
DRCR_COLS = [
    "dr/cr", "cr/dr", "debit/credit", "type", "transaction type", "dr cr",
    "d/c", "indicator", "debit or credit",
]
BALANCE_COLS = ["balance", "available balance", "running balance", "ledger balance"]

CURRENCY_CODES = {
    "SGD", "USD", "EUR", "GBP", "AUD", "JPY", "MYR", "THB", "IDR", "HKD", "CNY",
    "RMB", "KRW", "VND", "PHP", "TWD", "NZD", "CHF", "CAD", "INR", "AED", "DKK",
    "SEK", "NOK", "ZAR", "BRL", "MXN", "TRY", "RUB", "PLN", "CZK", "LKR", "BDT",
    "NPR", "PKR", "KHR", "LAK", "MMK", "BND", "MOP", "SAR", "QAR", "EGP", "ILS",
}

_HEADER_KEYWORDS = set(
    DATE_COLS + DESC_COLS + DEBIT_COLS + CREDIT_COLS + AMOUNT_COLS
    + CURRENCY_COLS + DRCR_COLS + BALANCE_COLS
)


def _norm(value) -> str:
    """Normalise a header for matching: 'Transaction Amount(Local)' ->
    'transaction amount local'."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("\n", " ").replace("_", " ")
    text = re.sub(r"[^a-z0-9/& ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_foreign_header(header: str) -> bool:
    return any(marker in header for marker in _FOREIGN_MARKERS)


def _substring_ok(candidate: str) -> bool:
    """Very short synonyms must match exactly.

    'in' would otherwise match 'Posting Date' and 'out' would match 'Amount',
    quietly reading a date column as the transaction amount.
    """
    return len(candidate) > 3


def _match_column(headers: List[str], candidates: List[str],
                  skip_foreign: bool = False) -> Optional[int]:
    """Exact match first, then substring, so 'Amount' doesn't steal 'Foreign Amount'.

    With skip_foreign, columns naming the pre-conversion figure are never
    returned — that keeps the SGD amount from being read off a foreign column.
    """
    normed = [_norm(h) for h in headers]
    allowed = [
        idx for idx, header in enumerate(normed)
        if not (skip_foreign and _is_foreign_header(header))
    ]
    for cand in candidates:
        for idx in allowed:
            if normed[idx] == cand:
                return idx
    for cand in candidates:
        if not _substring_ok(cand):
            continue
        for idx in allowed:
            if normed[idx] and cand in normed[idx]:
                return idx
    return None


def _match_all_columns(headers: List[str], candidates: List[str]) -> List[int]:
    normed = [_norm(h) for h in headers]
    hits = []
    for idx, header in enumerate(normed):
        if not header:
            continue
        if any(header == c or (_substring_ok(c) and c in header) for c in candidates):
            hits.append(idx)
    return hits


# ---------------------------------------------------------------------------
# Loading raw grids
# ---------------------------------------------------------------------------
def _read_grids(data: bytes, filename: str) -> List[Tuple[str, pd.DataFrame]]:
    """Return [(sheet_label, raw dataframe with no header applied)]."""
    lower = filename.lower()
    grids: List[Tuple[str, pd.DataFrame]] = []

    if lower.endswith((".xlsx", ".xlsm", ".xls", ".xltx")):
        engine = "openpyxl" if not lower.endswith(".xls") else None
        book = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None,
                             dtype=object, engine=engine)
        for name, frame in book.items():
            grids.append((str(name), frame))
        return grids

    # CSV / TSV: sniff the separator and tolerate ragged rows.
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")

    sample = "\n".join(text.splitlines()[:40])
    sep = "\t" if sample.count("\t") > sample.count(",") else ","
    if sample.count(";") > max(sample.count(","), sample.count("\t")):
        sep = ";"

    # Read with the csv module rather than pandas: bank exports put a 2-column
    # preamble above a 7-column table, and pandas would either error or lock the
    # column count to the preamble and silently drop every real row.
    rows = list(csv.reader(io.StringIO(text), delimiter=sep))
    if not rows:
        return grids
    width = max(len(r) for r in rows)
    padded = [r + [None] * (width - len(r)) for r in rows]
    frame = pd.DataFrame(padded, dtype=object)
    grids.append(("csv", frame))
    return grids


def _find_header_row(frame: pd.DataFrame, scan_rows: int = 40) -> Optional[int]:
    """Score the first N rows and pick the one that looks most like a header."""
    best_row, best_score = None, 0
    limit = min(scan_rows, len(frame))
    for row_idx in range(limit):
        cells = [_norm(c) for c in frame.iloc[row_idx].tolist()]
        score = 0
        for cell in cells:
            if not cell:
                continue
            if cell in _HEADER_KEYWORDS:
                score += 3
            elif any(kw == cell or (kw in cell and len(cell) < 40) for kw in _HEADER_KEYWORDS):
                score += 2
        has_date = any(
            c in DATE_COLS or any(d in c for d in ("date", "dt")) for c in cells if c
        )
        has_money = any(
            c in AMOUNT_COLS + DEBIT_COLS + CREDIT_COLS
            or any(m in c for m in ("amount", "debit", "credit", "withdraw", "deposit"))
            for c in cells if c
        )
        if has_date and has_money:
            score += 4
        if score > best_score:
            best_row, best_score = row_idx, score
    return best_row if best_score >= 5 else None


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------
_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d-%m-%y", "%m/%d/%Y", "%m/%d/%y",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%d %b %y", "%d-%b-%y",
    "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y",
    "%Y%m%d", "%d%m%Y", "%d %b", "%d-%b", "%b %d",
]


def parse_date(value, default_year: Optional[int] = None) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel serial date.
        try:
            if 20000 < float(value) < 60000:
                return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(value))).date()
        except (ValueError, OverflowError):
            return None
        return None

    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none", "-"):
        return None
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = text.split(" 00:00")[0]

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt and "%y" not in fmt:
            year = default_year or date.today().year
            try:
                return parsed.replace(year=year).date()
            except ValueError:
                return None
        return parsed.date()

    try:
        stamp = pd.to_datetime(text, dayfirst=True, errors="coerce")
        if pd.notna(stamp):
            return stamp.date()
    except (ValueError, TypeError):
        pass
    return None


_AMOUNT_RE = re.compile(r"-?\(?\s*[\d,]*\.?\d+\s*\)?")


def parse_amount(value) -> Optional[float]:
    """Return a signed float. Handles '1,234.56', '(45.60)', '45.60 CR', 'S$12'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "-", "--"):
        return None

    negative = False
    upper = text.upper()
    if re.search(r"\bCR\b", upper) and not re.search(r"\bDR\b", upper):
        cr_flag = True
    else:
        cr_flag = False
    if "(" in text and ")" in text:
        negative = True
    if text.lstrip().startswith("-"):
        negative = True

    cleaned = re.sub(r"(?i)\b(SGD|S\$|USD|US\$|\$|CR|DR)\b", "", text)
    cleaned = cleaned.replace("$", "")
    match = _AMOUNT_RE.search(cleaned.replace(" ", ""))
    if not match:
        return None
    number = match.group(0).replace(",", "").replace("(", "").replace(")", "").replace("-", "")
    try:
        amount = float(number)
    except ValueError:
        return None
    if negative:
        amount = -amount
    if cr_flag and amount > 0:
        # 'CR' in a plain amount column means money in.
        amount = amount
    return amount


def _looks_credit(drcr_value) -> Optional[bool]:
    if drcr_value is None:
        return None
    text = str(drcr_value).strip().upper()
    if not text:
        return None
    if text in ("CR", "C", "CREDIT", "DEPOSIT", "IN", "INFLOW", "+"):
        return True
    if text in ("DR", "D", "DEBIT", "WITHDRAWAL", "OUT", "OUTFLOW", "-"):
        return False
    if "CREDIT" in text or "DEPOSIT" in text or "REFUND" in text:
        return True
    if "DEBIT" in text or "WITHDRAW" in text or "PURCHASE" in text:
        return False
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def parse_tabular(data: bytes, filename: str, account_hint: str = "",
                  default_year: Optional[int] = None) -> ParsedDocument:
    doc = ParsedDocument(
        filename=filename,
        account=account_hint or _guess_account(filename),
        doc_type="tabular",
    )

    try:
        grids = _read_grids(data, filename)
    except Exception as exc:  # noqa: BLE001 - surface any reader failure to the UI
        doc.warnings.append(f"Could not read {filename}: {exc}")
        return doc

    for sheet_name, frame in grids:
        if frame is None or frame.empty:
            continue
        # Bank exports name the account in the rows above the table. That beats
        # guessing from the filename, and distinguishes two cards from one bank.
        if not account_hint:
            label = _account_from_preamble(frame)
            if label:
                doc.account = label
        header_row = _find_header_row(frame)
        if header_row is None:
            doc.warnings.append(
                f"{filename} [{sheet_name}]: no transaction header row found — sheet skipped."
            )
            continue

        headers = [str(h) if h is not None and str(h) != "nan" else ""
                   for h in frame.iloc[header_row].tolist()]
        body = frame.iloc[header_row + 1:].reset_index(drop=True)
        added = _rows_to_transactions(
            body, headers, doc, sheet_name, default_year
        )
        if added == 0:
            doc.warnings.append(
                f"{filename} [{sheet_name}]: header found but no readable rows."
            )

    if doc.transactions:
        months = sorted({t.month for t in doc.transactions if t.date})
        if months:
            doc.statement_month = months[-1]
    return doc


def _rows_to_transactions(body: pd.DataFrame, headers: List[str],
                          doc: ParsedDocument, sheet_name: str,
                          default_year: Optional[int]) -> int:
    date_idx = _match_column(headers, DATE_COLS)
    desc_idxs = _match_all_columns(headers, DESC_COLS)
    debit_idx = _match_column(headers, DEBIT_COLS, skip_foreign=True)
    credit_idx = _match_column(headers, CREDIT_COLS, skip_foreign=True)
    # Prefer an explicitly local/SGD amount column over a generic one.
    amount_idx = _match_column(headers, LOCAL_AMOUNT_COLS, skip_foreign=True)
    if amount_idx is None:
        amount_idx = _match_column(headers, AMOUNT_COLS, skip_foreign=True)
    currency_idx = _match_column(headers, CURRENCY_COLS, skip_foreign=True)
    foreign_currency_idx = _match_column(headers, FOREIGN_CURRENCY_COLS)
    foreign_idx = _match_column(headers, FOREIGN_AMOUNT_COLS)
    drcr_idx = _match_column(headers, DRCR_COLS)
    balance_idx = _match_column(headers, BALANCE_COLS)

    # Guard: a 'type' column that is really a description shouldn't be trusted.
    if debit_idx is not None and debit_idx == credit_idx:
        credit_idx = None
    # Never let a money/date/currency column double as a description column —
    # "Local Currency Type" matches DESC_COLS' "type" synonym.
    for idx in (debit_idx, credit_idx, amount_idx, date_idx, balance_idx,
                currency_idx, foreign_currency_idx, foreign_idx, drcr_idx):
        if idx is not None and idx in desc_idxs:
            desc_idxs.remove(idx)

    if date_idx is None:
        doc.warnings.append(f"{doc.filename} [{sheet_name}]: no date column found.")
        return 0
    if debit_idx is None and credit_idx is None and amount_idx is None:
        doc.warnings.append(f"{doc.filename} [{sheet_name}]: no amount column found.")
        return 0
    if not desc_idxs:
        doc.warnings.append(f"{doc.filename} [{sheet_name}]: no description column found.")
        return 0

    # A single signed Amount column is ambiguous: bank exports sign money out as
    # negative, whereas card exports list spend as positive and refunds as
    # negative. Decide once per sheet from the shape of the column.
    card_style = False
    if amount_idx is not None and debit_idx is None and credit_idx is None:
        positives = negatives = 0
        for _, row in body.iterrows():
            values = row.tolist()
            if amount_idx >= len(values):
                continue
            value = parse_amount(values[amount_idx])
            if value is None or abs(value) < 0.005:
                continue
            if value > 0:
                positives += 1
            else:
                negatives += 1
        total = positives + negatives
        card_style = total > 0 and positives / total >= 0.7
        if card_style and negatives:
            doc.notes.append(
                f"{doc.filename} [{sheet_name}]: single amount column is mostly "
                f"positive, so it reads as a card-style export — the "
                f"{negatives} negative amount(s) are treated as money in (refunds)."
            )

    count = 0
    for _, row in body.iterrows():
        values = row.tolist()

        def cell(idx):
            if idx is None or idx >= len(values):
                return None
            val = values[idx]
            if isinstance(val, float) and pd.isna(val):
                return None
            return val

        txn_date = parse_date(cell(date_idx), default_year)
        parts = []
        for idx in desc_idxs:
            val = cell(idx)
            if val is None:
                continue
            # Bank exports wrap long descriptions with embedded newlines
            # ("PAYNOW-FAST\nOTHR Transfer") — flatten to one line.
            text = re.sub(r"\s+", " ", str(val)).strip()
            if text and text.lower() not in ("nan", "none"):
                parts.append(text)
        raw_desc = " ".join(dict.fromkeys(parts)).strip()

        debit_val = parse_amount(cell(debit_idx)) if debit_idx is not None else None
        credit_val = parse_amount(cell(credit_idx)) if credit_idx is not None else None
        amount_val = parse_amount(cell(amount_idx)) if amount_idx is not None else None

        # Work out direction + magnitude.
        signed = None
        if debit_val and abs(debit_val) > 0:
            signed = -abs(debit_val)
        elif credit_val and abs(credit_val) > 0:
            signed = abs(credit_val)
        elif amount_val is not None and abs(amount_val) > 0:
            flag = _looks_credit(cell(drcr_idx)) if drcr_idx is not None else None
            raw_amount_text = str(cell(amount_idx) or "")
            if flag is None and re.search(r"\bCR\b", raw_amount_text.upper()):
                flag = True
            if flag is True:
                signed = abs(amount_val)
            elif flag is False:
                signed = -abs(amount_val)
            elif re.search(
                r"SALARY|\bSALA\b|PAYROLL|INTEREST|DIVIDEND|REFUND|REVERSAL|REBATE|"
                r"CASHBACK|DEPOSIT|RECEIVED|INCOMING|TRANSFER FROM|PAYMENT - THANK",
                raw_desc.upper(),
            ):
                signed = abs(amount_val)
            elif amount_val < 0:
                # Negative in a card-style column is a refund (money in);
                # negative in a bank-style signed column is money out.
                signed = abs(amount_val) if card_style else amount_val
            else:
                signed = -abs(amount_val)

        if signed is None or abs(signed) < 0.005:
            continue
        if not raw_desc and txn_date is None:
            continue
        if _is_summary_row(raw_desc):
            continue
        if txn_date is None:
            doc.skipped_lines.append(f"[{sheet_name}] undated row: {raw_desc[:70]}")
            continue

        # The settlement currency of the amount we recorded.
        settled_currency = "SGD"
        if currency_idx is not None:
            raw_ccy = str(cell(currency_idx) or "").strip().upper()[:3]
            if raw_ccy in CURRENCY_CODES:
                settled_currency = raw_ccy

        # The pre-conversion currency and amount, kept for reference only.
        currency = "SGD"
        original_amount = None
        if foreign_currency_idx is not None:
            raw_ccy = str(cell(foreign_currency_idx) or "").strip().upper()[:3]
            if raw_ccy in CURRENCY_CODES:
                currency = raw_ccy
        if foreign_idx is not None:
            original_amount = parse_amount(cell(foreign_idx))
            if original_amount is not None:
                original_amount = abs(original_amount)
                if original_amount == 0:
                    original_amount = None

        note = ""
        needs_review = False
        if original_amount is not None and currency == "SGD":
            # A foreign amount with no currency named: keep it but say so.
            currency = "FX"
            note = "Statement showed a foreign amount without naming the currency."
            needs_review = True
        if settled_currency != "SGD":
            # We were not given an SGD figure at all, and we will not invent a
            # rate — surface it instead of quietly mixing currencies.
            note = (f"This row settled in {settled_currency}, not SGD. The amount is "
                    f"as the statement gave it — convert it yourself before relying "
                    f"on the totals.")
            needs_review = True

        txn = Transaction(
            date=txn_date,
            description="",
            raw_description=raw_desc or "(no description)",
            amount_sgd=round(abs(signed), 2),
            direction=CREDIT if signed > 0 else DEBIT,
            source_account=doc.account,
            source_file=doc.filename,
            original_currency=currency,
            original_amount=original_amount,
            needs_review=needs_review,
            review_note=note,
        )
        doc.transactions.append(txn)
        count += 1

    return count


_SUMMARY_RE = re.compile(
    r"^(total|subtotal|sub total|balance|opening balance|closing balance|"
    r"previous balance|new balance|minimum payment|credit limit|statement|"
    r"grand total|end of|page \d+|available credit|amount due|payment due)",
    re.IGNORECASE,
)


def _is_summary_row(text: str) -> bool:
    return bool(_SUMMARY_RE.match(text.strip())) if text else False


_ACCOUNT_HINTS = [
    (r"\bposb\b", "POSB"),
    (r"\bdbs\b", "DBS"),
    (r"\bocbc\b", "OCBC"),
    (r"\buob\b", "UOB"),
    (r"\bcitibank\b|\bciti\b", "Citibank"),
    (r"\bhsbc\b", "HSBC"),
    (r"\bstandard\s*chartered\b|\bscb\b", "Standard Chartered"),
    (r"\bamex\b|american\s*express", "Amex"),
    (r"\bmaybank\b", "Maybank"),
    (r"\bcimb\b", "CIMB"),
    (r"\btrust\s*bank\b|\btrust\b", "Trust Bank"),
    (r"\bgxs\b", "GXS"),
    (r"\bmari\b", "MariBank"),
    (r"\byoutrip\b", "YouTrip"),
    (r"\brevolut\b", "Revolut"),
    (r"\bwise\b", "Wise"),
]


_ACCOUNT_TYPE_LABEL = re.compile(
    r"^(account\s*(type|name)|card\s*(type|name)|product)\s*:?\s*$", re.IGNORECASE
)
_ACCOUNT_NUMBER_LABEL = re.compile(
    r"^(account|card)\s*(no|number)\.?\s*:?\s*$", re.IGNORECASE
)


def _account_from_preamble(frame: pd.DataFrame, scan_rows: int = 25) -> str:
    """Read "Account Type: VISA SIGNATURE" / "Account Number: 4006...0691" from
    the rows above the transaction table, and build "Visa Signature ••0691"."""
    kind = ""
    last4 = ""
    limit = min(scan_rows, len(frame))
    for row_idx in range(limit):
        cells = [("" if c is None or (isinstance(c, float) and pd.isna(c))
                  else re.sub(r"\s+", " ", str(c)).strip())
                 for c in frame.iloc[row_idx].tolist()]
        for col, cell in enumerate(cells):
            if not cell:
                continue
            value = next((c for c in cells[col + 1:] if c), "")
            if not value:
                continue
            if not kind and _ACCOUNT_TYPE_LABEL.match(cell):
                kind = value
            elif not last4 and _ACCOUNT_NUMBER_LABEL.match(cell):
                digits = re.sub(r"\D", "", value)
                if len(digits) >= 4:
                    last4 = digits[-4:]
    if not kind:
        return ""
    kind = kind.title().replace("'S", "'s")
    return f"{kind} ••{last4}" if last4 else kind


def _guess_account(filename: str) -> str:
    lower = filename.lower()
    bank = ""
    for pattern, label in _ACCOUNT_HINTS:
        if re.search(pattern, lower):
            bank = label
            break
    kind = ""
    if re.search(r"card|credit|visa|master|platinum|ladies|krisflyer|prvi|"
                 r"one\s*card|lady|rewards", lower):
        kind = "Card"
    elif re.search(r"saving|account|statement|multiplier|360|transaction|casa", lower):
        kind = "Account"
    label = " ".join(p for p in (bank, kind) if p)
    return label or filename.rsplit(".", 1)[0][:40]
