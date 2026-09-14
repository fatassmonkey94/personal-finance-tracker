"""Build the two monthly outputs: the transaction compilation and the P&L."""
from __future__ import annotations

import re
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


# ---------------------------------------------------------------------------
# Dashboard data: the year/month tree, the three pies, and the YTD series
# ---------------------------------------------------------------------------
def years_with_months(transactions: List[Transaction]) -> "dict":
    """{'2026': ['2026-04', '2026-05', '2026-06'], …}, newest year first."""
    tree: "dict" = {}
    for month_key in available_months(transactions):
        tree.setdefault(month_key.split("-")[0], []).append(month_key)
    return dict(sorted(tree.items(), reverse=True))


def months_in_year(transactions: List[Transaction], year: str) -> List[str]:
    return [m for m in available_months(transactions) if m.startswith(f"{year}-")]


def income_breakdown(transactions: List[Transaction], months: List[str],
                     salary_basis: str = BASIS_NET,
                     cpf_status: str = cpf.STATUS_CITIZEN,
                     cpf_age_band: str = "55 and below",
                     include_employer_cpf: bool = False) -> pd.DataFrame:
    """Revenue split by source — what the Income pie shows."""
    salary = cpf_employee = cpf_employer = additional = 0.0
    for month_key in months:
        pnl = build_pnl(transactions, month_key, salary_basis, cpf_status,
                        cpf_age_band, include_employer_cpf)
        salary += pnl.salary_credited
        cpf_employee += pnl.cpf_employee
        cpf_employer += pnl.cpf_employer
        additional += pnl.additional_income

    rows = [
        ("Salary credited", round(salary, 2)),
        ("CPF — employee share", round(cpf_employee, 2)),
        ("Additional income", round(additional, 2)),
    ]
    if include_employer_cpf:
        rows.insert(2, ("CPF — employer share", round(cpf_employer, 2)))
    frame = pd.DataFrame(rows, columns=["Source", "Amount"])
    return frame[frame["Amount"] != 0].reset_index(drop=True)


def expense_breakdown(transactions: List[Transaction],
                      months: List[str]) -> pd.DataFrame:
    """Expenses by category, tagged Fixed or Variable — the Expenses pie."""
    rows = []
    month_txns = [t for t in transactions if t.month in months]
    for section, categories in ((FIXED, FIXED_CATEGORIES),
                                (VARIABLE, VARIABLE_CATEGORIES)):
        for category in categories:
            amount = _net(month_txns, category, expense=True)
            if amount:
                rows.append({
                    "Category": category,
                    "Section": "Fixed" if section == FIXED else "Variable",
                    "Amount": amount,
                })
    frame = pd.DataFrame(rows, columns=["Category", "Section", "Amount"])
    if frame.empty:
        return frame
    # A negative category (a refund with no matching spend) cannot be a slice of
    # a pie; report it separately rather than drawing a negative wedge.
    return frame.sort_values("Amount", ascending=False).reset_index(drop=True)


def savings_split(transactions: List[Transaction], months: List[str],
                  salary_basis: str = BASIS_NET,
                  cpf_status: str = cpf.STATUS_CITIZEN,
                  cpf_age_band: str = "55 and below",
                  include_employer_cpf: bool = False) -> pd.DataFrame:
    """Revenue divided into what was kept and what was spent — the Savings pie.

    Savings is one number, so the honest pie is the whole of revenue split in
    two: a wedge for the part kept and a wedge for the part spent.
    """
    revenue = expenses = 0.0
    for month_key in months:
        pnl = build_pnl(transactions, month_key, salary_basis, cpf_status,
                        cpf_age_band, include_employer_cpf)
        revenue += pnl.total_revenue
        expenses += pnl.total_expenses
    kept = round(revenue - expenses, 2)
    frame = pd.DataFrame(
        [("Saved", kept), ("Spent", round(expenses, 2))],
        columns=["Part", "Amount"],
    )
    return frame[frame["Amount"] > 0].reset_index(drop=True)


