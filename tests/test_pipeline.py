"""End-to-end and unit tests. Run: .venv/bin/python -m pytest tests -q"""
from __future__ import annotations

import glob
import io
import os
import sys
from datetime import date

import json

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finance.describe import MAX_WORDS, summarise
from finance.export_excel import build_workbook
from finance.ingest import ingest_files
from finance.model import (
    CAT_ADDITIONAL_INCOME,
    CAT_CARD_PAYMENT,
    CAT_EXPERIENCES,
    CAT_FOOD,
    CAT_GROCERIES,
    CAT_INSURANCE,
    CAT_INTERNAL_TRANSFER,
    CAT_PARENTS,
    CAT_SALARY,
    CAT_SHOPPING,
    CAT_SUBSCRIPTIONS,
    CAT_TAX,
    CAT_TELCO,
    CAT_TRANSPORT_CAB,
    CAT_TRANSPORT_CAR,
    CAT_TRANSPORT_PUBLIC,
    CAT_UNCATEGORISED,
    CREDIT,
    DEBIT,
    EXCLUDED,
    Transaction,
)
from finance.parse_tabular import parse_amount, parse_date, parse_tabular
from finance.report import (
    BASIS_GROSS,
    BASIS_NET,
    annual_summary,
    available_months,
    build_pnl,
    category_by_month,
    compilation_frame,
    expense_breakdown,
    income_breakdown,
    line_transactions,
    months_in_year,
    savings_split,
    trendlines,
    years_with_months,
    ytd_series,
)
from finance.rules import Categoriser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "sample_data")


@pytest.fixture(scope="module")
def parsed():
    files = [(os.path.basename(p), open(p, "rb").read())
             for p in sorted(glob.glob(os.path.join(SAMPLES, "*")))]
    assert files, "run `python make_samples.py` first"
    return ingest_files(files, fallback_month="2025-06")


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,direction,expected", [
    # Revenue
    ("SALA NORTHWIND ANALYTICS PTE LTD JUN SALARY", CREDIT, CAT_SALARY),
    ("GIRO SALARY CREDIT", CREDIT, CAT_SALARY),
    ("BONUS INTEREST MULTIPLIER ACCOUNT", CREDIT, CAT_ADDITIONAL_INCOME),
    ("DIVIDEND CDP SECURITIES", CREDIT, CAT_ADDITIONAL_INCOME),
    # Fixed
    ("AIA SINGAPORE PTE LTD POLICY 88213", DEBIT, CAT_INSURANCE),
    ("GREAT EASTERN LIFE ASSURANCE", DEBIT, CAT_INSURANCE),
    ("NTUC INCOME INSURANCE PREMIUM", DEBIT, CAT_INSURANCE),
    ("SINGTEL MOBILE BILL 4471", DEBIT, CAT_TELCO),
    ("CIRCLES LIFE SINGAPORE", DEBIT, CAT_TELCO),
    ("STARHUB BROADBAND SERVICES", DEBIT, CAT_TELCO),
    ("SPOTIFY AB STOCKHOLM", DEBIT, CAT_SUBSCRIPTIONS),
    ("APPLE COM BILL ITUNES", DEBIT, CAT_SUBSCRIPTIONS),
    ("GOOGLE ONE STORAGE", DEBIT, CAT_SUBSCRIPTIONS),
    ("ANYTIME FITNESS BUKIT TIMAH", DEBIT, CAT_SUBSCRIPTIONS),
    ("VIRGIN ACTIVE SINGAPORE", DEBIT, CAT_SUBSCRIPTIONS),
    # Variable
    ("GRAB A-7HKQMNP SINGAPORE SG", DEBIT, CAT_TRANSPORT_CAB),
    ("TRANSITLINK SIMPLYGO", DEBIT, CAT_TRANSPORT_PUBLIC),
    ("NETS FLASHPAY TOP UP", DEBIT, CAT_TRANSPORT_PUBLIC),
    ("SHELL SERVICE STATION 07", DEBIT, CAT_TRANSPORT_CAR),
    ("HDB CARPARK SEASON PARKING", DEBIT, CAT_TRANSPORT_CAR),
    ("GRABFOOD SINGAPORE SG", DEBIT, CAT_FOOD),
    ("FOODPANDA SG SINGAPORE", DEBIT, CAT_FOOD),
    ("DELIVEROO SINGAPORE", DEBIT, CAT_FOOD),
    ("DIN TAI FUNG PARAGON", DEBIT, CAT_FOOD),
    ("CRYSTAL JADE KITCHEN", DEBIT, CAT_FOOD),
    ("PAYNOW TRANSFER TO TAN WEI MING DINNER SHARE", DEBIT, CAT_FOOD),
    ("NTUC FAIRPRICE FINEST", DEBIT, CAT_GROCERIES),
    ("SHENG SIONG SUPERMARKET", DEBIT, CAT_GROCERIES),
    ("COLD STORAGE JELITA", DEBIT, CAT_GROCERIES),
    ("SHOPEE SINGAPORE", DEBIT, CAT_SHOPPING),
    ("UNIQLO ORCHARD CENTRAL", DEBIT, CAT_SHOPPING),
    ("IKEA TAMPINES", DEBIT, CAT_SHOPPING),
    ("CLIMB CENTRAL KALLANG", DEBIT, CAT_EXPERIENCES),
    ("RAFFLES MEDICAL CLINIC", DEBIT, CAT_EXPERIENCES),
    ("GOLDEN VILLAGE VIVOCITY", DEBIT, CAT_EXPERIENCES),
    ("AGODA COM SINGAPORE", DEBIT, CAT_EXPERIENCES),
    ("SINGAPORE AIRLINES LTD", DEBIT, CAT_EXPERIENCES),
    ("FUNDS TRANSFER TO YOUTRIP TOP UP", DEBIT, CAT_EXPERIENCES),
    ("MARRIOTT HOTEL BANGKOK", DEBIT, CAT_EXPERIENCES),
    # Excluded transfers
    ("PAYMENT - THANK YOU", CREDIT, CAT_CARD_PAYMENT),
    ("PAYMENT RECEIVED - THANK YOU", CREDIT, CAT_CARD_PAYMENT),
    ("CREDIT CARD PAYMENT OCBC 90N CARD", DEBIT, CAT_CARD_PAYMENT),
    ("FUNDS TRANSFER TO OWN ACCOUNT SAVINGS", DEBIT, CAT_INTERNAL_TRANSFER),
])
def test_categories(raw, direction, expected):
    category, _rule, _review, _note = Categoriser().categorise(raw, direction)
    assert category == expected, f"{raw!r} -> {category}"


