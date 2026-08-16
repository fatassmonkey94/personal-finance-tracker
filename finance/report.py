"""Build the two monthly outputs: the transaction compilation and the P&L."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import pandas as pd

from . import cpf
from .model import (
    CAT_ADDITIONAL_INCOME,
    CAT_SALARY,
    CREDIT,
    DEBIT,
    EXCLUDED,
    FIXED,
    FIXED_CATEGORIES,
    REVENUE,
    VARIABLE,
    VARIABLE_CATEGORIES,
    Transaction,
)

MONTH_LABELS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# How to read the salary that lands in the bank account.
BASIS_NET = "net"      # it is take-home, already after the employee's CPF
BASIS_GROSS = "gross"  # it is already the gross figure


def month_label(month_key: str) -> str:
    """'2025-06' -> 'June 2025'."""
    try:
        year, month = month_key.split("-")
        return f"{MONTH_LABELS[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return month_key


def month_short(month_key: str) -> str:
    """'2025-06' -> 'Jun 2025'."""
    try:
        year, month = month_key.split("-")
        return f"{MONTH_LABELS[int(month) - 1][:3]} {year}"
    except (ValueError, IndexError):
        return month_key


def available_months(transactions: List[Transaction]) -> List[str]:
    return sorted({t.month for t in transactions if t.date})


# ---------------------------------------------------------------------------
# Sheet 1: monthly transaction compilation
# ---------------------------------------------------------------------------
COMPILATION_COLUMNS = [
    "Date",
    "Description",
    "Category",
    "Section",
    "Type",
    "Amount (SGD)",
    "Source Account",
    "Original Currency",
    "Original Amount",
    "Raw Statement Text",
    "Flag",
]


def compilation_frame(transactions: List[Transaction], month_key: Optional[str] = None,
                      include_excluded: bool = True) -> pd.DataFrame:
    rows = []
    for txn in sorted(
        transactions,
        key=lambda t: (t.date or date.min, t.source_account, t.description),
    ):
        if month_key and txn.month != month_key:
            continue
        if not include_excluded and txn.section == EXCLUDED:
            continue
        flags = []
        if txn.date_is_inferred:
            flags.append("date inferred")
        if txn.needs_review:
            flags.append("review")
        if txn.section == EXCLUDED:
            flags.append("not in P&L")
        rows.append({
            "Date": txn.date,
            "Description": txn.description,
            "Category": txn.category,
            "Section": txn.section,
            "Type": txn.direction,
            "Amount (SGD)": round(txn.amount_sgd, 2),
            "Source Account": txn.source_account,
            "Original Currency": txn.original_currency,
            "Original Amount": (round(txn.original_amount, 2)
                                if txn.original_amount is not None else None),
            "Raw Statement Text": txn.raw_description,
            "Flag": "; ".join(flags),
        })
    return pd.DataFrame(rows, columns=COMPILATION_COLUMNS)


# ---------------------------------------------------------------------------
# Sheet 2: Revenues / Expenses / Net Income
# ---------------------------------------------------------------------------
@dataclass
class PnLLine:
    label: str
    amount: float
    kind: str = "item"  # "header", "item", "subtotal", "total", "spacer"
    indent: int = 1
    count: int = 0
    # Which transaction categories feed this line — drives the drill-down.
    categories: List[str] = field(default_factory=list)
    expense_side: bool = True
    # For derived lines (CPF) there are no transactions, so explain the maths.
    note: str = ""

    @property
    def drillable(self) -> bool:
        return self.kind in ("item", "subtotal") and bool(self.categories or self.note)


@dataclass
class PnL:
    month_key: str
    lines: List[PnLLine] = field(default_factory=list)
    salary_credited: float = 0.0
    cpf_employee: float = 0.0
    cpf_employer: float = 0.0
    additional_income: float = 0.0
    total_revenue: float = 0.0
    total_fixed: float = 0.0
    total_variable: float = 0.0
    total_expenses: float = 0.0
    net_income: float = 0.0
    excluded_total: float = 0.0
    excluded_count: int = 0
    warnings: List[str] = field(default_factory=list)
    cpf: Optional[cpf.CpfResult] = None
    salary_basis: str = BASIS_NET
    include_employer_cpf: bool = False

    @property
    def label(self) -> str:
        return month_label(self.month_key)

    @property
    def savings_rate(self) -> Optional[float]:
        if not self.total_revenue:
            return None
        return round(self.net_income / self.total_revenue * 100, 1)


def _net(transactions: List[Transaction], category: str, expense: bool) -> float:
    """Net a category. Expenses count debits positive and refunds negative."""
    total = 0.0
    for txn in transactions:
        if txn.category != category:
            continue
        if expense:
            total += txn.amount_sgd if txn.direction == DEBIT else -txn.amount_sgd
        else:
            total += txn.amount_sgd if txn.direction == CREDIT else -txn.amount_sgd
    return round(total, 2)


def _count(transactions: List[Transaction], category: str) -> int:
    return sum(1 for t in transactions if t.category == category)


def build_pnl(transactions: List[Transaction], month_key: str,
              salary_basis: str = BASIS_NET,
              cpf_status: str = cpf.STATUS_CITIZEN,
              cpf_age_band: str = "55 and below",
              include_employer_cpf: bool = False) -> PnL:
    """Assemble the P&L for one month.

    CPF follows CPF Board's published rules (see `finance/cpf.py`): the Ordinary
    Wage ceiling in force that month, the age band, and the low-wage bands.

    salary_basis:
      BASIS_NET   — the bank credit is take-home, already after your CPF. Gross
                    is recovered from it, so Salary + CPF equals true gross pay.
      BASIS_GROSS — the bank credit is already gross; CPF is computed on it and
                    added on top, the literal reading of the original brief.
    """
    month_txns = [t for t in transactions if t.month == month_key]
    when = cpf.month_start(month_key)
    pnl = PnL(month_key=month_key, salary_basis=salary_basis,
              include_employer_cpf=include_employer_cpf)

    # --- Revenue ---------------------------------------------------------
    salary_credited = _net(month_txns, CAT_SALARY, expense=False)
    additional = _net(month_txns, CAT_ADDITIONAL_INCOME, expense=False)

    if salary_basis == BASIS_GROSS:
        result = cpf.contributions(salary_credited, when, cpf_status, cpf_age_band)
    else:
        result = cpf.gross_up(salary_credited, when, cpf_status, cpf_age_band)

    pnl.cpf = result
    pnl.salary_credited = salary_credited
    pnl.cpf_employee = result.employee
    pnl.cpf_employer = result.employer
    pnl.additional_income = additional

    revenue = salary_credited + result.employee + additional
    if include_employer_cpf:
        revenue += result.employer
    pnl.total_revenue = round(revenue, 2)

    basis_note = (
        f"Salary credited S${salary_credited:,.2f} is treated as take-home pay. "
        f"Gross Ordinary Wages work back to S${result.gross_ow:,.2f}."
        if salary_basis == BASIS_NET else
        f"Salary credited S${salary_credited:,.2f} is treated as already gross, so "
        f"CPF is added on top of it."
    )
    # Markdown needs a blank line before a list, and no leading indent, or the
    # bullets collapse into one paragraph.
    cpf_note = "\n".join([
        basis_note,
        "",
        f"CPF rules applied — {result.status}, age {result.age_band}:",
        "",
        f"- Ordinary Wage ceiling that month: S${result.ceiling:,.0f}",
        f"- Wages subject to CPF: S${result.ow_subject_to_cpf:,.2f}"
        f"{' (capped)' if result.capped else ''}",
        f"- Wage band: {result.band}",
        f"- Employee share: S${result.employee:,.2f}",
        f"- Employer share: S${result.employer:,.2f}",
        f"- Total into CPF: S${result.total:,.2f}",
    ])

    pnl.lines.append(PnLLine("REVENUES", 0.0, "header", 0))
    pnl.lines.append(PnLLine(
        "Salary credited to bank" if salary_basis == BASIS_NET else "Gross salary",
        salary_credited, "item", 1, _count(month_txns, CAT_SALARY),
        categories=[CAT_SALARY], expense_side=False,
    ))
    pnl.lines.append(PnLLine(
        f"CPF contribution — employee share (capped at S${result.ceiling:,.0f} OW)",
        result.employee, "item", 1, 0, note=cpf_note,
    ))
    if include_employer_cpf:
        pnl.lines.append(PnLLine(
            "CPF contribution — employer share", result.employer, "item", 1, 0,
            note=cpf_note,
        ))
    pnl.lines.append(PnLLine(
        "Additional income (interest, dividends, other)", additional, "item", 1,
        _count(month_txns, CAT_ADDITIONAL_INCOME),
        categories=[CAT_ADDITIONAL_INCOME], expense_side=False,
    ))
    pnl.lines.append(PnLLine(
        "Total Revenues", pnl.total_revenue, "subtotal", 0,
        categories=[CAT_SALARY, CAT_ADDITIONAL_INCOME], expense_side=False,
    ))

    # --- Fixed expenses --------------------------------------------------
    pnl.lines.append(PnLLine("", 0.0, "spacer", 0))
    pnl.lines.append(PnLLine("EXPENSES", 0.0, "header", 0))
    pnl.lines.append(PnLLine("Fixed Expenses", 0.0, "header", 1))
    fixed_total = 0.0
    for category in FIXED_CATEGORIES:
        amount = _net(month_txns, category, expense=True)
        fixed_total += amount
        pnl.lines.append(PnLLine(category, amount, "item", 2,
                                 _count(month_txns, category),
                                 categories=[category]))
    pnl.total_fixed = round(fixed_total, 2)
    pnl.lines.append(PnLLine("Total Fixed Expenses", pnl.total_fixed, "subtotal", 1,
                             categories=list(FIXED_CATEGORIES)))

    # --- Variable expenses -----------------------------------------------
    pnl.lines.append(PnLLine("", 0.0, "spacer", 0))
    pnl.lines.append(PnLLine("Variable Expenses", 0.0, "header", 1))
    variable_total = 0.0
    for category in VARIABLE_CATEGORIES:
        amount = _net(month_txns, category, expense=True)
        variable_total += amount
        pnl.lines.append(PnLLine(category, amount, "item", 2,
                                 _count(month_txns, category),
                                 categories=[category]))
    pnl.total_variable = round(variable_total, 2)
    pnl.lines.append(PnLLine("Total Variable Expenses", pnl.total_variable, "subtotal", 1,
                             categories=list(VARIABLE_CATEGORIES)))

    pnl.total_expenses = round(pnl.total_fixed + pnl.total_variable, 2)
    pnl.lines.append(PnLLine("", 0.0, "spacer", 0))
    pnl.lines.append(PnLLine(
        "Total Expenses", pnl.total_expenses, "subtotal", 0,
        categories=list(FIXED_CATEGORIES) + list(VARIABLE_CATEGORIES),
    ))

    # --- Net income ------------------------------------------------------
    pnl.net_income = round(pnl.total_revenue - pnl.total_expenses, 2)
    pnl.lines.append(PnLLine("", 0.0, "spacer", 0))
    pnl.lines.append(PnLLine("NET INCOME", pnl.net_income, "total", 0))

    # --- Housekeeping notes ----------------------------------------------
    excluded = [t for t in month_txns if t.section == EXCLUDED]
    pnl.excluded_total = round(sum(t.amount_sgd for t in excluded), 2)
    pnl.excluded_count = len(excluded)

    if salary_credited == 0:
        pnl.warnings.append(
            "No salary transaction was identified this month, so gross pay and the "
            "CPF line are both zero. Tag the salary credit in the Transactions tab "
            "to fix the revenue figures."
        )
    elif result.capped:
        pnl.warnings.append(
            f"Salary exceeds the S${result.ceiling:,.0f} Ordinary Wage ceiling, so CPF "
            f"is charged on S${result.ow_subject_to_cpf:,.0f} of it — the employee share "
            f"is S${result.employee:,.2f}, not {result.employee / max(salary_credited, 1):.0%} "
            f"of the full salary."
        )
    unreviewed = sum(1 for t in month_txns if t.needs_review)
    if unreviewed:
        pnl.warnings.append(
            f"{unreviewed} transaction(s) need a look — see the Review tab. "
            f"They are already included in the totals above."
        )
    inferred = sum(1 for t in month_txns if t.date_is_inferred)
    if inferred:
        pnl.warnings.append(
            f"{inferred} transaction(s) came from a PDF with no per-line date and were "
            f"dated to the end of the statement period."
        )
    return pnl


def pnl_frame(pnl: PnL) -> pd.DataFrame:
    """Numeric P&L, for programmatic use and the Excel writer."""
    blank = float("nan")
    rows = []
    for line in pnl.lines:
        if line.kind == "spacer":
            rows.append({"Line Item": "", "Amount (SGD)": blank, "Txns": blank})
            continue
        indent = "    " * line.indent
        amount = blank if line.kind == "header" else round(line.amount, 2)
        rows.append({
            "Line Item": indent + line.label,
            "Amount (SGD)": amount,
            "Txns": float(line.count) if line.count else blank,
        })
    frame = pd.DataFrame(rows, columns=["Line Item", "Amount (SGD)", "Txns"])
    frame["Amount (SGD)"] = pd.to_numeric(frame["Amount (SGD)"], errors="coerce")
    frame["Txns"] = pd.to_numeric(frame["Txns"], errors="coerce")
    return frame


def pnl_display_frame(pnl: PnL) -> pd.DataFrame:
    """Presentation copy: amounts pre-formatted as text.

    A numeric column has to choose between showing blanks on the section-header
    rows and showing thousands separators — Streamlit renders a NaN under a
    printf format as the literal "None". Formatting here gives both.
    """
    rows = []
    for line in pnl.lines:
        if line.kind == "spacer":
            rows.append({"Line Item": "", "Amount (SGD)": "", "Txns": ""})
            continue
        indent = "    " * line.indent
        amount = "" if line.kind == "header" else f"{line.amount:,.2f}"
        rows.append({
            "Line Item": indent + line.label,
            "Amount (SGD)": amount,
            "Txns": str(line.count) if line.count else "",
        })
    return pd.DataFrame(rows, columns=["Line Item", "Amount (SGD)", "Txns"])


def line_transactions(transactions: List[Transaction], month_key: str,
                      line: PnLLine) -> List[Transaction]:
    """The transactions behind one P&L line, for the drill-down."""
    if not line.categories:
        return []
    wanted = set(line.categories)
    rows = [t for t in transactions if t.month == month_key and t.category in wanted]
    return sorted(rows, key=lambda t: (t.date or date.min, -t.amount_sgd))


def category_breakdown(transactions: List[Transaction], month_key: str) -> pd.DataFrame:
    """Per-category totals for the month, for charts and sanity checks."""
    rows = []
    month_txns = [t for t in transactions if t.month == month_key]
    for section, categories in (
        (REVENUE, [CAT_SALARY, CAT_ADDITIONAL_INCOME]),
        (FIXED, FIXED_CATEGORIES),
        (VARIABLE, VARIABLE_CATEGORIES),
    ):
        for category in categories:
            amount = _net(month_txns, category, expense=(section != REVENUE))
            count = _count(month_txns, category)
            if count == 0 and amount == 0:
                continue
            rows.append({
                "Section": section,
                "Category": category,
                "Amount (SGD)": amount,
                "Transactions": count,
            })
    return pd.DataFrame(rows, columns=["Section", "Category", "Amount (SGD)", "Transactions"])


def review_frame(transactions: List[Transaction], month_key: Optional[str] = None) -> pd.DataFrame:
    rows = []
    for txn in sorted(transactions, key=lambda t: (t.date or date.min)):
        if month_key and txn.month != month_key:
            continue
        if not txn.needs_review:
            continue
        rows.append({
            "Date": txn.date,
            "Description": txn.description,
            "Category": txn.category,
            "Type": txn.direction,
            "Amount (SGD)": round(txn.amount_sgd, 2),
            "Why flagged": txn.review_note or "Low-confidence match",
            "Source Account": txn.source_account,
            "Raw Statement Text": txn.raw_description,
        })
    return pd.DataFrame(rows, columns=[
        "Date", "Description", "Category", "Type", "Amount (SGD)",
        "Why flagged", "Source Account", "Raw Statement Text",
    ])


def category_by_month(transactions: List[Transaction],
                      months: Optional[List[str]] = None,
                      sections: Optional[List[str]] = None) -> pd.DataFrame:
    """Long-form category x month totals — the shape a dot plot wants.

    One row per (category, month) so each category can be drawn as a series of
    dots joined by a line, showing how that category moved through the year.
    """
    months = months or available_months(transactions)
    wanted_sections = sections or [FIXED, VARIABLE]
    rows = []
    for month_key in months:
        month_txns = [t for t in transactions if t.month == month_key]
        for section, categories in ((FIXED, FIXED_CATEGORIES),
                                    (VARIABLE, VARIABLE_CATEGORIES),
                                    (REVENUE, [CAT_SALARY, CAT_ADDITIONAL_INCOME])):
            if section not in wanted_sections:
                continue
            for category in categories:
                rows.append({
                    "Category": category,
                    "Section": section,
                    "Month": month_key,
                    "MonthLabel": month_short(month_key),
                    "Amount": _net(month_txns, category,
                                   expense=(section != REVENUE)),
                    "Transactions": _count(month_txns, category),
                })
    frame = pd.DataFrame(rows, columns=[
        "Category", "Section", "Month", "MonthLabel", "Amount", "Transactions",
    ])
    if frame.empty:
        return frame
    # Drop categories with no activity at all across the whole period, so the
    # plot is not padded out with empty rows.
    active = frame.groupby("Category")["Amount"].transform(
        lambda s: s.abs().sum() > 0
    )
    return frame[active].reset_index(drop=True)


@dataclass
class AnnualSummary:
    """Totals across every month loaded."""

    months: List[str] = field(default_factory=list)
    total_revenue: float = 0.0
    total_fixed: float = 0.0
    total_variable: float = 0.0
    total_expenses: float = 0.0
    net_income: float = 0.0
    cpf_employee: float = 0.0
    cpf_employer: float = 0.0
    excluded_total: float = 0.0
    review_count: int = 0
    transaction_count: int = 0

    @property
    def savings_rate(self) -> Optional[float]:
        if not self.total_revenue:
            return None
        return round(self.net_income / self.total_revenue * 100, 1)

    @property
    def month_count(self) -> int:
        return len(self.months)

    @property
    def avg_monthly_expenses(self) -> float:
        return round(self.total_expenses / self.month_count, 2) if self.months else 0.0

    @property
    def avg_monthly_net(self) -> float:
        return round(self.net_income / self.month_count, 2) if self.months else 0.0

    @property
    def span(self) -> str:
        if not self.months:
            return ""
        if len(self.months) == 1:
            return month_label(self.months[0])
        return f"{month_short(self.months[0])} – {month_short(self.months[-1])}"


def annual_summary(transactions: List[Transaction], salary_basis: str = BASIS_NET,
                   cpf_status: str = cpf.STATUS_CITIZEN,
                   cpf_age_band: str = "55 and below",
                   include_employer_cpf: bool = False) -> AnnualSummary:
    months = available_months(transactions)
    summary = AnnualSummary(months=months)
    for month_key in months:
        pnl = build_pnl(transactions, month_key, salary_basis, cpf_status,
                        cpf_age_band, include_employer_cpf)
        summary.total_revenue += pnl.total_revenue
        summary.total_fixed += pnl.total_fixed
        summary.total_variable += pnl.total_variable
        summary.total_expenses += pnl.total_expenses
        summary.net_income += pnl.net_income
        summary.cpf_employee += pnl.cpf_employee
        summary.cpf_employer += pnl.cpf_employer
        summary.excluded_total += pnl.excluded_total
    for field_name in ("total_revenue", "total_fixed", "total_variable",
                       "total_expenses", "net_income", "cpf_employee",
                       "cpf_employer", "excluded_total"):
        setattr(summary, field_name, round(getattr(summary, field_name), 2))
    summary.review_count = sum(1 for t in transactions if t.needs_review)
    summary.transaction_count = len(transactions)
    return summary


def monthly_trend(transactions: List[Transaction], salary_basis: str = BASIS_NET,
                  cpf_status: str = cpf.STATUS_CITIZEN,
                  cpf_age_band: str = "55 and below",
                  include_employer_cpf: bool = False) -> pd.DataFrame:
    rows = []
    for month_key in available_months(transactions):
        pnl = build_pnl(transactions, month_key, salary_basis, cpf_status,
                        cpf_age_band, include_employer_cpf)
        rows.append({
            "Month": pnl.label,
            "Total Revenues": pnl.total_revenue,
            "Fixed Expenses": pnl.total_fixed,
            "Variable Expenses": pnl.total_variable,
            "Total Expenses": pnl.total_expenses,
            "Net Income": pnl.net_income,
            "Savings Rate": pnl.savings_rate,
        })
    # Name the columns even when there are no rows, so callers can filter on
    # them without a KeyError.
    return pd.DataFrame(rows, columns=[
        "Month", "Total Revenues", "Fixed Expenses", "Variable Expenses",
        "Total Expenses", "Net Income", "Savings Rate",
    ])