def ytd_series(transactions: List[Transaction], months: List[str],
               salary_basis: str = BASIS_NET,
               cpf_status: str = cpf.STATUS_CITIZEN,
               cpf_age_band: str = "55 and below",
               include_employer_cpf: bool = False) -> pd.DataFrame:
    """Long-form month x measure for the year-to-date dot plot.

    Every month of the calendar year gets a row so the x axis always runs
    January to December, but a month with no statements loaded carries a null
    Amount rather than a zero — the column holds its place and no dot is drawn,
    because a zero there would read as "earned nothing" rather than "not known".

    PrevChange and AvgChange are percentage changes against the previous month
    that *has* data and against the year's mean so far. They are computed here
    rather than in the chart so the same figures reach the export.
    """
    year = months[0].split("-")[0] if months else ""
    loaded = set(months)
    calendar = [f"{year}-{m:02d}" for m in range(1, 13)] if year else []

    figures = {}
    for month_key in calendar:
        if month_key not in loaded:
            continue
        pnl = build_pnl(transactions, month_key, salary_basis, cpf_status,
                        cpf_age_band, include_employer_cpf)
        figures[month_key] = {
            "Income": pnl.total_revenue,
            "Expenses": pnl.total_expenses,
            "Savings": pnl.net_income,
        }

    measures = ("Income", "Expenses", "Savings")
    averages = {}
    for measure in measures:
        values = [figures[m][measure] for m in figures]
        averages[measure] = (sum(values) / len(values)) if values else None

    rows = []
    for measure in measures:
        previous = None
        for order, month_key in enumerate(calendar):
            amount = figures.get(month_key, {}).get(measure)
            prev_change = avg_change = None
            if amount is not None:
                if previous not in (None, 0):
                    prev_change = (amount - previous) / abs(previous) * 100
                mean = averages[measure]
                if mean not in (None, 0):
                    avg_change = (amount - mean) / abs(mean) * 100
                previous = amount
            rows.append({
                "Month": month_key,
                "MonthLabel": MONTH_LABELS[order][:3],
                "Order": order,
                "Measure": measure,
                "Amount": amount,
                "PrevChange": prev_change,
                "AvgChange": avg_change,
                "HasData": month_key in figures,
            })
    return pd.DataFrame(rows, columns=[
        "Month", "MonthLabel", "Order", "Measure", "Amount",
        "PrevChange", "AvgChange", "HasData",
    ])


def trendlines(series: pd.DataFrame) -> pd.DataFrame:
    """Least-squares fit per measure, as endpoints ready to draw.

    Altair's `loess`/`regression` transforms need a quantitative x; the dot plot
    uses an ordinal month axis, so the fit is computed here against the month's
    ordinal position and returned as two points per measure.
    """
    if series.empty:
        return pd.DataFrame(columns=["Measure", "Order", "MonthLabel", "Fit"])
    # Months with no statements carry a null amount now that the axis runs the
    # full calendar year. Fitting through them would drag every trend towards
    # whatever pandas coerces the gap to.
    series = series[series["Amount"].notna()]
    if series.empty:
        return pd.DataFrame(columns=["Measure", "Order", "MonthLabel", "Fit"])
    rows = []
    for measure, group in series.groupby("Measure"):
        group = group.sort_values("Order")
        xs = group["Order"].tolist()
        ys = group["Amount"].tolist()
        n = len(xs)
        if n < 2:
            continue
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator == 0:
            continue
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
        intercept = mean_y - slope * mean_x
        for x in (xs[0], xs[-1]):
            label = group.loc[group["Order"] == x, "MonthLabel"].iloc[0]
            rows.append({
                "Measure": measure,
                "Order": x,
                "MonthLabel": label,
                "Fit": round(slope * x + intercept, 2),
            })
    return pd.DataFrame(rows, columns=["Measure", "Order", "MonthLabel", "Fit"])


# ---------------------------------------------------------------------------
# Item-level tables for the monthly page
#
# The income statement aggregates to one row per category; these give the
# individual transactions behind a section, which is what the monthly page
# tables show. "Payment method" is the account the money actually moved
# through — the card or bank account named in the statement's own preamble.
# ---------------------------------------------------------------------------
ITEM_COLUMNS = ["Item", "Category", "Payment Method", "Amount"]


def _payment_method(txn: Transaction) -> str:
    account = (txn.source_account or "").strip()
    return account if account and account.lower() != "unknown" else "—"