SAMPLE_PARENTS = ["ALEX TAN", "JAMIE LOW", "SAM LIM"]


@pytest.mark.parametrize("raw", [
    "PAYNOW TRANSFER TO ALEX TAN MONTHLY ALLOWANCE",
    "PAYNOW TRANSFER TO JAMIE LOW",
    "FAST TRANSFER TO SAM LIM",
])
def test_configured_parent_names_are_an_allowance(raw):
    """No names ship in source — they are real people — so they are supplied."""
    engine = Categoriser(parent_names=SAMPLE_PARENTS)
    assert engine.categorise(raw, DEBIT)[0] == CAT_PARENTS


def test_no_parent_names_by_default():
    from finance.rules import DEFAULT_PARENT_NAMES
    assert DEFAULT_PARENT_NAMES == []
    assert Categoriser().categorise(
        "PAYNOW TRANSFER TO ALEX TAN", DEBIT)[0] != CAT_PARENTS


def test_grabfood_beats_grab_ride():
    """Ordering matters: GrabFood must not be booked as transport."""
    cat, _, _, _ = Categoriser().categorise("GRABFOOD SINGAPORE", DEBIT)
    assert cat == CAT_FOOD
    cat, _, _, _ = Categoriser().categorise("GRAB RIDE SINGAPORE", DEBIT)
    assert cat == CAT_TRANSPORT_CAB


def test_multiword_merchants_actually_match():
    """Regression: re.escape escapes spaces, which used to break every
    multi-word merchant pattern silently."""
    engine = Categoriser()
    for raw, expected in [
        ("CIRCLES LIFE SINGAPORE", CAT_TELCO),
        ("VIRGIN ACTIVE SINGAPORE", CAT_SUBSCRIPTIONS),
        ("SINGAPORE AIRLINES LTD", CAT_EXPERIENCES),
        ("CRYSTAL JADE KITCHEN", CAT_FOOD),
        ("GREAT EASTERN LIFE", CAT_INSURANCE),
    ]:
        assert engine.categorise(raw, DEBIT)[0] == expected, raw


def test_word_boundaries_not_substrings():
    """'SIA ' must not fire inside 'MALAYSIA'."""
    cat, rule, _, _ = Categoriser().categorise("MALAYSIA GROCER MART", DEBIT)
    assert cat == CAT_GROCERIES  # matched GROCER, not the SIA airline entry


def test_refund_nets_against_original_category():
    cat, rule, _, _ = Categoriser().categorise("REFUND - IKEA TAMPINES", CREDIT)
    assert cat == CAT_SHOPPING
    assert rule == "refund-to-merchant"


def test_parent_names_are_configurable():
    engine = Categoriser(parent_names=["MARY TAN"])
    assert engine.categorise("PAYNOW TRANSFER TO MARY TAN", DEBIT)[0] == CAT_PARENTS
    assert engine.categorise("PAYNOW TRANSFER TO ALEX TAN", DEBIT)[0] != CAT_PARENTS


def test_employer_keyword_catches_salary():
    engine = Categoriser(employer_keywords=["NORTHWIND ANALYTICS"])
    assert engine.categorise("IBG NORTHWIND ANALYTICS PTE LTD", CREDIT)[0] == CAT_SALARY


# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------
def test_description_is_at_most_ten_words():
    long_raw = ("POS PURCHASE SOME VERY LONG MERCHANT NAME TRADING COMPANY "
                "PRIVATE LIMITED SINGAPORE SG REF 123456789 TXN 99")
    assert len(summarise(long_raw).split()) <= MAX_WORDS


@pytest.mark.parametrize("raw,expected", [
    ("GRABFOOD SINGAPORE SG", "GrabFood order"),
    ("SPOTIFY AB STOCKHOLM", "Spotify subscription"),
    ("SALA NORTHWIND ANALYTICS", "Monthly salary credited"),
    ("TRANSITLINK SIMPLYGO", "Public transport fare"),
])
def test_canonical_descriptions(raw, expected):
    assert summarise(raw) == expected


