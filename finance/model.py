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
CAT_CPF = "CPF Contribution"
CAT_ADDITIONAL_INCOME = "Additional Income (Interest & Dividends)"

CAT_INSURANCE = "Insurance"
CAT_TELCO = "Telco"
CAT_SUBSCRIPTIONS = "Subscriptions"
CAT_PARENTS = "Allowance to Parents"
CAT_TAX = "Tax"

CAT_TRANSPORT_PUBLIC = "Transport (Bus/MRT)"
CAT_TRANSPORT_CAB = "Transport (Cab)"
CAT_TRANSPORT_CAR = "Transport (Car Maintenance)"
CAT_FOOD = "Food"
CAT_GROCERIES = "Groceries"
CAT_SHOPPING = "Shopping"
CAT_EXPERIENCES = "Experiences/Hobbies"
# The bucket *you* put a genuine one-off in. Deliberately separate from
# CAT_UNCATEGORISED below, which is where the app parks what it could not place
# — folding the two together would make an unread guess look like your decision.
CAT_ADDITIONAL_EXPENSE = "Additional Expenses"
CAT_UNCATEGORISED = "Uncategorised"

CAT_CARD_PAYMENT = "Credit Card Bill Payment"
CAT_INTERNAL_TRANSFER = "Internal Transfer"
# Large transfers we could not identify. Kept out of the income statement and
# reported separately, because guessing wrong on a five-figure transfer distorts
# the whole month. Reassign them in the Transactions tab and they count normally.
CAT_UNCLASSIFIED_TRANSFER = "Unclassified Transfer (needs your call)"

REVENUE_CATEGORIES = [CAT_SALARY, CAT_CPF, CAT_ADDITIONAL_INCOME]
FIXED_CATEGORIES = [CAT_INSURANCE, CAT_TELCO, CAT_SUBSCRIPTIONS, CAT_PARENTS,
                    CAT_TAX]
VARIABLE_CATEGORIES = [
    CAT_TRANSPORT_PUBLIC,
    CAT_TRANSPORT_CAB,
    CAT_TRANSPORT_CAR,
    CAT_FOOD,
    CAT_GROCERIES,
    CAT_SHOPPING,
    CAT_EXPERIENCES,
    CAT_ADDITIONAL_EXPENSE,
    CAT_UNCATEGORISED,
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


def _reindex_sections() -> None:
    CATEGORY_SECTION.clear()
    for _c in REVENUE_CATEGORIES:
        CATEGORY_SECTION[_c] = REVENUE
    for _c in FIXED_CATEGORIES:
        CATEGORY_SECTION[_c] = FIXED
    for _c in VARIABLE_CATEGORIES:
        CATEGORY_SECTION[_c] = VARIABLE
    for _c in EXCLUDED_CATEGORIES:
        CATEGORY_SECTION[_c] = EXCLUDED


_reindex_sections()

# ---------------------------------------------------------------------------
# Categories you add yourself.
#
# The lists above are mutated in place rather than rebuilt, because report.py
# and app.py hold references to them. A category added here has no keywords
# behind it, so the rule engine will never reach it on its own — it becomes
# automatic once you assign a merchant to it and tick "remember my fixes",
# which is the same mechanism that corrects a wrong guess.
# ---------------------------------------------------------------------------
CUSTOM_CATEGORIES: list = []


def register_custom_category(name: str, section: str) -> str:
    """Add a user-defined category to a section. Returns the stored name."""
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("A category needs a name.")
    if section not in (FIXED, VARIABLE):
        raise ValueError(f"Unknown section: {section}")
    if name in CATEGORY_SECTION:
        raise ValueError(f"“{name}” already exists.")

    target = FIXED_CATEGORIES if section == FIXED else VARIABLE_CATEGORIES
    # Ahead of the app's own catch-alls, so your categories read first.
    tail = {CAT_ADDITIONAL_EXPENSE, CAT_UNCATEGORISED}
    insert_at = next((i for i, c in enumerate(target) if c in tail), len(target))
    target.insert(insert_at, name)
    ASSIGNABLE_CATEGORIES.insert(ASSIGNABLE_CATEGORIES.index(EXCLUDED_CATEGORIES[0]),
                                 name)
    CUSTOM_CATEGORIES.append({"name": name, "section": section})
    _reindex_sections()
    return name


def forget_custom_categories() -> None:
    """Drop every user-defined category. Used by the tests and on reload."""
    for entry in list(CUSTOM_CATEGORIES):
        name = entry["name"]
        for target in (FIXED_CATEGORIES, VARIABLE_CATEGORIES, ASSIGNABLE_CATEGORIES):
            if name in target:
                target.remove(name)
    CUSTOM_CATEGORIES.clear()
    _reindex_sections()


# ---------------------------------------------------------------------------
# Renamed and merged categories.
#
# Your saved category fixes in data/category_overrides.json are keyed by
# merchant and hold a category *name*, so a rename would silently strand them.
# Categories that merged map straight across. "Transport" is deliberately
# absent: it split three ways and there is no way to tell from the old name
# whether a merchant was a bus fare, a cab or a workshop, so those overrides are
# dropped and the rule engine — which does draw that distinction — decides again.
# ---------------------------------------------------------------------------
LEGACY_CATEGORY_MAP = {
    "CPF Contribution (20%)": CAT_CPF,
    "Food Delivery": CAT_FOOD,
    "Food & Dining": CAT_FOOD,
    "Recreational & Experiences": CAT_EXPERIENCES,
    "Travel": CAT_EXPERIENCES,
    "Other": CAT_UNCATEGORISED,
}
LEGACY_CATEGORIES_DROPPED = {"Transport"}


def migrate_category(name: str):
    """Current name for a possibly-old category, or None if it should be dropped."""
    if name in LEGACY_CATEGORIES_DROPPED:
        return None
    return LEGACY_CATEGORY_MAP.get(name, name)


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
    category: str = CAT_UNCATEGORISED
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
