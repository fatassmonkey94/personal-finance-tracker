"""Core data model for the personal finance tracker."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

# ---------------------------------------------------------------------------
# Statement sections
# ---------------------------------------------------------------------------
REVENUE = "Revenue"
FIXED = "Fixed Expenses"
VARIABLE = "Variable Expenses"
EXCLUDED = "Excluded"

# ---------------------------------------------------------------------------
# Categories, in the display order the P&L uses.
# ---------------------------------------------------------------------------
CAT_SALARY = "Salary"
CAT_CPF = "CPF Contribution (20%)"
CAT_ADDITIONAL_INCOME = "Additional Income (Interest & Dividends)"

CAT_INSURANCE = "Insurance"
CAT_TELCO = "Telco"
CAT_SUBSCRIPTIONS = "Subscriptions"
CAT_PARENTS = "Allowance to Parents"

CAT_TRANSPORT = "Transport"
CAT_FOOD_DELIVERY = "Food Delivery"
CAT_DINING = "Food & Dining"
CAT_GROCERIES = "Groceries"
CAT_SHOPPING = "Shopping"
CAT_RECREATION = "Recreational & Experiences"
CAT_TRAVEL = "Travel"
CAT_OTHER = "Other"

CAT_CARD_PAYMENT = "Credit Card Bill Payment"
CAT_INTERNAL_TRANSFER = "Internal Transfer"
# Large transfers we could not identify. Kept out of the income statement and
# reported separately, because guessing wrong on a five-figure transfer distorts
# the whole month. Reassign them in the Transactions tab and they count normally.
CAT_UNCLASSIFIED_TRANSFER = "Unclassified Transfer (needs your call)"

REVENUE_CATEGORIES = [CAT_SALARY, CAT_CPF, CAT_ADDITIONAL_INCOME]
FIXED_CATEGORIES = [CAT_INSURANCE, CAT_TELCO, CAT_SUBSCRIPTIONS, CAT_PARENTS]
VARIABLE_CATEGORIES = [
    CAT_TRANSPORT,
    CAT_FOOD_DELIVERY,
    CAT_DINING,
    CAT_GROCERIES,
    CAT_SHOPPING,
    CAT_RECREATION,
    CAT_TRAVEL,
    CAT_OTHER,
]
EXCLUDED_CATEGORIES = [
    CAT_CARD_PAYMENT, CAT_INTERNAL_TRANSFER, CAT_UNCLASSIFIED_TRANSFER,
]

# Categories a transaction can actually be tagged with (CPF is derived, not parsed).
ASSIGNABLE_CATEGORIES = (
    [CAT_SALARY, CAT_ADDITIONAL_INCOME]
    + FIXED_CATEGORIES
    + VARIABLE_CATEGORIES
    + EXCLUDED_CATEGORIES
)

CATEGORY_SECTION = {}
for _c in REVENUE_CATEGORIES:
    CATEGORY_SECTION[_c] = REVENUE
for _c in FIXED_CATEGORIES:
    CATEGORY_SECTION[_c] = FIXED
for _c in VARIABLE_CATEGORIES:
    CATEGORY_SECTION[_c] = VARIABLE
for _c in EXCLUDED_CATEGORIES:
    CATEGORY_SECTION[_c] = EXCLUDED


def section_for(category: str) -> str:
    return CATEGORY_SECTION.get(category, VARIABLE)


DEBIT = "Debit"
CREDIT = "Credit"


@dataclass
class Transaction:
    """One line on a statement, normalised to SGD."""

    date: Optional[date]
    description: str  # short summary, <= 10 words
    raw_description: str  # what the statement actually said
    amount_sgd: float  # always positive; `direction` carries the sign
    direction: str  # DEBIT (money out) or CREDIT (money in)
    category: str = CAT_OTHER
    source_account: str = "Unknown"
    source_file: str = ""
    # Which uploaded document this came from. Two uploads of the same file are
    # two documents even though they share a filename, which is what lets
    # dedupe tell "same statement twice" apart from "same purchase twice".
    source_doc: int = 0
    original_currency: str = "SGD"
    original_amount: Optional[float] = None
    date_is_inferred: bool = False
    needs_review: bool = False
    review_note: str = ""
    rule_matched: str = ""

    @property
    def section(self) -> str:
        return section_for(self.category)

    @property
    def month(self) -> str:
        """YYYY-MM bucket used to group into monthly sheets."""
        return self.date.strftime("%Y-%m") if self.date else "Unknown"

    @property
    def signed_amount(self) -> float:
        """Positive for money in, negative for money out."""
        return self.amount_sgd if self.direction == CREDIT else -self.amount_sgd

    def dedupe_key(self):
        # Use the *whole* description. Two NETS charges to the same shop on the
        # same day for the same amount differ only in their trailing reference
        # number, and truncating here would delete a real transaction.
        desc = re.sub(r"[^A-Z0-9]", "", self.raw_description.upper())
        return (
            self.date,
            round(self.amount_sgd, 2),
            self.direction,
            desc,
            self.source_account,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["section"] = self.section
        d["month"] = self.month
        return d


@dataclass
class ParsedDocument:
    """Result of parsing one uploaded file."""

    filename: str
    account: str
    doc_type: str  # "tabular" or "pdf"
    transactions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    statement_month: Optional[str] = None  # YYYY-MM if detected
    skipped_lines: list = field(default_factory=list)