def test_description_keeps_transfer_payee():
    out = summarise("PAYNOW TRANSFER TO ALEX TAN", CAT_PARENTS, DEBIT)
    assert "Alex Tan" in out
    assert len(out.split()) <= MAX_WORDS


def test_description_never_empty():
    assert summarise("") == "Unlabelled transaction"
    assert summarise("   ###   ") != ""


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("1,234.56", 1234.56),
    ("(45.60)", -45.60),
    ("-45.60", -45.60),
    ("S$12.00", 12.0),
    ("45.60 CR", 45.60),
    ("", None),
    ("-", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("01/06/2025", date(2025, 6, 1)),
    ("2025-06-01", date(2025, 6, 1)),
    ("1 Jun 2025", date(2025, 6, 1)),
    ("01-JUN-2025", date(2025, 6, 1)),
    ("June 1, 2025", date(2025, 6, 1)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_defaults_year_when_absent():
    assert parse_date("18 Jun", default_year=2024) == date(2024, 6, 18)


def test_dayfirst_not_monthfirst():
    """13/06 must be 13 June, not an error or June 13 read as month 13."""
    assert parse_date("13/06/2025") == date(2025, 6, 13)


# ---------------------------------------------------------------------------
# Tabular parsing edge cases
# ---------------------------------------------------------------------------
def test_preamble_above_header_is_skipped():
    csv_text = (
        "Account Details For:,My Account\n"
        "Available Balance:,100.00\n"
        "\n"
        "Transaction Date,Debit Amount,Credit Amount,Transaction Ref1\n"
        "01/06/2025,50.00,,COFFEE BEAN\n"
        "02/06/2025,,6800.00,SALA EMPLOYER\n"
    )
    doc = parse_tabular(csv_text.encode(), "test.csv")
    assert len(doc.transactions) == 2, doc.warnings
    assert doc.transactions[0].direction == DEBIT
    assert doc.transactions[1].direction == CREDIT
    assert doc.transactions[1].amount_sgd == 6800.00


def test_posting_date_column_is_not_read_as_amount():
    """Regression: the 'in'/'out' synonyms used to substring-match
    'Posting Date', turning a day-of-month into the amount."""
    csv_text = (
        "Transaction Date,Posting Date,Description,Transaction Amount (SGD)\n"
        "03/06/2025,04/06/2025,GRABFOOD SINGAPORE,24.80\n"
    )
    doc = parse_tabular(csv_text.encode(), "card.csv")
    assert len(doc.transactions) == 1
    assert doc.transactions[0].amount_sgd == 24.80


def test_signed_amount_column_bank_style():
    """Mostly-negative column = bank export: negative is money out."""
    csv_text = (
        "Date,Description,Amount\n"
        "01/06/2025,COFFEE BEAN,-5.00\n"
        "02/06/2025,FAIRPRICE,-40.00\n"
        "03/06/2025,SHOPEE,-20.00\n"
        "04/06/2025,SALA EMPLOYER,6800.00\n"
    )
    doc = parse_tabular(csv_text.encode(), "bank.csv")
    by_desc = {t.raw_description: t for t in doc.transactions}
    assert by_desc["COFFEE BEAN"].direction == DEBIT
    assert by_desc["SALA EMPLOYER"].direction == CREDIT


def test_signed_amount_column_card_style():
    """Mostly-positive column = card export: negative is a refund (money in)."""
    csv_text = (
        "Date,Description,Amount\n"
        "01/06/2025,COFFEE BEAN,5.00\n"
        "02/06/2025,FAIRPRICE,40.00\n"
        "03/06/2025,UNIQLO,60.00\n"
        "04/06/2025,IKEA TAMPINES,80.00\n"
        "05/06/2025,REFUND IKEA TAMPINES,-30.00\n"
    )
    doc = parse_tabular(csv_text.encode(), "card.csv")
    by_desc = {t.raw_description: t for t in doc.transactions}
    assert by_desc["COFFEE BEAN"].direction == DEBIT
    assert by_desc["REFUND IKEA TAMPINES"].direction == CREDIT


def test_drcr_indicator_column():
    csv_text = (
        "Date,Description,Amount,DR/CR\n"
        "01/06/2025,COFFEE BEAN,5.00,DR\n"
        "02/06/2025,INTEREST EARNED,1.20,CR\n"
    )
    doc = parse_tabular(csv_text.encode(), "bank.csv")
    assert doc.transactions[0].direction == DEBIT
    assert doc.transactions[1].direction == CREDIT


def test_summary_rows_are_not_transactions():
    csv_text = (
        "Date,Description,Debit,Credit\n"
        "01/06/2025,COFFEE BEAN,5.00,\n"
        ",Total Debit,5.00,\n"
        ",Closing Balance,,100.00\n"
    )
    doc = parse_tabular(csv_text.encode(), "bank.csv")
    assert len(doc.transactions) == 1


def test_unreadable_file_reports_a_warning_not_a_crash():
    doc = parse_tabular(b"\x00\x01 not a spreadsheet", "junk.csv")
    assert doc.transactions == []
    assert doc.warnings


def test_unsupported_extension_is_reported():
    from finance.ingest import parse_upload
    doc = parse_upload(b"data", "statement.docx")
    assert doc.warnings and "unsupported" in doc.warnings[0].lower()


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
def test_all_sample_files_parse(parsed):
    txns, docs, _notes = parsed
    for doc in docs:
        assert doc.transactions, f"{doc.filename} produced nothing: {doc.warnings}"
        assert not doc.warnings, doc.warnings
    assert len(txns) > 60


def test_pdf_reads_foreign_currency_detail(parsed):
    txns, _docs, _notes = parsed
    fx = [t for t in txns if t.original_currency != "SGD"]
    currencies = {t.original_currency for t in fx}
    assert {"USD", "THB"} <= currencies, currencies
    thb = next(t for t in fx if t.original_currency == "THB")
    assert thb.original_amount == 10800.00
    # The SGD figure must be the bank's converted amount, not the FX amount.
    assert thb.amount_sgd == 412.66


def test_fx_rate_line_does_not_pollute_description(parsed):
    txns, _docs, _notes = parsed
    assert not [t for t in txns if "EXCHANGE RATE" in t.raw_description.upper()]


def test_pdf_without_line_dates_uses_statement_period(parsed):
    txns, _docs, _notes = parsed
    inferred = [t for t in txns if t.date_is_inferred]
    assert inferred, "the dateless Citi PDF should produce inferred dates"
    assert all(t.source_file.startswith("citi") for t in inferred)
    assert all(t.date == date(2025, 6, 20) for t in inferred)


def test_transactions_are_chronological(parsed):
    txns, _docs, _notes = parsed
    dates = [t.date for t in txns]
    assert dates == sorted(dates)


def test_every_description_within_ten_words(parsed):
    txns, _docs, _notes = parsed
    for txn in txns:
        assert 1 <= len(txn.description.split()) <= MAX_WORDS, txn.description


def test_card_bill_payments_are_excluded_from_pnl(parsed):
    txns, _docs, _notes = parsed
    excluded = [t for t in txns if t.section == EXCLUDED]
    assert len(excluded) >= 4
    pnl = build_pnl(txns, "2025-06")
    # None of the excluded amounts may appear in any P&L total.
    assert pnl.excluded_count == len([t for t in txns
                                      if t.month == "2025-06" and t.section == EXCLUDED])


def test_pnl_arithmetic(parsed):
    txns, _docs, _notes = parsed
    pnl = build_pnl(txns, "2025-06")
    assert pnl.total_revenue == pytest.approx(
        pnl.salary_credited + pnl.cpf_employee + pnl.additional_income)
    assert pnl.total_expenses == pytest.approx(pnl.total_fixed + pnl.total_variable)
    assert pnl.net_income == pytest.approx(pnl.total_revenue - pnl.total_expenses)


def test_pnl_cpf_respects_the_ordinary_wage_ceiling(parsed):
    """The June 2025 sample credits S$6,800, above the S$7,400 ceiling once
    grossed up, so the employee share is capped rather than a flat 20%."""
    txns, _docs, _notes = parsed
    pnl = build_pnl(txns, "2025-06")
    assert pnl.cpf is not None
    assert pnl.cpf.ceiling == 7400          # 2025 ceiling
    assert pnl.cpf_employee <= 0.20 * 7400 + 0.5
    # Salary credited plus the employee share is the true gross.
    assert pnl.salary_credited + pnl.cpf_employee == pytest.approx(
        pnl.cpf.gross_ow, abs=1.0)


def test_employer_cpf_is_opt_in(parsed):
    txns, _docs, _notes = parsed
    without = build_pnl(txns, "2025-06")
    with_employer = build_pnl(txns, "2025-06", include_employer_cpf=True)
    assert with_employer.total_revenue == pytest.approx(
        without.total_revenue + without.cpf_employer)


def test_pnl_section_totals_match_transactions(parsed):
    """Every non-excluded transaction must land in exactly one P&L line."""
    txns, _docs, _notes = parsed
    pnl = build_pnl(txns, "2025-06")
    month = [t for t in txns if t.month == "2025-06" and t.section != EXCLUDED]
    net = sum(t.signed_amount for t in month)
    # Revenue is money in, expenses money out. CPF never touched the bank
    # account, so it is excluded from the cash reconciliation.
    assert net == pytest.approx(
        pnl.total_revenue - pnl.cpf_employee - pnl.total_expenses, abs=0.01)


def test_salary_basis_changes_the_cpf_figure(parsed):
    """Treating the credit as gross gives a different CPF line than treating it
    as take-home, because the gross-up raises the wage the rates apply to."""
    txns, _docs, _notes = parsed
    as_net = build_pnl(txns, "2025-06", BASIS_NET)
    as_gross = build_pnl(txns, "2025-06", BASIS_GROSS)
    assert as_net.cpf.gross_ow > as_gross.cpf.gross_ow
    assert as_net.total_revenue >= as_gross.total_revenue


def test_compilation_frame_shape(parsed):
    txns, _docs, _notes = parsed
    frame = compilation_frame(txns, "2025-06")
    assert not frame.empty
    assert list(frame["Date"]) == sorted(frame["Date"])
    assert set(frame["Type"]) <= {DEBIT, CREDIT}
    assert (frame["Amount (SGD)"] > 0).all()


def test_months_split_by_transaction_date(parsed):
    txns, _docs, _notes = parsed
    assert available_months(txns) == ["2025-05", "2025-06"]


def test_duplicate_upload_is_deduplicated():
    path = os.path.join(SAMPLES, "dbs-multiplier-account-jun2025.csv")
    data = open(path, "rb").read()
    once, _, _ = ingest_files([("a.csv", data)])
    twice, _, notes = ingest_files([("a.csv", data), ("a.csv", data)])
    assert len(once) == len(twice)
    assert any("duplicate" in n.lower() for n in notes)


def test_excel_workbook_is_written(parsed, tmp_path):
    txns, _docs, _notes = parsed
    blob = build_workbook(txns, ["2025-06"])
    assert blob[:2] == b"PK"
    out = tmp_path / "book.xlsx"
    out.write_bytes(blob)
    sheets = pd.read_excel(out, sheet_name=None, header=None)
    assert "Summary" in sheets
    assert "P&L Jun 2025" in sheets
    assert "Transactions Jun 2025" in sheets
    flat = sheets["P&L Jun 2025"].astype(str).to_numpy().ravel()
    assert any("NET INCOME" in cell for cell in flat)


def test_excel_workbook_multi_month(parsed):
    txns, _docs, _notes = parsed
    blob = build_workbook(txns, ["2025-05", "2025-06"])
    sheets = pd.read_excel(io.BytesIO(blob), sheet_name=None, header=None)
    assert "P&L May 2025" in sheets and "P&L Jun 2025" in sheets


def test_empty_input_does_not_crash():
    txns, docs, notes = ingest_files([])
    assert txns == [] and docs == []
    assert build_workbook([], [])[:2] == b"PK"


# ---------------------------------------------------------------------------
# Annual overview data (the landing page)
# ---------------------------------------------------------------------------
def test_category_by_month_is_long_form_one_row_per_pair(parsed):
    """The dot plot needs a row per (category, month), not a wide table."""
    txns, _docs, _notes = parsed
    frame = category_by_month(txns)
    months = available_months(txns)
    assert set(frame.columns) == {"Category", "Section", "Month", "MonthLabel",
                                 "Amount", "Transactions"}
    # Every surviving category appears once per month, so the connecting line
    # has a point for each month even where the amount is zero.
    counts = frame.groupby("Category")["Month"].nunique()
    assert set(counts.unique()) == {len(months)}
    assert set(frame["Month"]) == set(months)


def test_category_by_month_drops_categories_with_no_activity(parsed):
    txns, _docs, _notes = parsed
    frame = category_by_month(txns)
    for category, group in frame.groupby("Category"):
        assert group["Amount"].abs().sum() > 0, category


def test_category_by_month_matches_the_monthly_pnl(parsed):
    """A category's dots must agree with what the income statement shows.

    Asks for all three sections; the default covers spending only, which is what
    the dot plot wants.
    """
    from finance.model import FIXED, REVENUE, VARIABLE
    txns, _docs, _notes = parsed
    frame = category_by_month(txns, sections=[REVENUE, FIXED, VARIABLE])
    for month_key in available_months(txns):
        pnl = build_pnl(txns, month_key)
        month_rows = frame[frame["Month"] == month_key]
        for line in pnl.lines:
            if line.kind != "item" or len(line.categories) != 1:
                continue
            match = month_rows[month_rows["Category"] == line.categories[0]]
            if match.empty:  # dropped as inactive all period
                assert line.amount == 0
                continue
            assert float(match["Amount"].iloc[0]) == pytest.approx(line.amount, abs=0.01)


def test_category_by_month_can_be_restricted_to_a_section(parsed):
    from finance.model import FIXED
    txns, _docs, _notes = parsed
    frame = category_by_month(txns, sections=[FIXED])
    assert set(frame["Section"]) == {FIXED}


def test_category_by_month_on_empty_input():
    frame = category_by_month([])
    assert frame.empty


def test_annual_summary_sums_the_months(parsed):
    txns, _docs, _notes = parsed
    summary = annual_summary(txns)
    months = available_months(txns)
    assert summary.months == months
    assert summary.month_count == len(months)
    assert summary.transaction_count == len(txns)

    monthly = [build_pnl(txns, m) for m in months]
    assert summary.total_revenue == pytest.approx(
        sum(p.total_revenue for p in monthly), abs=0.01)
    assert summary.total_expenses == pytest.approx(
        sum(p.total_expenses for p in monthly), abs=0.01)
    assert summary.net_income == pytest.approx(
        sum(p.net_income for p in monthly), abs=0.01)
    assert summary.net_income == pytest.approx(
        summary.total_revenue - summary.total_expenses, abs=0.01)
    assert summary.total_expenses == pytest.approx(
        summary.total_fixed + summary.total_variable, abs=0.01)


def test_annual_summary_averages_and_span(parsed):
    txns, _docs, _notes = parsed
    summary = annual_summary(txns)
    assert summary.avg_monthly_expenses == pytest.approx(
        summary.total_expenses / summary.month_count, abs=0.01)
    assert summary.avg_monthly_net == pytest.approx(
        summary.net_income / summary.month_count, abs=0.01)
    assert summary.span == "May 2025 – Jun 2025"
    assert summary.savings_rate == pytest.approx(
        summary.net_income / summary.total_revenue * 100, abs=0.1)


def test_annual_summary_counts_review_and_excluded(parsed):
    txns, _docs, _notes = parsed
    summary = annual_summary(txns)
    assert summary.review_count == sum(1 for t in txns if t.needs_review)
    assert summary.excluded_total > 0


def test_annual_summary_on_empty_input():
    summary = annual_summary([])
    assert summary.month_count == 0
    assert summary.total_revenue == 0
    assert summary.savings_rate is None
    assert summary.avg_monthly_expenses == 0
    assert summary.span == ""


def test_annual_summary_respects_employer_cpf_toggle(parsed):
    txns, _docs, _notes = parsed
    without = annual_summary(txns)
    with_employer = annual_summary(txns, include_employer_cpf=True)
    assert with_employer.total_revenue == pytest.approx(
        without.total_revenue + without.cpf_employer, abs=0.01)


def test_dot_plot_default_excludes_revenue(parsed):
    """Salary would dwarf every spending category and flatten the plot."""
    from finance.model import CAT_SALARY, REVENUE
    txns, _docs, _notes = parsed
    frame = category_by_month(txns)
    assert REVENUE not in set(frame["Section"])
    assert CAT_SALARY not in set(frame["Category"])


# ---------------------------------------------------------------------------
# Dashboard data: year tree, the three pies, and the YTD series
# ---------------------------------------------------------------------------
def test_years_with_months_groups_and_sorts(parsed):
    txns, _docs, _notes = parsed
    tree = years_with_months(txns)
    assert list(tree) == ["2025"]
    assert tree["2025"] == ["2025-05", "2025-06"]
    assert months_in_year(txns, "2025") == ["2025-05", "2025-06"]
    assert months_in_year(txns, "1999") == []


def test_income_breakdown_sums_to_total_revenue(parsed):
    txns, _docs, _notes = parsed
    months = available_months(txns)
    frame = income_breakdown(txns, months)
    expected = sum(build_pnl(txns, m).total_revenue for m in months)
    assert frame["Amount"].sum() == pytest.approx(expected, abs=0.02)
    assert "CPF — employee share" in set(frame["Source"])
    # A zero source is dropped rather than drawn as an invisible wedge.
    assert (frame["Amount"] != 0).all()


def test_income_breakdown_adds_the_employer_slice_when_asked(parsed):
    txns, _docs, _notes = parsed
    months = available_months(txns)
    without = income_breakdown(txns, months)
    with_employer = income_breakdown(txns, months, include_employer_cpf=True)
    assert "CPF — employer share" not in set(without["Source"])
    assert "CPF — employer share" in set(with_employer["Source"])
    assert with_employer["Amount"].sum() > without["Amount"].sum()


def test_expense_breakdown_is_tagged_and_ordered(parsed):
    txns, _docs, _notes = parsed
    frame = expense_breakdown(txns, available_months(txns))
    assert set(frame["Section"]) <= {"Fixed", "Variable"}
    assert list(frame["Amount"]) == sorted(frame["Amount"], reverse=True)
    # Sections must match where each category actually sits in the statement.
    from finance.model import FIXED_CATEGORIES
    for row in frame.itertuples():
        expected = "Fixed" if row.Category in FIXED_CATEGORIES else "Variable"
        assert row.Section == expected, row.Category


def test_expense_breakdown_sums_to_total_expenses(parsed):
    txns, _docs, _notes = parsed
    months = available_months(txns)
    frame = expense_breakdown(txns, months)
    expected = sum(build_pnl(txns, m).total_expenses for m in months)
    assert frame["Amount"].sum() == pytest.approx(expected, abs=0.02)


def test_savings_split_covers_the_whole_of_revenue(parsed):
    txns, _docs, _notes = parsed
    months = available_months(txns)
    frame = savings_split(txns, months)
    expected = sum(build_pnl(txns, m).total_revenue for m in months)
    assert frame["Amount"].sum() == pytest.approx(expected, abs=0.02)
    assert set(frame["Part"]) <= {"Saved", "Spent"}


def test_savings_split_drops_a_negative_wedge():
    """A month that spent more than it earned cannot be drawn as a pie."""
    from finance.model import Transaction, CAT_FOOD, DEBIT
    from datetime import date as _date
    spent_only = [Transaction(date=_date(2025, 6, 3), description="Lunch",
                              raw_description="LUNCH", amount_sgd=40.0,
                              direction=DEBIT, category=CAT_FOOD)]
    frame = savings_split(spent_only, ["2025-06"])
    assert list(frame["Part"]) == ["Spent"]


def test_ytd_series_has_a_row_per_calendar_month_and_measure(parsed):
    txns, _docs, _notes = parsed
    months = available_months(txns)
    frame = ytd_series(txns, months)
    assert len(frame) == 12 * 3                 # the axis always runs Jan-Dec
    assert set(frame["Measure"]) == {"Income", "Expenses", "Savings"}
    # Savings is Income minus Expenses, month by month.
    wide = frame.pivot(index="Month", columns="Measure", values="Amount")
    for month in months:
        assert wide.loc[month, "Savings"] == pytest.approx(
            wide.loc[month, "Income"] - wide.loc[month, "Expenses"], abs=0.02)


def test_ytd_series_keeps_empty_months_as_columns_without_amounts(parsed):
    """The column holds its place so the year reads Jan-Dec, but an unloaded
    month carries no amount — a zero there would read as 'earned nothing'."""
    txns, _docs, _notes = parsed
    loaded = set(available_months(txns))
    frame = ytd_series(txns, available_months(txns))

    assert set(frame["Month"]) >= loaded
    assert "2025-01" in set(frame["Month"])     # present as a column...
    january = frame[frame["Month"] == "2025-01"]
    assert january["Amount"].isna().all()       # ...with nothing plotted
    assert not january["HasData"].any()

    for month in loaded:
        rows = frame[frame["Month"] == month]
        assert rows["Amount"].notna().all()
        assert rows["HasData"].all()


def test_ytd_series_reports_change_against_previous_month_and_average(parsed):
    txns, _docs, _notes = parsed
    frame = ytd_series(txns, available_months(txns))
    income = frame[(frame["Measure"] == "Income") & frame["HasData"]].sort_values("Order")
    assert len(income) >= 2

    # The first month with data has nothing to compare against.
    assert pd.isna(income.iloc[0]["PrevChange"])
    first, second = income.iloc[0]["Amount"], income.iloc[1]["Amount"]
    if first:
        assert income.iloc[1]["PrevChange"] == pytest.approx(
            (second - first) / abs(first) * 100)

    mean = income["Amount"].mean()
    if mean:
        assert income.iloc[0]["AvgChange"] == pytest.approx(
            (first - mean) / abs(mean) * 100)


def test_trendlines_ignore_months_with_no_data(parsed):
    """A null month must not drag the fit towards zero."""
    txns, _docs, _notes = parsed
    full = trendlines(ytd_series(txns, available_months(txns)))
    assert len(full) == 6
    assert full["Fit"].notna().all()


def test_trendlines_give_two_endpoints_per_measure(parsed):
    txns, _docs, _notes = parsed
    series = ytd_series(txns, available_months(txns))
    fits = trendlines(series)
    assert len(fits) == 6                       # 3 measures x 2 endpoints
    assert set(fits["Measure"]) == {"Income", "Expenses", "Savings"}


def test_trendline_is_a_least_squares_fit():
    """A straight input must come back as itself."""
    import pandas as _pd
    series = _pd.DataFrame([
        {"Month": f"2025-0{i+1}", "MonthLabel": f"M{i}", "Order": i,
         "Measure": "Income", "Amount": 100.0 + 50.0 * i}
        for i in range(4)
    ])
    fits = trendlines(series).sort_values("Order")
    assert list(fits["Fit"]) == pytest.approx([100.0, 250.0])


def test_trendlines_need_two_points():
    import pandas as _pd
    single = _pd.DataFrame([{"Month": "2025-06", "MonthLabel": "Jun", "Order": 0,
                             "Measure": "Income", "Amount": 10.0}])
    assert trendlines(single).empty
    assert trendlines(_pd.DataFrame()).empty


def test_dashboard_frames_survive_empty_input():
    assert income_breakdown([], []).empty
    assert expense_breakdown([], []).empty
    assert savings_split([], []).empty
    assert ytd_series([], []).empty
    assert years_with_months([]) == {}


# ---------------------------------------------------------------------------
# The category model after App requirements.xlsx v1
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("GRAB *A-7HKQ SINGAPORE", CAT_TRANSPORT_CAB),
    ("COMFORTDELGRO TAXI", CAT_TRANSPORT_CAB),
    ("SMRT SIMPLYGO TOP UP", CAT_TRANSPORT_PUBLIC),
    ("EZ-LINK CONCESSION", CAT_TRANSPORT_PUBLIC),
    ("CALTEX SERVICE STATION", CAT_TRANSPORT_CAR),
    ("VICOM INSPECTION CENTRE", CAT_TRANSPORT_CAR),
    ("WILSON PARKING PTE LTD", CAT_TRANSPORT_CAR),
])
def test_transport_splits_three_ways(raw, expected):
    assert Categoriser().categorise(raw, DEBIT)[0] == expected


