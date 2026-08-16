"""Regression tests for statement quirks found in real UOB and Citibank exports.

Each case here is a bug that real statements actually triggered. The fixtures
reproduce the *structure* of those statements. Every account number, payee and
reference here is invented — the fixtures must never carry real card numbers or
names, because this file is committed.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finance.ingest import ingest_files
from finance.model import (
    CAT_CARD_PAYMENT,
    CAT_DINING,
    CAT_GROCERIES,
    CAT_INSURANCE,
    CAT_INTERNAL_TRANSFER,
    CAT_TRANSPORT,
    CAT_TRAVEL,
    CAT_UNCLASSIFIED_TRANSFER,
    CREDIT,
    DEBIT,
    EXCLUDED,
)
from finance.parse_pdf import parse_pdf
from finance.parse_tabular import parse_tabular
from finance.rules import Categoriser
from make_samples import write_pdf


# ---------------------------------------------------------------------------
# UOB card export: Foreign amount column sits LEFT of the local one
# ---------------------------------------------------------------------------
UOB_CARD_CSV = (
    "United Overseas Bank Limited,,,,,,\n"
    ",,,,,,\n"
    "Account Number:,4000000000001111,SGD,,,,\n"
    "Account Type:,LADY'S SOLITAIRE CARD,,,,,\n"
    "Statement Date:,02 Jun 2026,,,,,\n"
    "Statement Balance:,652.90,SGD,,,,\n"
    ",,,,,,\n"
    "Transaction Date,Posting Date,Description,Foreign Currency Type,"
    "Transaction Amount(Foreign),Local Currency Type,Transaction Amount(Local)\n"
    ",,Previous Balance,,,,940.24\n"
    "11 May 2026,12 May 2026,KONJIKI LONDON GB,GBP,88.42,SGD,158.10\n"
    "22 May 2026,25 May 2026,THE PUBLIC IZAKAYA,,,SGD,26.74\n"
    "19 May 2026,19 May 2026,PAYMT THRU E-BANK/HOMEB/CY,,,SGD,-940.24\n"
)


@pytest.fixture(scope="module")
def uob_card():
    return parse_tabular(UOB_CARD_CSV.encode(), "uob card may.csv")


def test_local_amount_wins_over_foreign_amount(uob_card):
    """The SGD figure must come from Transaction Amount(Local).

    Regression: a plain search for "amount" matched Transaction Amount(Foreign)
    first, recording GBP 88.42 as if it were S$88.42.
    """
    konjiki = next(t for t in uob_card.transactions if "KONJIKI" in t.raw_description)
    assert konjiki.amount_sgd == 158.10
    assert konjiki.original_currency == "GBP"
    assert konjiki.original_amount == 88.42


def test_account_label_read_from_preamble(uob_card):
    """Two cards from one bank must not collapse to the same label."""
    assert uob_card.account == "Lady's Solitaire Card ••1111"


def test_paymt_thru_ebank_is_a_card_bill_payment(uob_card):
    payment = next(t for t in uob_card.transactions if "PAYMT" in t.raw_description)
    assert payment.direction == CREDIT  # negative on a card = money in
    engine = Categoriser()
    assert engine.categorise(payment.raw_description, payment.direction)[0] == CAT_CARD_PAYMENT


def test_previous_balance_row_is_not_a_transaction(uob_card):
    assert not [t for t in uob_card.transactions if "Previous Balance" in t.raw_description]


def test_currency_type_column_is_not_used_as_description(uob_card):
    """'Local Currency Type' matches the 'type' description synonym."""
    for txn in uob_card.transactions:
        assert "SGD" not in txn.raw_description.split()


# ---------------------------------------------------------------------------
# UOB account export: Withdrawal/Deposit pair, zeros, embedded newlines
# ---------------------------------------------------------------------------
UOB_ACCOUNT_CSV = (
    "United Overseas Bank Limited,,,,\n"
    "Account Number:,1234567890,SGD,,\n"
    "Account Type:,One Account,,,\n"
    "Statement Period:,01 May 2026 To 31 May 2026,,,\n"
    "Transaction Date,Transaction Description,Withdrawal,Deposit,Available Balance\n"
    '30 May 2026,Interest Credit,0,2,55598.32\n'
    '25 May 2026,"Inward CR - GIRO REF00005 SALA Salary Payment A PAYROLL CO PTE. LTD.",0,14466.69,54088.43\n'
    '19 May 2026,"Bill Payment Bill payment mBK-Citi CC 4000000000002222",166.45,0,40000.00\n'
    '19 May 2026,"Bill Payment Card payment mBK-UOB Cards 4000000000001111",940.24,0,39000.00\n'
    '18 May 2026,"NETS Debit-Consumer A SHOP00000001 xxxx",4.50,0,43340.40\n'
    '18 May 2026,"NETS Debit-Consumer A SHOP00000002 xxxx",4.50,0,43344.90\n'
    '29 May 2026,"PAYNOW-FAST\nOTHR REF0000001 INTERACTIVE BR SG-",24000,0,55629.32\n'
    '28 May 2026,"Inward Credit-FAST REF0000002 OTHR Other OKX SG PTE. LTD.",0,26214.66,80629.32\n'
    '02 May 2026,"PAYNOW-FAST\nOTHR REF0000003 PIB000001 YOU TECHNOLOGIES GR",300,0,50000.00\n'
    '21 May 2026,"PAYNOW-FAST\nOTHR REF0000004 PIB000002 A Payee",1000,0,49000.00\n'
    '08 May 2026,"PAYNOW-FAST\nOTHR PAYNOW Prudential Assurance",0,39.78,49039.78\n'
)


@pytest.fixture(scope="module")
def uob_account():
    doc = parse_tabular(UOB_ACCOUNT_CSV.encode(), "uob one acc may.csv")
    from finance.ingest import enrich
    enrich(doc.transactions, Categoriser())
    return doc


def _by(doc, needle):
    return next(t for t in doc.transactions if needle in t.raw_description.upper())


def test_zero_in_the_unused_column_is_not_a_transaction(uob_account):
    interest = _by(uob_account, "INTEREST CREDIT")
    assert interest.direction == CREDIT
    assert interest.amount_sgd == 2.00


def test_embedded_newlines_are_flattened(uob_account):
    for txn in uob_account.transactions:
        assert "\n" not in txn.raw_description


def test_giro_salary_is_found(uob_account):
    salary = _by(uob_account, "SALARY PAYMENT")
    assert salary.category == "Salary"
    assert salary.amount_sgd == 14466.69


def test_two_identical_nets_charges_are_both_kept():
    """Regression: the dedupe key truncated the description, so two genuine
    same-day same-amount NETS charges collapsed into one and money vanished."""
    txns, _docs, notes = ingest_files([("uob.csv", UOB_ACCOUNT_CSV.encode())])
    nets = [t for t in txns if "NETS Debit" in t.raw_description]
    assert len(nets) == 2
    assert sum(t.amount_sgd for t in nets) == 9.00
    assert not any("Dropped duplicate" in n for n in notes)


def test_same_file_uploaded_twice_is_deduplicated():
    once, _d, _n = ingest_files([("uob.csv", UOB_ACCOUNT_CSV.encode())])
    twice, _d, notes = ingest_files([("uob.csv", UOB_ACCOUNT_CSV.encode()),
                                     ("uob.csv", UOB_ACCOUNT_CSV.encode())])
    assert len(twice) == len(once)
    assert any("Dropped duplicate" in n for n in notes)


def test_bill_payment_to_another_issuer_is_excluded(uob_account):
    """'Bill payment mBK-Citi CC' is a Citi card bill, not a restaurant."""
    citi = _by(uob_account, "MBK-CITI CC")
    assert citi.category == CAT_CARD_PAYMENT
    assert citi.section == EXCLUDED


def test_brokerage_transfer_is_not_an_expense(uob_account):
    """A truncated 'INTERACTIVE BR SG-' payee is still Interactive Brokers."""
    ibkr = _by(uob_account, "INTERACTIVE BR")
    assert ibkr.category == CAT_INTERNAL_TRANSFER
    assert ibkr.section == EXCLUDED


def test_crypto_exchange_credit_is_not_income(uob_account):
    """A withdrawal back from an exchange is your own capital returning."""
    okx = _by(uob_account, "OKX")
    assert okx.category == CAT_INTERNAL_TRANSFER
    assert okx.section == EXCLUDED


def test_youtrip_legal_name_is_travel(uob_account):
    """Top-ups show YouTrip's corporate name, truncated by the export, not the
    brand — so the rule has to match the "YOU TECHNOLOG" stem."""
    top_up = _by(uob_account, "YOU TECHNOLOGIES GR")
    assert top_up.category == CAT_TRAVEL


@pytest.mark.parametrize("payee", [
    "YOU TECHNOLOGIES GR", "YOU TECHNOLOGIES GROUP PTE LTD",
    "YOU TECHNOLOGY PTE LTD", "YOUTRIP", "YouTrip Top Up",
])
def test_all_youtrip_spellings_are_travel(payee):
    assert Categoriser().categorise(f"PAYNOW-FAST OTHR {payee}", DEBIT)[0] == CAT_TRAVEL


def test_large_unidentified_transfer_is_held_back(uob_account):
    """A four-figure PayNow to a person is not a restaurant bill."""
    big = _by(uob_account, "A PAYEE")
    assert big.category == CAT_UNCLASSIFIED_TRANSFER
    assert big.section == EXCLUDED
    assert big.needs_review


def test_threshold_of_zero_restores_literal_behaviour():
    txns, _docs, _notes = ingest_files(
        [("uob.csv", UOB_ACCOUNT_CSV.encode())], transfer_review_threshold=0,
    )
    big = next(t for t in txns if "A Payee" in t.raw_description)
    assert big.category == CAT_DINING


def test_transfer_naming_a_merchant_uses_that_merchant(uob_account):
    """A PayNow credit from Prudential is an insurance refund, not income."""
    refund = _by(uob_account, "PRUDENTIAL")
    assert refund.category == CAT_INSURANCE
    assert refund.direction == CREDIT


# ---------------------------------------------------------------------------
# Merchant name vs location name
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    # A supermarket at a station is groceries, not a train fare.
    ("GIANT-SIMEI MRT Singapore SG", CAT_GROCERIES),
    ("COLD STORAGE JURONG EAST MRT", CAT_GROCERIES),
    ("STARBUCKS BUGIS MRT", CAT_DINING),
    # ...but a genuine fare still lands in transport.
    ("BUS/MRT 862119911", CAT_TRANSPORT),
    ("BUS/MRT DONATION", CAT_TRANSPORT),
])
def test_named_merchant_beats_location_word(raw, expected):
    assert Categoriser().categorise(raw, DEBIT)[0] == expected


@pytest.mark.parametrize("raw", [
    "FUNKY NOODLES LTD LONDON GB",
    "MARUGAME UDON LONDON GB",
    "BUSAN POCHA",
    "FORTUNE FRIED CHICKEN LONDON GB",
    "OLD CHANG KEE",
    "FUN TOAST @ ONE SHENTON",
    "MAY'S COFFE",
])
def test_generic_food_words_reach_dining(raw):
    assert Categoriser().categorise(raw, DEBIT)[0] == CAT_DINING


# ---------------------------------------------------------------------------
# Citibank PDF: payment slips, masked cards, spelled-out currencies
# ---------------------------------------------------------------------------
def _pad(left, right, width=96):
    return left + " " * max(2, width - len(left) - len(right)) + right


CITI_LINES = [
    "Citibank Singapore Ltd",
    "YOUR BILL SUMMARY",
    "Statement Date May 05, 2026",
    "Credit Limit $99,700.00",
    "Current Balance $166.45",
    "#04-76 Total Minimum Payment $50.00",
    "Payment Due Date May 30, 2026",
    "CITI REWARDS WORLD MASTERCARD 4000 0000 0000 2222",
    "PAYMENT SLIP",
    "CREDIT CARD TYPE ACCOUNT NUMBER CURRENT BALANCE $ MINIMUM PAYMENT $",
    "1 CITIREWARDS 4000000000002222 166.45 50.00",
    "TOTAL FOR THE CARD(S) ABOVE 166.45 50.00",
    "DATE DESCRIPTION AMOUNT (SGD)",
    "BALANCE PREVIOUS STATEMENT 982.24",
    _pad("21 APR MONEYSEND A CARDHOLDER SINGAPORE SG", "(982.24)"),
    _pad("04 APR fp*Food Panda Singapore SG", "20.19"),
    "XXXX-XXXX-XXXX-0000",
    _pad("08 APR Spotify P413BA4822 Stockholm SE", "20.98"),
    _pad("10 APR CCY CONVERSION FEE SGD 20.98", "0.20"),
    _pad("13 APR ANNUAL MEMBER FEE REV", "(180.00)"),
    _pad("19 APR WWW.JETPACGLOBAL.COM SINGAPORE SG", "92.06"),
    "FOREIGN AMOUNT U.S. DOLLAR 69.99",
    "XXXX-XXXX-XXXX-0000",
    _pad("01 MAY EzypaySGD*Anytime Fitn Singapore SG", "80.75"),
    "SUB-TOTAL: 166.45",
    "GRAND TOTAL 166.45",
    "982.24 982.24 362.42 0.00 -195.97 166.45",
    "Page 1 of 8",
]


@pytest.fixture(scope="module")
def citi(tmp_path_factory):
    path = tmp_path_factory.mktemp("citi") / "citi.pdf"
    write_pdf(str(path), [CITI_LINES])
    doc = parse_pdf(path.read_bytes(), "citi rewards may.pdf")
    from finance.ingest import enrich
    enrich(doc.transactions, Categoriser())
    return doc


def test_payment_slip_row_is_not_a_transaction(citi):
    """Regression: '1 CITIREWARDS <16-digit acct> 166.45 50.00' became a
    phantom S$50.00 debit."""
    assert not [t for t in citi.transactions if "CITIREWARDS" in t.raw_description.upper()]
    assert not [t for t in citi.transactions if t.amount_sgd == 50.00]


def test_minimum_payment_sharing_a_line_with_an_address_is_ignored(citi):
    assert not [t for t in citi.transactions
                if "MINIMUM" in t.raw_description.upper()]


def test_masked_card_number_is_not_appended_to_a_description(citi):
    for txn in citi.transactions:
        assert "XXXX" not in txn.raw_description.upper()


def test_spelled_out_foreign_currency_is_captured_not_double_counted(citi):
    """'FOREIGN AMOUNT U.S. DOLLAR 69.99' is FX detail, not a new charge."""
    jetpac = next(t for t in citi.transactions if "JETPAC" in t.raw_description.upper())
    assert jetpac.amount_sgd == 92.06
    assert jetpac.original_currency == "USD"
    assert jetpac.original_amount == 69.99
    assert not [t for t in citi.transactions if t.amount_sgd == 69.99]


def test_parenthesised_amount_is_a_credit(citi):
    moneysend = next(t for t in citi.transactions if "MONEYSEND" in t.raw_description.upper())
    assert moneysend.direction == CREDIT
    assert moneysend.amount_sgd == 982.24
    assert moneysend.category == CAT_CARD_PAYMENT


def test_fee_reversal_is_a_credit(citi):
    rev = next(t for t in citi.transactions if "MEMBER FEE REV" in t.raw_description.upper())
    assert rev.direction == CREDIT
    assert rev.amount_sgd == 180.00


def test_currency_conversion_fee_is_kept(citi):
    fee = next(t for t in citi.transactions if "CONVERSION FEE" in t.raw_description.upper())
    assert fee.amount_sgd == 0.20


def test_truncated_gym_name_still_matches(citi):
    gym = next(t for t in citi.transactions if "ANYTIME" in t.raw_description.upper())
    assert gym.category == "Subscriptions"


def test_all_amount_only_summary_rows_are_dropped(citi):
    """'982.24 982.24 362.42 0.00 -195.97 166.45' has no letters."""
    for txn in citi.transactions:
        assert any(ch.isalpha() for ch in txn.raw_description)


def test_citi_totals_reconcile(citi):
    """The statement's own SUB-TOTAL is 166.45; purchases 362.42, credits 195.97
    plus the 982.24 payment. Check we captured the purchase side exactly."""
    debits = sum(t.amount_sgd for t in citi.transactions if t.direction == DEBIT)
    assert debits == pytest.approx(214.18, abs=0.01)  # the lines present in this fixture
    credits = sum(t.amount_sgd for t in citi.transactions if t.direction == CREDIT)
    assert credits == pytest.approx(1162.24, abs=0.01)  # 982.24 payment + 180.00 reversal


def test_dates_land_in_the_statement_period(citi):
    for txn in citi.transactions:
        assert date(2026, 4, 1) <= txn.date <= date(2026, 5, 5), txn


# ---------------------------------------------------------------------------
# Legacy .xls support
# ---------------------------------------------------------------------------
def test_legacy_xls_is_readable(tmp_path):
    """UOB exports BIFF .xls, which pandas can only read with xlrd installed."""
    pytest.importorskip("xlrd")
    import pandas as pd
    frame = pd.DataFrame([
        ["Account Type:", "One Account", None, None, None],
        ["Transaction Date", "Transaction Description", "Withdrawal", "Deposit",
         "Available Balance"],
        ["01 May 2026", "STARBUCKS ORCHARD", 7.60, 0, 100.0],
    ])
    path = tmp_path / "legacy.xlsx"  # xlwt cannot write .xls on modern pandas
    frame.to_excel(path, index=False, header=False)
    doc = parse_tabular(path.read_bytes(), "legacy.xls".replace(".xls", ".xlsx"))
    assert len(doc.transactions) == 1
    assert doc.transactions[0].amount_sgd == 7.60
