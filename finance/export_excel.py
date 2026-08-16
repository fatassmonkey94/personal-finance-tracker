"""Write the monthly workbook: one transaction sheet and one P&L sheet per month."""
from __future__ import annotations

import io
import re
from typing import List, Optional

import pandas as pd

from . import cpf
from .model import Transaction
from .report import (
    BASIS_NET,
    available_months,
    build_pnl,
    category_breakdown,
    compilation_frame,
    month_label,
    monthly_trend,
    pnl_frame,
    review_frame,
)

MONEY = "#,##0.00;[Red](#,##0.00)"
DATE_FMT = "dd mmm yyyy"


def _safe_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "-", name)
    return cleaned[:31]


def build_workbook(transactions: List[Transaction], months: Optional[List[str]] = None,
                   salary_basis: str = BASIS_NET,
                   cpf_status: str = cpf.STATUS_CITIZEN,
                   cpf_age_band: str = "55 and below",
                   include_employer_cpf: bool = False) -> bytes:
    """Return .xlsx bytes covering the given months (all months if None)."""
    months = months or available_months(transactions)
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="xlsxwriter",
                        datetime_format=DATE_FMT, date_format=DATE_FMT) as writer:
        book = writer.book
        fmt = _formats(book)

        _write_summary(writer, fmt, transactions, months, salary_basis,
                       cpf_status, cpf_age_band, include_employer_cpf)

        for month_key in months:
            pnl = build_pnl(transactions, month_key, salary_basis,
                            cpf_status, cpf_age_band, include_employer_cpf)
            short = _short_month(month_key)
            _write_pnl_sheet(writer, fmt, pnl, f"P&L {short}")
            _write_transactions_sheet(
                writer, fmt, compilation_frame(transactions, month_key),
                f"Transactions {short}", month_key,
            )

        review = review_frame(transactions)
        if not review.empty:
            _write_transactions_sheet(writer, fmt, review, "Review", None)

    buffer.seek(0)
    return buffer.getvalue()