@pytest.mark.parametrize("raw", [
    "IRAS INCOME TAX",
    "GIRO IRAS PROPERTY TAX",
    "INLAND REVENUE AUTHORITY",
])
def test_tax_is_a_fixed_commitment_not_a_stray_debit(raw):
    from finance.model import FIXED, section_for
    category = Categoriser().categorise(raw, DEBIT)[0]
    assert category == CAT_TAX
    assert section_for(category) == FIXED


def test_road_tax_is_a_car_cost_not_an_iras_bill():
    """'ROAD TAX' contains 'TAX' but is what you pay to keep a car on the road."""
    assert Categoriser().categorise("ROAD TAX RENEWAL", DEBIT)[0] == CAT_TRANSPORT_CAR


def test_legacy_category_names_are_carried_forward(tmp_path):
    """A saved fix must survive a rename, or the user silently loses it."""
    from finance.model import migrate_category
    from finance.rules import _load_overrides

    path = tmp_path / "category_overrides.json"
    path.write_text(json.dumps({
        "kopitiam": "Food & Dining",
        "grabfood": "Food Delivery",
        "agoda": "Travel",
        "mystery": "Other",
        "someshop": "Transport",
    }))
    loaded = _load_overrides(str(path))

    assert loaded["kopitiam"] == CAT_FOOD
    assert loaded["grabfood"] == CAT_FOOD
    assert loaded["agoda"] == CAT_EXPERIENCES
    assert loaded["mystery"] == CAT_UNCATEGORISED
    # Transport split three ways with nothing in the old name to say which, so
    # the override is dropped and the rules decide again.
    assert "someshop" not in loaded
    assert migrate_category("Transport") is None