def section_items(transactions: List[Transaction], month_key: str,
                  section: str) -> pd.DataFrame:
    """Every transaction in one section of one month, newest rules applied.

    Amounts are signed the way the section reads: an expense is positive
    because the section is already called Expenses, and a refund inside it is
    negative because it reduces that category.
    """
    rows = []
    for txn in transactions:
        if txn.month != month_key or txn.section != section:
            continue
        if section == REVENUE:
            amount = txn.signed_amount
        else:
            amount = -txn.signed_amount
        rows.append({
            "Item": txn.description,
            "Category": txn.category,
            "Payment Method": _payment_method(txn),
            "Amount": round(amount, 2),
            "Date": txn.date,
        })
    frame = pd.DataFrame(rows, columns=ITEM_COLUMNS + ["Date"])
    if frame.empty:
        return frame
    return (frame.sort_values(["Category", "Date"], kind="stable")
                 .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Dashboard: income sources by name
# ---------------------------------------------------------------------------
# A Singapore bank credit wraps the payer in routing text: "Inward CR - GIRO
# TO91XKQBVM4HD7P SALA Salary Payment ACME ASIA PTE. LTD.". The company name is
# the part ending in a corporate suffix, so that is what we look for first.
_CORPORATE_SUFFIX = re.compile(
    # "Holdings" and "Group" are parts of a name, not legal suffixes — treating
    # them as the end would cut "Northwind Holdings Limited" down to "Northwind".
    r"\b(PTE\.?\s*LTD\.?|PRIVATE\s+LIMITED|LTD\.?|LIMITED|LLP|L\.?L\.?C\.?|"
    r"INC\.?|CORP\.?|CORPORATION)\b"
)
# Walking back from the suffix stops at any of these: past them lies the bank's
# routing, not the payer.
_HARD_ROUTING = {
    "GIRO", "SALA", "SALARY", "PAYMENT", "PAYMENTS", "TRANSFER", "TRF", "TT",
    "INWARD", "OUTWARD", "INCOMING", "REF", "TXN", "ADVICE", "FAST", "MEPS",
    "IBG", "IBFT", "PAYNOW", "PAYLAH", "OTHR", "CREDIT", "DEPOSIT", "REMITTANCE",
    "BONUS", "DIVIDEND", "INTEREST", "VIA", "FROM", "TO",
}
# The routing prefix a statement puts before the real description.
_ROUTING_PREFIX = re.compile(
    r"^(INWARD|OUTWARD|INCOMING|OTHR)\b[A-Z\s]{0,12}?-\s*"
)
_HAS_DIGIT = re.compile(r"\d")


def _source_name(txn: Transaction) -> str:
    """Best guess at who paid you, from the statement's own wording.

    Two shapes come up. A company payment names the company and ends in a
    corporate suffix, so the name is the few words before that suffix, stopping
    at the bank's own routing words. Anything else — bank interest, a dividend
    credit — has no counterparty at all, and its description already says what
    it is, so that is shown rather than a fabricated name.
    """
    text = (txn.raw_description or "").upper()
    text = _ROUTING_PREFIX.sub("", text).strip()
    tokens = [t for t in text.split() if not _HAS_DIGIT.search(t)]

    suffix = _CORPORATE_SUFFIX.search(" ".join(tokens))
    if suffix:
        before = " ".join(tokens)[:suffix.start()].split()
        name_parts = []
        for token in reversed(before):
            if token.strip(".,") in _HARD_ROUTING:
                break
            name_parts.insert(0, token)
            if len(name_parts) == 5:
                break
        if name_parts:
            whole = " ".join(tokens)
            return " ".join(name_parts + whole[suffix.start():suffix.end()].split()).title()

    cleaned = " ".join(tokens).strip(" -")
    if len(cleaned) < 3:
        return txn.description or "Unnamed source"
    return cleaned.title()


def income_sources(transactions: List[Transaction], months: List[str],
                   limit: int = 3) -> pd.DataFrame:
    """Who paid you this year: name, total received, and the latest payment.

    Grouped on the cleaned-up name rather than the category, because "top three
    income sources" is a question about payers, not about which P&L line they
    landed on.
    """
    buckets = {}
    for txn in transactions:
        if txn.month not in months or txn.direction != CREDIT:
            continue
        if txn.section != REVENUE:
            continue
        name = _source_name(txn)
        bucket = buckets.setdefault(name, {
            "Source": name, "Category": txn.category, "Total": 0.0,
            "Payments": 0, "LastDate": None, "LastAmount": 0.0,
        })
        bucket["Total"] += txn.amount_sgd
        bucket["Payments"] += 1
        if txn.date and (bucket["LastDate"] is None or txn.date >= bucket["LastDate"]):
            bucket["LastDate"] = txn.date
            bucket["LastAmount"] = txn.amount_sgd
    frame = pd.DataFrame(list(buckets.values()), columns=[
        "Source", "Category", "Total", "Payments", "LastDate", "LastAmount",
    ])
    if frame.empty:
        return frame
    frame["Total"] = frame["Total"].round(2)
    frame["LastAmount"] = frame["LastAmount"].round(2)
    return (frame.sort_values("Total", ascending=False)
                 .head(limit).reset_index(drop=True))


# ---------------------------------------------------------------------------
# Dashboard: savings, this year against last
# ---------------------------------------------------------------------------
def savings_stack(transactions: List[Transaction], year: str,
                  salary_basis: str = BASIS_NET,
                  cpf_status: str = cpf.STATUS_CITIZEN,
                  cpf_age_band: str = "55 and below",
                  include_employer_cpf: bool = False) -> pd.DataFrame:
    """Saved vs spent for `year`, and the same for the year before it.

    The previous year comes back as its own row only when statements for it are
    actually loaded — the chart draws it as an outline, and an outline around a
    zero would suggest last year was a year of no savings rather than a year
    you have not uploaded.
    """
    args = (salary_basis, cpf_status, cpf_age_band, include_employer_cpf)
    rows = []
    for which, target in (("Current", year), ("Previous", str(int(year) - 1))):
        months = months_in_year(transactions, target)
        if not months:
            continue
        saved = spent = 0.0
        for month_key in months:
            pnl = build_pnl(transactions, month_key, *args)
            saved += pnl.net_income
            spent += pnl.total_expenses
        rows.append({
            "Series": which,
            "Year": target,
            "Saved": round(saved, 2),
            "Spent": round(spent, 2),
            "Months": len(months),
        })
    return pd.DataFrame(rows, columns=["Series", "Year", "Saved", "Spent", "Months"])


def cumulative_savings(transactions: List[Transaction],
                       salary_basis: str = BASIS_NET,
                       cpf_status: str = cpf.STATUS_CITIZEN,
                       cpf_age_band: str = "55 and below",
                       include_employer_cpf: bool = False) -> pd.DataFrame:
    """Savings per year, oldest first, with a running total.

    A year is marked YTD unless all twelve months have statements loaded. That
    is stricter than the calendar — a finished year with two months missing is
    still YTD here — but the label then describes what the bar is actually
    built from rather than what the date says.
    """
    args = (salary_basis, cpf_status, cpf_age_band, include_employer_cpf)
    rows = []
    running = 0.0
    for order, year in enumerate(sorted(years_with_months(transactions))):
        months = months_in_year(transactions, year)
        saved = sum(build_pnl(transactions, m, *args).net_income for m in months)
        running += saved
        complete = len(months) == 12
        rows.append({
            "Year": year,
            "Order": order,
            "Saved": round(saved, 2),
            "Cumulative": round(running, 2),
            "Months": len(months),
            "Complete": complete,
            "Label": year if complete else f"{year} YTD",
        })
    return pd.DataFrame(rows, columns=[
        "Year", "Order", "Saved", "Cumulative", "Months", "Complete", "Label",
    ])


def cumulative_trend(frame: pd.DataFrame) -> pd.DataFrame:
    """Least-squares fit through the yearly savings bars, as two endpoints."""
    if frame.empty or len(frame) < 2:
        return pd.DataFrame(columns=["Label", "Order", "Fit"])
    xs = frame["Order"].tolist()
    ys = frame["Saved"].tolist()
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return pd.DataFrame(columns=["Label", "Order", "Fit"])
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    rows = [{
        "Label": frame.loc[frame["Order"] == x, "Label"].iloc[0],
        "Order": x,
        "Fit": round(slope * x + intercept, 2),
    } for x in (xs[0], xs[-1])]
    return pd.DataFrame(rows, columns=["Label", "Order", "Fit"])


def expense_cumulative(transactions: List[Transaction],
                       months: List[str]) -> pd.DataFrame:
    """Total spend per category over the year, biggest first.

    This is the annual counterpart to the monthly breakdown: one bar per
    category for the whole year, rather than a dot per month.
    """
    totals = {}
    for txn in transactions:
        if txn.month not in months or txn.section not in (FIXED, VARIABLE):
            continue
        entry = totals.setdefault(txn.category, {
            "Category": txn.category,
            "Section": "Fixed" if txn.section == FIXED else "Variable",
            "Amount": 0.0, "Transactions": 0,
        })
        entry["Amount"] += -txn.signed_amount
        entry["Transactions"] += 1
    frame = pd.DataFrame(list(totals.values()),
                         columns=["Category", "Section", "Amount", "Transactions"])
    if frame.empty:
        return frame
    frame["Amount"] = frame["Amount"].round(2)
    return frame.sort_values("Amount", ascending=False).reset_index(drop=True)