def _short_month(month_key: str) -> str:
    try:
        year, month = month_key.split("-")
        names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{names[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return month_key


def _formats(book) -> dict:
    return {
        "title": book.add_format({"bold": True, "font_size": 15, "font_color": "#1F3864"}),
        "subtitle": book.add_format({"italic": True, "font_size": 10, "font_color": "#555555"}),
        "header": book.add_format({
            "bold": True, "bg_color": "#1F3864", "font_color": "white",
            "border": 1, "align": "left", "valign": "vcenter", "text_wrap": True,
        }),
        "section": book.add_format({
            "bold": True, "font_size": 11, "bg_color": "#D9E1F2", "border": 1,
        }),
        "section_money": book.add_format({
            "bold": True, "bg_color": "#D9E1F2", "border": 1, "num_format": MONEY,
        }),
        "item": book.add_format({"border": 1}),
        "item_money": book.add_format({"border": 1, "num_format": MONEY}),
        "subtotal": book.add_format({
            "bold": True, "border": 1, "top": 2, "bg_color": "#F2F2F2",
        }),
        "subtotal_money": book.add_format({
            "bold": True, "border": 1, "top": 2, "bg_color": "#F2F2F2",
            "num_format": MONEY,
        }),
        "total": book.add_format({
            "bold": True, "font_size": 12, "border": 1, "top": 2, "bottom": 6,
            "bg_color": "#1F3864", "font_color": "white",
        }),
        "total_money": book.add_format({
            "bold": True, "font_size": 12, "border": 1, "top": 2, "bottom": 6,
            "bg_color": "#1F3864", "font_color": "white", "num_format": MONEY,
        }),
        "date": book.add_format({"border": 1, "num_format": DATE_FMT}),
        "money": book.add_format({"border": 1, "num_format": MONEY}),
        "text": book.add_format({"border": 1}),
        "wrap": book.add_format({"border": 1, "text_wrap": True, "valign": "top"}),
        "note": book.add_format({"font_color": "#9C5700", "italic": True}),
        "int": book.add_format({"border": 1, "num_format": "0", "align": "center"}),
        "pct": book.add_format({"border": 1, "num_format": "0.0"}),
    }


def _write_pnl_sheet(writer, fmt, pnl, sheet_name: str) -> None:
    sheet = writer.book.add_worksheet(_safe_sheet_name(sheet_name))
    writer.sheets[_safe_sheet_name(sheet_name)] = sheet

    sheet.set_column("A:A", 46)
    sheet.set_column("B:B", 16)
    sheet.set_column("C:C", 8)

    sheet.write("A1", f"Income Statement — {pnl.label}", fmt["title"])
    basis = ("bank credit treated as take-home, grossed up"
             if pnl.salary_basis == BASIS_NET else "bank credit treated as gross")
    ceiling = pnl.cpf.ceiling if pnl.cpf else 0
    sheet.write("A2", f"All amounts in SGD as converted by the issuing bank or card. "
                      f"CPF per CPF Board rates, Ordinary Wage ceiling "
                      f"S${ceiling:,.0f} ({basis}).", fmt["subtitle"])

    row = 3
    sheet.write(row, 0, "Line Item", fmt["header"])
    sheet.write(row, 1, "Amount (SGD)", fmt["header"])
    sheet.write(row, 2, "Txns", fmt["header"])
    row += 1

    for line in pnl.lines:
        if line.kind == "spacer":
            row += 1
            continue
        indent = "    " * line.indent
        label = indent + line.label
        if line.kind == "header":
            sheet.write(row, 0, label, fmt["section"])
            sheet.write_blank(row, 1, None, fmt["section_money"])
            sheet.write_blank(row, 2, None, fmt["section"])
        elif line.kind == "subtotal":
            sheet.write(row, 0, label, fmt["subtotal"])
            sheet.write_number(row, 1, line.amount, fmt["subtotal_money"])
            sheet.write_blank(row, 2, None, fmt["subtotal"])
        elif line.kind == "total":
            sheet.write(row, 0, label, fmt["total"])
            sheet.write_number(row, 1, line.amount, fmt["total_money"])
            sheet.write_blank(row, 2, None, fmt["total"])
        else:
            sheet.write(row, 0, label, fmt["item"])
            sheet.write_number(row, 1, line.amount, fmt["item_money"])
            if line.count:
                sheet.write_number(row, 2, line.count, fmt["int"])
            else:
                sheet.write_blank(row, 2, None, fmt["item"])
        row += 1

    row += 1
    sheet.write(row, 0, "Net income = Total Revenues - (Fixed Expenses + Variable Expenses)",
                fmt["subtitle"])
    row += 2

    if pnl.excluded_count:
        sheet.write(row, 0,
                    f"Excluded from this statement: {pnl.excluded_count} transfer(s) "
                    f"totalling S${pnl.excluded_total:,.2f} (credit card bill payments and "
                    f"transfers between your own accounts). Counting them would "
                    f"double-count the card spending itself.", fmt["note"])
        row += 2

    for warning in pnl.warnings:
        sheet.write(row, 0, "Note: " + warning, fmt["note"])
        row += 1

    sheet.freeze_panes(4, 0)


def _write_transactions_sheet(writer, fmt, frame: pd.DataFrame, sheet_name: str,
                              month_key: Optional[str]) -> None:
    name = _safe_sheet_name(sheet_name)
    sheet = writer.book.add_worksheet(name)
    writer.sheets[name] = sheet

    heading = (f"Transactions — {month_label(month_key)}" if month_key
               else "Transactions flagged for review")
    sheet.write("A1", heading, fmt["title"])
    sheet.write("A2", "Chronological. Amounts in SGD as converted by the bank or card at "
                      "the point of transaction.", fmt["subtitle"])

    if frame.empty:
        sheet.write("A4", "No transactions.", fmt["subtitle"])
        return

    header_row = 3
    widths = {
        "Date": 12, "Description": 42, "Category": 26, "Section": 17, "Type": 8,
        "Amount (SGD)": 14, "Source Account": 22, "Original Currency": 9,
        "Original Amount": 14, "Raw Statement Text": 52, "Flag": 20,
        "Why flagged": 46,
    }
    for col, column in enumerate(frame.columns):
        sheet.write(header_row, col, column, fmt["header"])
        sheet.set_column(col, col, widths.get(column, 18))

    for offset, (_, record) in enumerate(frame.iterrows()):
        row = header_row + 1 + offset
        for col, column in enumerate(frame.columns):
            value = record[column]
            if pd.isna(value) or value is None:
                sheet.write_blank(row, col, None, fmt["text"])
            elif column == "Date":
                sheet.write_datetime(row, col, pd.Timestamp(value).to_pydatetime(), fmt["date"])
            elif column in ("Amount (SGD)", "Original Amount"):
                sheet.write_number(row, col, float(value), fmt["money"])
            elif column in ("Raw Statement Text", "Why flagged"):
                sheet.write(row, col, str(value), fmt["wrap"])
            else:
                sheet.write(row, col, str(value), fmt["text"])

    last_row = header_row + len(frame)
    sheet.freeze_panes(header_row + 1, 0)
    sheet.autofilter(header_row, 0, last_row, len(frame.columns) - 1)

    if "Amount (SGD)" in frame.columns and "Type" in frame.columns:
        amount_col = list(frame.columns).index("Amount (SGD)")
        type_col = list(frame.columns).index("Type")
        first = header_row + 2  # 1-based Excel row of the first data row
        last = last_row + 1
        col_letter = chr(ord("A") + amount_col)
        type_letter = chr(ord("A") + type_col)
        # Pass the computed result as the cached value too: xlsxwriter cannot
        # evaluate formulas, and without a cached value the cell reads 0 in any
        # viewer that does not recalculate on open.
        debit_total = float(frame.loc[frame["Type"] == "Debit", "Amount (SGD)"].sum())
        credit_total = float(frame.loc[frame["Type"] == "Credit", "Amount (SGD)"].sum())

        total_row = last_row + 2
        sheet.write(total_row, 0, "Total debits (money out)", fmt["subtotal"])
        sheet.write_formula(
            total_row, amount_col,
            f'=SUMIF({type_letter}{first}:{type_letter}{last},"Debit",'
            f'{col_letter}{first}:{col_letter}{last})',
            fmt["subtotal_money"], round(debit_total, 2),
        )
        sheet.write(total_row + 1, 0, "Total credits (money in)", fmt["subtotal"])
        sheet.write_formula(
            total_row + 1, amount_col,
            f'=SUMIF({type_letter}{first}:{type_letter}{last},"Credit",'
            f'{col_letter}{first}:{col_letter}{last})',
            fmt["subtotal_money"], round(credit_total, 2),
        )


def _write_summary(writer, fmt, transactions, months, salary_basis,
                   cpf_status, cpf_age_band, include_employer_cpf) -> None:
    sheet = writer.book.add_worksheet("Summary")
    writer.sheets["Summary"] = sheet
    sheet.set_column("A:A", 26)
    sheet.set_column("B:G", 17)

    sheet.write("A1", "Personal Finance Summary", fmt["title"])
    sheet.write("A2", f"{len(transactions)} transactions across "
                      f"{len({t.source_account for t in transactions})} accounts/cards, "
                      f"covering {len(months)} month(s).", fmt["subtitle"])

    trend = monthly_trend(transactions, salary_basis, cpf_status,
                          cpf_age_band, include_employer_cpf)
    trend = trend[trend["Month"].isin([month_label(m) for m in months])]

    row = 4
    if not trend.empty:
        for col, column in enumerate(trend.columns):
            sheet.write(row, col, column, fmt["header"])
        for offset, (_, record) in enumerate(trend.iterrows()):
            data_row = row + 1 + offset
            for col, column in enumerate(trend.columns):
                value = record[column]
                if column == "Month":
                    sheet.write(data_row, col, str(value), fmt["text"])
                elif pd.isna(value):
                    sheet.write_blank(data_row, col, None, fmt["money"])
                elif column == "Savings Rate":
                    sheet.write_number(data_row, col, float(value), fmt["pct"])
                else:
                    sheet.write_number(data_row, col, float(value), fmt["money"])
        row += len(trend) + 3

    for month_key in months:
        breakdown = category_breakdown(transactions, month_key)
        if breakdown.empty:
            continue
        sheet.write(row, 0, f"Category detail — {month_label(month_key)}", fmt["section"])
        row += 1
        for col, column in enumerate(breakdown.columns):
            sheet.write(row, col, column, fmt["header"])
        row += 1
        for _, record in breakdown.iterrows():
            sheet.write(row, 0, str(record["Section"]), fmt["text"])
            sheet.write(row, 1, str(record["Category"]), fmt["text"])
            sheet.write_number(row, 2, float(record["Amount (SGD)"]), fmt["money"])
            sheet.write_number(row, 3, int(record["Transactions"]), fmt["int"])
            row += 1
        row += 2

    sheet.freeze_panes(4, 0)