def test_a_custom_category_lands_in_its_section():
    from finance import model
    try:
        model.register_custom_category("Pet care", model.VARIABLE)
        assert model.section_for("Pet care") == model.VARIABLE
        assert "Pet care" in model.ASSIGNABLE_CATEGORIES
        with pytest.raises(ValueError):
            model.register_custom_category("Pet care", model.VARIABLE)
        with pytest.raises(ValueError):
            model.register_custom_category("Insurance", model.FIXED)
    finally:
        model.forget_custom_categories()
    assert "Pet care" not in model.VARIABLE_CATEGORIES


# ---------------------------------------------------------------------------
# The dashboard and monthly-page data
# ---------------------------------------------------------------------------
def test_section_items_list_every_transaction_with_a_payment_method(parsed):
    from finance.model import VARIABLE
    from finance.report import section_items
    txns, _docs, _notes = parsed
    month = available_months(txns)[0]
    frame = section_items(txns, month, VARIABLE)

    expected = [t for t in txns if t.month == month and t.section == VARIABLE]
    assert len(frame) == len(expected)
    assert list(frame.columns)[:4] == ["Item", "Category", "Payment Method", "Amount"]
    assert (frame["Payment Method"] != "").all()
    # Expenses read positive inside a section already called Expenses.
    spend = [t for t in expected if t.direction == DEBIT]
    if spend:
        assert frame["Amount"].max() > 0


def test_section_items_total_matches_the_pnl(parsed):
    from finance.model import FIXED, VARIABLE
    from finance.report import build_pnl, section_items
    txns, _docs, _notes = parsed
    month = available_months(txns)[0]
    pnl = build_pnl(txns, month)
    for section, total in ((FIXED, pnl.total_fixed), (VARIABLE, pnl.total_variable)):
        frame = section_items(txns, month, section)
        assert frame["Amount"].sum() == pytest.approx(total, abs=0.02)


def test_income_sources_name_the_payer_and_the_latest_payment(parsed):
    from finance.report import income_sources
    txns, _docs, _notes = parsed
    frame = income_sources(txns, available_months(txns))
    if frame.empty:
        pytest.skip("no income in the sample statements")
    assert len(frame) <= 3
    assert list(frame["Total"]) == sorted(frame["Total"], reverse=True)
    for row in frame.itertuples():
        assert row.Source and row.Source.strip()
        assert not any(ch.isdigit() for ch in row.Source)
        assert row.LastAmount <= row.Total + 0.01
        assert row.Payments >= 1


def test_savings_stack_omits_a_year_with_no_statements(parsed):
    from finance.report import months_in_year, savings_stack
    txns, _docs, _notes = parsed
    year = sorted({m.split("-")[0] for m in available_months(txns)})[0]
    frame = savings_stack(txns, year)
    assert list(frame["Series"]) == ["Current"]
    assert frame.iloc[0]["Months"] == len(months_in_year(txns, year))


def test_cumulative_savings_marks_an_incomplete_year_as_ytd(parsed):
    from finance.report import cumulative_savings
    txns, _docs, _notes = parsed
    frame = cumulative_savings(txns)
    assert not frame.empty
    for row in frame.itertuples():
        assert row.Complete == (row.Months == 12)
        assert row.Label == (row.Year if row.Complete else f"{row.Year} YTD")
    # The running total is the sum of everything up to and including that year.
    assert list(frame["Cumulative"]) == pytest.approx(
        list(frame["Saved"].cumsum()), abs=0.02)


def test_expense_cumulative_totals_the_year_by_category(parsed):
    from finance.report import expense_cumulative
    txns, _docs, _notes = parsed
    months = available_months(txns)
    frame = expense_cumulative(txns, months)
    assert not frame.empty
    assert list(frame["Amount"]) == sorted(frame["Amount"], reverse=True)
    assert set(frame["Section"]) <= {"Fixed", "Variable"}
    assert frame["Transactions"].sum() == sum(
        1 for t in txns if t.month in months and t.section in
        ("Fixed Expenses", "Variable Expenses"))


@pytest.mark.parametrize("raw,expected", [
    # A company payment: the name is what sits before the legal suffix, with the
    # bank's routing words and reference numbers stripped off the front.
    ("GIRO SALARY ACME TECHNOLOGIES PTE LTD REF 8821",
     "Acme Technologies Pte Ltd"),
    ("Inward CR - GIRO TO91XKQBVM4HD7P SALA Salary Payment NORTHWIND ASIA PTE. LTD.",
     "Northwind Asia Pte. Ltd"),
    ("INWARD TRF - TT SUMMERFIELD ASSOCIATES SG PTE LTD 1AB704193725D02 20260614",
     "Summerfield Associates Sg Pte Ltd"),
    # "Holdings" and "Group" are parts of a name, not the end of one.
    ("FAST INCOMING NORTHWIND HOLDINGS LIMITED 99213",
     "Northwind Holdings Limited"),
    # No counterparty at all: the description already says what it is.
    ("One Bonus Interest", "One Bonus Interest"),
    ("Interest Credit", "Interest Credit"),
])
def test_income_source_names_strip_bank_routing(raw, expected):
    from finance.report import _source_name
    txn = Transaction(date=date(2026, 5, 1), description=raw[:40],
                      raw_description=raw, amount_sgd=1.0, direction=CREDIT)
    assert _source_name(txn) == expected
