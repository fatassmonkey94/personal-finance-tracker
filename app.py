"""Personal Finance Tracker — Streamlit front end.

Run with:  ./run.sh      (or)  .venv/bin/streamlit run app.py
Everything stays on this machine; no data leaves the process.
"""
from __future__ import annotations

import glob
import os
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from finance import cpf
from finance.export_excel import build_workbook
from finance.ingest import default_overrides_path, ingest_files
from finance.model import ASSIGNABLE_CATEGORIES, CREDIT, DEBIT, EXCLUDED
from finance.report import (
    BASIS_GROSS,
    BASIS_NET,
    annual_summary,
    available_months,
    build_pnl,
    category_breakdown,
    category_by_month,
    compilation_frame,
    line_transactions,
    month_label,
    month_short,
    monthly_trend,
    pnl_display_frame,
    review_frame,
)
from finance.rules import DEFAULT_PARENT_NAMES, save_overrides

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_PATH = default_overrides_path(BASE_DIR)
STATEMENT_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls", ".pdf")
# Real family names do not belong in source. They live here instead, in a
# gitignored file, so the sidebar remembers them without them being committed.
PARENT_NAMES_PATH = os.path.join(BASE_DIR, "data", "parent_names.txt")


def load_parent_names() -> list:
    try:
        with open(PARENT_NAMES_PATH) as handle:
            return [line.strip() for line in handle if line.strip()]
    except OSError:
        return list(DEFAULT_PARENT_NAMES)


def save_parent_names(names: list) -> None:
    os.makedirs(os.path.dirname(PARENT_NAMES_PATH), exist_ok=True)
    with open(PARENT_NAMES_PATH, "w") as handle:
        handle.write("\n".join(names) + ("\n" if names else ""))

st.set_page_config(page_title="Personal Finance Tracker", page_icon="📊", layout="wide")

# Dark minimalist polish, plus the two things Streamlit gives no API for:
#  * the view strip is a radio group, dressed to read as a row of tabs;
#  * the Review sub-tab is always the third one, so it can be tinted by position.
# Palette matches .streamlit/config.toml.
st.markdown(
    """
    <style>
      :root {
        --ink:      #0B0C0E;
        --panel:    #14161A;
        --hairline: #24272E;
        --muted:    #9AA4B2;
        --bright:   #E7E9EC;
        --accent:   #7DD3C0;
        --warn-bg:  #2A1A1D;
        --warn-fg:  #F0959B;
      }

      .block-container { padding-top: 2.2rem; max-width: 1680px; }

      /* Minimalist headings: tight, letter-spaced, no decoration. */
      h1, h2, h3, h4, h5 { letter-spacing: -0.015em; }
      h1 { font-weight: 600 !important; }
      hr { border-color: var(--hairline) !important; margin: 1.6rem 0 !important; }

      /* Metrics: the numbers are the interface, so give them room and quiet
         their labels to small caps. */
      div[data-testid="stMetricValue"] {
          font-size: 1.7rem;
          font-weight: 600;
          letter-spacing: -0.02em;
          font-variant-numeric: tabular-nums;
      }
      div[data-testid="stMetricLabel"] p {
          font-size: 0.72rem !important;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--muted) !important;
      }
      div[data-testid="stMetricDelta"] { font-size: 0.78rem; }

      /* Tabular figures everywhere a number is read in a column. */
      div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
          font-variant-numeric: tabular-nums;
      }

      /* View strip: a radio group dressed as a tab bar. Scoped to
         .st-key-month_strip so other radios keep their normal look. */
      .st-key-month_strip div[role="radiogroup"] {
          border-bottom: 1px solid var(--hairline);
          gap: 0;
          flex-wrap: wrap;
          align-items: flex-end;
      }
      .st-key-month_strip div[role="radiogroup"] > label {
          border-radius: 0;
          padding: 0.45rem 1.05rem 0.5rem 1.05rem;
          margin-bottom: -1px;
          border-bottom: 1px solid transparent;
      }
      /* Hide the radio dot so the labels read as tabs. */
      .st-key-month_strip div[role="radiogroup"] > label
        > div:first-child { display: none; }
      .st-key-month_strip div[role="radiogroup"] > label p {
          color: var(--muted) !important;
          font-size: 0.9rem;
          letter-spacing: 0.01em;
      }
      .st-key-month_strip div[role="radiogroup"] > label:hover {
          background: var(--panel);
      }
      .st-key-month_strip div[role="radiogroup"] > label:hover p {
          color: var(--bright) !important;
      }
      .st-key-month_strip div[role="radiogroup"] > label:has(input:checked) {
          border-bottom: 1px solid var(--accent);
          background: transparent;
      }
      .st-key-month_strip div[role="radiogroup"] > label:has(input:checked) p {
          color: var(--accent) !important;
          font-weight: 600;
      }

      /* Sub-tabs: flat, hairline underline on the active one. */
      div[data-testid="stTabs"] div[data-baseweb="tab-list"] {
          gap: 0;
          border-bottom: 1px solid var(--hairline);
      }
      div[data-testid="stTabs"] button[data-baseweb="tab"] {
          border-radius: 0;
          padding-left: 1rem;
          padding-right: 1rem;
      }

      /* Review sub-tab — a muted red wash, the dark-theme reading of pastel. */
      div[data-testid="stTabs"] div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3) {
          background-color: var(--warn-bg);
      }
      div[data-testid="stTabs"] div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3) p {
          color: var(--warn-fg) !important;
          font-weight: 600;
      }
      div[data-testid="stTabs"] div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3):hover {
          background-color: #332024;
      }
      div[data-testid="stTabs"] div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3)[aria-selected="true"] {
          background-color: #3A2429;
      }

      /* Charts sit on the page, not in a box. */
      div[data-testid="stVegaLiteChart"] { background: transparent; }
    </style>
    """,
    unsafe_allow_html=True,
)

# A teal ramp with monotonically rising lightness: later months read brighter,
# and every stop stays legible against the near-black page. Viridis and the like
# put their darkest stop at roughly the page colour, which loses the first month.
_MONTH_RAMP = [
    "#1F5F55", "#25705F", "#2B8071", "#329182", "#3AA294", "#48B3A4",
    "#5CC3B4", "#74D2C2", "#8FDFD1", "#AAEADF", "#C6F3EB", "#DEFAF5",
]


def _month_ramp(count: int) -> list:
    """`count` evenly spaced stops from the ramp, darkest first."""
    if count <= 1:
        return [_MONTH_RAMP[-4]]
    if count >= len(_MONTH_RAMP):
        return _MONTH_RAMP[:count]
    step = (len(_MONTH_RAMP) - 1) / (count - 1)
    return [_MONTH_RAMP[round(i * step)] for i in range(count)]


def md(text: str) -> str:
    """Escape dollar signs for Streamlit markdown.

    Streamlit treats a pair of `$` as LaTeX math, so "S$8,000 … S$102,000"
    renders as an equation instead of two amounts.
    """
    return str(text).replace("$", r"\$")


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
for key, default in [
    ("txns", []),
    ("docs", []),
    ("notes", []),
    ("preloaded", False),
    ("drill_shown", {}),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Sidebar: settings
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    st.caption("CPF (per CPF Board rates)")
    cpf_status = st.selectbox(
        "Residency status", cpf.STATUSES, index=0,
        help="Singapore Citizens and Permanent Residents from their 3rd year use "
             "CPF Board's Table 1 — the default.",
    )
    cpf_age_band = st.selectbox(
        "Age band", cpf.AGE_BANDS, index=0,
        help="Contribution rates step down with age. 55 and below pays the full "
             "20% employee share.",
    )
    salary_basis_label = st.radio(
        "The salary in my bank statement is…",
        ["Take-home pay, after my CPF deduction", "Already the gross figure"],
        help=(
            "A Singapore salary credit is normally net of your own CPF share. On "
            "that basis the gross is worked back from it, so Salary + CPF equals "
            "true gross pay. Pick the second option to treat the credited figure "
            "as gross and add CPF on top of it."
        ),
    )
    salary_basis = BASIS_NET if salary_basis_label.startswith("Take-home") else BASIS_GROSS
    include_employer_cpf = st.checkbox(
        "Also count the employer's CPF share as revenue", value=False,
        help="Off by default: your brief asked for the 20% employee contribution. "
             "Switch on to show total cost of employment.",
    )
    st.caption(md(
        f"Ordinary Wage ceiling: S${cpf.ow_ceiling_for(date.today()):,.0f}/month · "
        f"annual salary ceiling S${cpf.ANNUAL_SALARY_CEILING:,.0f}"
    ))

    st.divider()
    st.caption("Categorisation")
    employer_text = st.text_input(
        "Employer name(s) on your salary credit",
        value="",
        help="Optional. Comma-separated. Helps catch salary credits that don't say "
             "'SALARY' — e.g. 'ACME PTE LTD'.",
    )
    parents_text = st.text_area(
        "Names that mean 'allowance to parents'",
        value="\n".join(load_parent_names()),
        height=90,
        help="One per line. Transfers matching these names are booked as "
             "Allowance to Parents. Kept in data/parent_names.txt, which is "
             "gitignored — real names never reach the repository.",
    )
    transfer_threshold = st.number_input(
        "Hold transfers above (SGD) for review", min_value=0.0, value=500.0, step=50.0,
        help=(
            "PayNow and bank transfers you have not named a merchant for are booked "
            "to Food & Dining (out) or Additional Income (in), per your rules. Above "
            "this amount that guess is too consequential, so they are held out of the "
            "income statement and listed for you to assign. Set 0 to switch this off."
        ),
    )

    st.divider()
    st.caption("PDF handling")
    pdf_password = st.text_input(
        "PDF password (if statements are locked)", type="password", value="",
        help="Used only in memory to open the PDF; never written to disk.",
    )
    fallback_month = st.text_input(
        "Fallback month for dateless PDFs (YYYY-MM)", value="",
        help="Only used when a PDF has no statement period and no line dates.",
    )

    if os.path.exists(OVERRIDES_PATH):
        st.divider()
        st.caption(f"Learned category fixes: `{os.path.relpath(OVERRIDES_PATH, BASE_DIR)}`")
        if st.button("Forget learned fixes", width="stretch"):
            os.remove(OVERRIDES_PATH)
            st.success("Cleared. Re-parse to apply.")

employer_keywords = [e.strip() for e in employer_text.split(",") if e.strip()]
parent_names = [p.strip() for p in parents_text.splitlines() if p.strip()]
if parent_names != load_parent_names():
    save_parent_names(parent_names)
PNL_ARGS = (salary_basis, cpf_status, cpf_age_band, include_employer_cpf)


# ---------------------------------------------------------------------------
# Header + loading
# ---------------------------------------------------------------------------
st.title("📊 Personal Finance Tracker")
st.caption(
    "Upload bank and credit card statements — CSV, Excel or PDF. "
    "Everything is processed locally on this machine."
)

uploads = st.file_uploader(
    "Statement files",
    type=["csv", "tsv", "txt", "xlsx", "xlsm", "xls", "pdf"],
    accept_multiple_files=True,
    help="CSV/Excel need description, date, amount and currency. "
         "PDF card statements need description and amount; dates are read when present.",
)

with st.expander("…or read them straight off this machine", expanded=False):
    folder_path = st.text_input(
        "Folder or file paths",
        value=os.environ.get("PFT_STATEMENTS", ""),
        placeholder="~/Downloads/statements     (or comma-separated file paths)",
        help="Handy month to month: point at the folder you save statements into "
             "instead of picking files by hand every time.",
    )
    folder_clicked = st.button("Read from this path")


def _collect_from_path(raw_path: str):
    """Expand a folder, a glob, or a comma-separated list into (name, bytes)."""
    found, problems = [], []
    for piece in [p.strip() for p in raw_path.split(",") if p.strip()]:
        target = os.path.expanduser(piece)
        if os.path.isdir(target):
            entries = [
                os.path.join(target, name) for name in sorted(os.listdir(target))
                if name.lower().endswith(STATEMENT_EXTENSIONS)
                and not name.startswith(".")
            ]
            if not entries:
                problems.append(f"No statement files in {target}")
            candidates = entries
        else:
            candidates = sorted(glob.glob(target)) or [target]
        for path in candidates:
            if not os.path.isfile(path):
                problems.append(f"Not found: {path}")
                continue
            if not path.lower().endswith(STATEMENT_EXTENSIONS):
                problems.append(f"Unsupported file type: {os.path.basename(path)}")
                continue
            try:
                with open(path, "rb") as handle:
                    found.append((os.path.basename(path), handle.read()))
            except OSError as exc:
                problems.append(f"Could not read {os.path.basename(path)}: {exc}")
    return found, problems


def _process(files):
    with st.spinner("Reading statements, categorising transactions…"):
        return ingest_files(
            files,
            parent_names=parent_names,
            employer_keywords=employer_keywords,
            fallback_month=fallback_month.strip() or None,
            pdf_password=pdf_password or None,
            overrides_path=OVERRIDES_PATH,
            transfer_review_threshold=transfer_threshold,
        )


col_a, col_b = st.columns([1, 4])
with col_a:
    parse_clicked = st.button("Process statements", type="primary",
                              width="stretch", disabled=not uploads)
with col_b:
    if uploads:
        st.caption(f"{len(uploads)} file(s) ready: " + ", ".join(f.name for f in uploads))

# Preload once per session when a path was supplied via the environment, so
# `PFT_STATEMENTS=... streamlit run app.py` opens with results already on screen.
preload = os.environ.get("PFT_STATEMENTS", "").strip()
if preload and not st.session_state.preloaded:
    st.session_state.preloaded = True
    files, problems = _collect_from_path(preload)
    for problem in problems:
        st.warning(problem)
    if files:
        (st.session_state.txns, st.session_state.docs,
         st.session_state.notes) = _process(files)

if folder_clicked and folder_path.strip():
    files, problems = _collect_from_path(folder_path)
    for problem in problems:
        st.warning(problem)
    if files:
        (st.session_state.txns, st.session_state.docs,
         st.session_state.notes) = _process(files)
    else:
        st.error("Nothing readable at that path.")

if parse_clicked and uploads:
    (st.session_state.txns, st.session_state.docs,
     st.session_state.notes) = _process([(f.name, f.getvalue()) for f in uploads])

txns = st.session_state.txns
docs = st.session_state.docs

if docs:
    all_warnings = [w for d in docs for w in d.warnings]
    parsed_counts = ", ".join(
        f"**{d.filename}** → {len(d.transactions)} txns" for d in docs
    )
    if txns:
        st.success(f"Parsed {len(txns)} transactions. {parsed_counts}")
    for warning in all_warnings:
        st.warning(md(warning))
    for note in st.session_state.notes:
        st.info(md(note))

if not txns:
    with st.expander("What the app expects in each file", expanded=not docs):
        st.markdown(
            """
**CSV / Excel** — one row per transaction. Column names are matched flexibly, so
these all work: `Transaction Date` / `Date` / `Posting Date`; `Description` /
`Particulars` / `Transaction Ref1..3`; either a signed `Amount` column, a
`Debit`/`Credit` pair, or `Amount` + a `DR/CR` column; optional `Currency` and
`Foreign Amount`. Preamble rows above the header are skipped automatically.

**PDF** — credit card or bank statements with a text layer. Each transaction line
is read as *date (if present) · description · foreign currency detail (if any) ·
SGD amount*. The statement period is detected to supply the year. Scanned PDFs
with no text layer need OCR first.

**A note on double counting** — a credit card bill paid from your bank account is
a transfer, not an expense. Those rows are tagged *Credit Card Bill Payment* and
kept out of the income statement, so the card's own transactions are counted once.
            """
        )
    st.stop()

months = available_months(txns)
if not months:
    st.error("No dated transactions were found. Check the parsing log below.")
    st.stop()


# ---------------------------------------------------------------------------
# Drill-down dialog: the transactions behind one income-statement line
# ---------------------------------------------------------------------------
@st.dialog("Line item detail", width="large")
def show_line_detail(month_key: str, line, rows):
    st.markdown(f"**{line.label.strip()}** — {month_label(month_key)}")
    st.markdown(md(f"### S${line.amount:,.2f}"))

    if line.note:
        st.info(md(line.note))

    if not rows:
        if not line.note:
            st.caption("No transactions behind this line.")
        return

    debits = sum(t.amount_sgd for t in rows if t.direction == DEBIT)
    credits = sum(t.amount_sgd for t in rows if t.direction == CREDIT)
    cols = st.columns(3)
    cols[0].metric("Transactions", len(rows))
    cols[1].metric("Money out", f"S${debits:,.2f}")
    cols[2].metric("Money in", f"S${credits:,.2f}")
    if credits and debits:
        st.caption(
            "The line total nets money in against money out — a refund reduces the "
            "category it was spent from."
        )

    # Scrollable so a long month stays inside the dialog.
    with st.container(height=340):
        detail = pd.DataFrame([
            {
                "Date": t.date,
                "Description": t.description,
                "Category": t.category,
                "Type": t.direction,
                "Amount (SGD)": f"{t.amount_sgd:,.2f}",
                "Account": t.source_account,
                "Raw statement text": t.raw_description,
            }
            for t in rows
        ])
        st.dataframe(
            detail, hide_index=True, width="stretch",
            column_config={
                "Date": st.column_config.DateColumn(format="DD MMM YYYY", width="small"),
                "Description": st.column_config.TextColumn(width="medium"),
                "Amount (SGD)": st.column_config.TextColumn(width="small"),
                "Raw statement text": st.column_config.TextColumn(width="large"),
            },
        )


def render_income_statement(month_key: str, pnl):
    left, right = st.columns([3, 2])

    with left:
        st.markdown("##### Income statement")
        st.caption("Click any line to see the transactions behind it.")
        frame = pnl_display_frame(pnl)
        event = st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            height=min(820, 44 + 35 * len(frame)),
            on_select="rerun",
            selection_mode="single-row",
            key=f"pnl_{month_key}",
            column_config={
                "Line Item": st.column_config.TextColumn("Line Item", width="large"),
                "Amount (SGD)": st.column_config.TextColumn("Amount (SGD)", width="small"),
                "Txns": st.column_config.TextColumn("Txns", width="small"),
            },
        )
        st.caption("Net income = Total Revenues − (Fixed Expenses + Variable Expenses)")

        selected = list(event.selection.rows) if event and event.selection else []
        if selected:
            index = selected[0]
            line = pnl.lines[index]
            # Record the request rather than opening the dialog here. Opening it
            # from inside a tab remounts the tab strip and bounces the user back
            # to the first month; the caller opens it at top level instead.
            token = f"{month_key}:{index}"
            if line.drillable:
                if st.session_state.drill_shown.get("token") != token:
                    st.session_state.drill_shown["token"] = token
                    st.session_state.drill_shown["pending"] = (month_key, index)
                else:
                    if st.button("Reopen detail", key=f"reopen_{month_key}"):
                        st.session_state.drill_shown["pending"] = (month_key, index)
            else:
                st.session_state.drill_shown["token"] = token
                st.caption("That row is a heading — pick a line item or a total.")

    with right:
        st.markdown("##### Where the money went")
        breakdown = category_breakdown(txns, month_key)
        expenses = breakdown[breakdown["Section"] != "Revenue"].copy()
        expenses = expenses[expenses["Amount (SGD)"] != 0]
        if expenses.empty:
            st.info("No expenses recorded for this month.")
        else:
            chart = expenses.set_index("Category")["Amount (SGD)"].sort_values(ascending=False)
            st.bar_chart(chart, height=320)
            expenses["% of total"] = (
                expenses["Amount (SGD)"] / pnl.total_expenses * 100
            ).round(1) if pnl.total_expenses else 0
            shown = expenses.sort_values("Amount (SGD)", ascending=False).copy()
            shown["Amount (SGD)"] = shown["Amount (SGD)"].map(lambda v: f"{v:,.2f}")
            shown["% of total"] = shown["% of total"].map(lambda v: f"{v:.1f}%")
            st.dataframe(
                shown[["Category", "Amount (SGD)", "% of total", "Transactions"]],
                hide_index=True, width="stretch",
                column_config={
                    "Category": st.column_config.TextColumn(width="medium"),
                    "Amount (SGD)": st.column_config.TextColumn(width="small"),
                    "% of total": st.column_config.TextColumn(width="small"),
                    "Transactions": st.column_config.NumberColumn("Txns", format="%d",
                                                                  width="small"),
                },
            )

    if pnl.excluded_count:
        st.info(md(
            f"**Excluded from the statement:** {pnl.excluded_count} transfer(s) totalling "
            f"S${pnl.excluded_total:,.2f} — credit card bill payments, movements between "
            f"your own accounts, and transfers too large to categorise on a guess."
        ))
    for warning in pnl.warnings:
        st.warning(md(warning))


# ---------------------------------------------------------------------------
# Transactions tab, with a filter per column
# ---------------------------------------------------------------------------
def render_transactions(month_key: str):
    month_idx = [i for i, t in enumerate(txns) if t.month == month_key]
    if not month_idx:
        st.info("No transactions this month.")
        return

    month_rows = [txns[i] for i in month_idx]
    st.markdown("##### Transaction compilation")
    st.caption(
        "Chronological across every account and card. Edit **Category**, "
        "**Description**, **Type**, **Amount** or **Date**, then press *Apply edits* "
        "and the income statement updates."
    )

    # Count filters that are already set (session_state holds the previous run's
    # values) so an active filter is visible in the label rather than hidden
    # behind a collapsed expander — a forgotten filter would misread the totals.
    active = 0
    for prefix, empty in (("cat", []), ("acc", []), ("typ", []), ("sec", []),
                          ("q", ""), ("rev", False), ("fx", False)):
        if st.session_state.get(f"{prefix}_{month_key}", empty) != empty:
            active += 1
    if st.session_state.get(f"exc_{month_key}", True) is False:
        active += 1

    label = f"Filters — {active} active" if active else "Filters"
    with st.expander(label, expanded=bool(active)):
        row1 = st.columns([1.1, 1.1, 1.6, 1.6])
        dates = [t.date for t in month_rows if t.date]
        low, high = min(dates), max(dates)
        with row1[0]:
            from_date = st.date_input("Date from", value=low, min_value=low,
                                      max_value=high, key=f"df_{month_key}")
        with row1[1]:
            to_date = st.date_input("Date to", value=high, min_value=low,
                                    max_value=high, key=f"dt_{month_key}")
        with row1[2]:
            categories = st.multiselect(
                "Category", sorted({t.category for t in month_rows}),
                key=f"cat_{month_key}",
            )
        with row1[3]:
            accounts = st.multiselect(
                "Account", sorted({t.source_account for t in month_rows}),
                key=f"acc_{month_key}",
            )

        row2 = st.columns([1.1, 1.1, 1.1, 1.6, 1.6])
        with row2[0]:
            types = st.multiselect("Type", [DEBIT, CREDIT], key=f"typ_{month_key}")
        with row2[1]:
            min_amount = st.number_input("Min amount", value=0.0, step=10.0,
                                         key=f"amin_{month_key}")
        with row2[2]:
            biggest = max(t.amount_sgd for t in month_rows)
            max_amount = st.number_input("Max amount", value=float(round(biggest + 1)),
                                         step=10.0, key=f"amax_{month_key}")
        with row2[3]:
            search = st.text_input("Description or statement text contains",
                                   key=f"q_{month_key}")
        with row2[4]:
            sections = st.multiselect(
                "Section", sorted({t.section for t in month_rows}),
                key=f"sec_{month_key}",
            )

        row3 = st.columns(3)
        with row3[0]:
            only_review = st.checkbox("Only flagged for review",
                                      key=f"rev_{month_key}")
        with row3[1]:
            only_fx = st.checkbox("Only foreign-currency transactions",
                                  key=f"fx_{month_key}")
        with row3[2]:
            show_excluded = st.checkbox(
                "Include excluded transfers", value=True, key=f"exc_{month_key}",
            )

    needle = (search or "").strip().lower()
    kept = []
    for i in month_idx:
        txn = txns[i]
        if txn.date and not (from_date <= txn.date <= to_date):
            continue
        if categories and txn.category not in categories:
            continue
        if accounts and txn.source_account not in accounts:
            continue
        if types and txn.direction not in types:
            continue
        if sections and txn.section not in sections:
            continue
        if not (min_amount <= txn.amount_sgd <= max_amount):
            continue
        if needle and needle not in (txn.description + " " + txn.raw_description).lower():
            continue
        if only_review and not txn.needs_review:
            continue
        if only_fx and txn.original_currency == "SGD":
            continue
        if not show_excluded and txn.section == EXCLUDED:
            continue
        kept.append(i)

    total_out = sum(txns[i].amount_sgd for i in kept if txns[i].direction == DEBIT)
    total_in = sum(txns[i].amount_sgd for i in kept if txns[i].direction == CREDIT)
    st.caption(md(
        f"Showing **{len(kept)}** of {len(month_idx)} transactions · "
        f"money out S${total_out:,.2f} · money in S${total_in:,.2f}"
    ))

    if not kept:
        st.info("No transactions match these filters.")
        return

    editable = pd.DataFrame([
        {
            "_id": i,
            "Date": txns[i].date,
            "Description": txns[i].description,
            "Category": txns[i].category,
            "Type": txns[i].direction,
            "Amount (SGD)": round(txns[i].amount_sgd, 2),
            "Account": txns[i].source_account,
            "Original": ("" if txns[i].original_currency == "SGD"
                         else f"{txns[i].original_currency} "
                              f"{txns[i].original_amount:,.2f}"
                              if txns[i].original_amount else txns[i].original_currency),
            "⚑": ("⚠️" if txns[i].needs_review else "") +
                 ("📅" if txns[i].date_is_inferred else ""),
            "Raw statement text": txns[i].raw_description,
        }
        for i in kept
    ])

    edited = st.data_editor(
        editable,
        hide_index=True,
        width="stretch",
        height=520,
        column_config={
            "_id": None,
            "Date": st.column_config.DateColumn("Date", format="DD MMM YYYY",
                                                width="small"),
            "Description": st.column_config.TextColumn(
                "Description (≤10 words)", width="medium",
                help="Auto-summarised from the statement text. Editable.",
            ),
            "Category": st.column_config.SelectboxColumn(
                "Category", options=ASSIGNABLE_CATEGORIES, width="medium", required=True,
            ),
            "Type": st.column_config.SelectboxColumn(
                "Type", options=[DEBIT, CREDIT], width="small", required=True,
            ),
            "Amount (SGD)": st.column_config.NumberColumn(
                "Amount (SGD)", format="%.2f", width="small",
            ),
            "Account": st.column_config.TextColumn("Account", width="small",
                                                   disabled=True),
            "Original": st.column_config.TextColumn("Original", width="small",
                                                    disabled=True),
            "⚑": st.column_config.TextColumn("⚑", width="small", disabled=True),
            "Raw statement text": st.column_config.TextColumn(
                "Raw statement text", width="large", disabled=True,
            ),
        },
        key=f"editor_{month_key}",
    )

    left, right = st.columns([2, 1])
    with left:
        remember = st.checkbox(
            "Remember my category fixes for these merchants next month", value=True,
            help=f"Saves to {os.path.relpath(OVERRIDES_PATH, BASE_DIR)}.",
            key=f"remember_{month_key}",
        )
    with right:
        apply_clicked = st.button("Apply edits", type="primary",
                                 key=f"apply_{month_key}", width="stretch")

    if apply_clicked:
        from finance.ingest import apply_override
        from finance.rules import _load_overrides

        overrides = _load_overrides(OVERRIDES_PATH)
        changed = 0
        for _, record in edited.iterrows():
            idx = int(record["_id"])
            txn = txns[idx]
            new_category = str(record["Category"])
            new_description = str(record["Description"])
            new_type = str(record["Type"])
            new_amount = float(record["Amount (SGD)"])
            new_date = record["Date"]

            if new_category != txn.category:
                if remember:
                    apply_override(overrides, txn.raw_description, new_category)
                txn.category = new_category
                txn.needs_review = False
                txn.review_note = ""
                changed += 1
            if new_description != txn.description:
                txn.description = " ".join(new_description.split()[:10])
                changed += 1
            if new_type != txn.direction:
                txn.direction = new_type
                changed += 1
            if abs(new_amount - txn.amount_sgd) > 0.005:
                txn.amount_sgd = round(abs(new_amount), 2)
                changed += 1
            if isinstance(new_date, (date, pd.Timestamp)):
                coerced = new_date.date() if isinstance(new_date, pd.Timestamp) else new_date
                if coerced != txn.date:
                    txn.date = coerced
                    txn.date_is_inferred = False
                    changed += 1

        if remember and overrides:
            save_overrides(OVERRIDES_PATH, overrides)
        st.session_state.txns = txns
        if changed:
            st.success(f"Applied {changed} change(s).")
        else:
            st.info("No changes.")
        st.rerun()


def render_review(month_key: str):
    st.markdown("##### Transactions needing review")
    st.caption(
        "These are already counted in the income statement — this list shows where "
        "the automatic categorisation was a guess. Fix them in the Transactions "
        "tab, and the fix can be remembered for next month."
    )
    review = review_frame(txns, month_key)
    if review.empty:
        st.success("Nothing flagged for this month.")
        return

    total = review["Amount (SGD)"].sum()
    st.caption(md(f"**{len(review)}** transaction(s), S${total:,.2f} in total."))
    st.dataframe(
        review, hide_index=True, width="stretch", height=460,
        column_config={
            "Date": st.column_config.DateColumn(format="DD MMM YYYY", width="small"),
            "Amount (SGD)": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Why flagged": st.column_config.TextColumn(width="large"),
            "Raw Statement Text": st.column_config.TextColumn(width="large"),
        },
    )


# ---------------------------------------------------------------------------
# One tab per month, plus overview tabs
# ---------------------------------------------------------------------------
def _strip_label(option: str) -> str:
    """Month keys render as 'May 2026'; the overview entries pass through."""
    return month_short(option) if option in months else option


OVERVIEW = "Overview"
PARSING_LOG = "Parsing log"
EXPORT = "Export"

# The overview leads and is the landing page; months follow in order.
STRIP_OPTIONS = [OVERVIEW] + months + [PARSING_LOG, EXPORT]

# The month strip is a radio group dressed as a tab bar, not st.tabs: opening a
# dialog remounts a tab strip and would bounce you back to the first entry every
# time you drilled into a line item. A radio keeps its position across reruns.
month_choice = st.radio(
    "View", STRIP_OPTIONS, horizontal=True,
    index=0, format_func=_strip_label,
    key="month_strip", label_visibility="collapsed",
)

if month_choice in months:
    month_key = month_choice
    pnl = build_pnl(txns, month_key, *PNL_ARGS)
    review_count = int(review_frame(txns, month_key).shape[0])

    st.subheader(month_label(month_key))
    metrics = st.columns(5)
    metrics[0].metric("Total Revenues", f"S${pnl.total_revenue:,.2f}")
    metrics[1].metric("Fixed Expenses", f"S${pnl.total_fixed:,.2f}")
    metrics[2].metric("Variable Expenses", f"S${pnl.total_variable:,.2f}")
    metrics[3].metric("Total Expenses", f"S${pnl.total_expenses:,.2f}")
    metrics[4].metric(
        "Net Income", f"S${pnl.net_income:,.2f}",
        delta=(f"{pnl.savings_rate:,.1f}% of revenue"
               if pnl.savings_rate is not None else None),
    )

    sub = st.tabs([
        "Income Statement",
        f"Transactions ({sum(1 for t in txns if t.month == month_key)})",
        f"⚠ Review ({review_count})",
    ])
    with sub[0]:
        render_income_statement(month_key, pnl)
    with sub[1]:
        render_transactions(month_key)
    with sub[2]:
        render_review(month_key)

    # A drill-down requested above is opened here, outside the sub-tabs.
    pending = st.session_state.drill_shown.pop("pending", None)
    if pending:
        drill_month, drill_index = pending
        drill_pnl = build_pnl(txns, drill_month, *PNL_ARGS)
        if 0 <= drill_index < len(drill_pnl.lines):
            drill_line = drill_pnl.lines[drill_index]
            show_line_detail(drill_month, drill_line,
                             line_transactions(txns, drill_month, drill_line))


# --- Annual overview: the landing page -------------------------------------
elif month_choice == OVERVIEW:
    summary = annual_summary(txns, *PNL_ARGS)
    trend = monthly_trend(txns, *PNL_ARGS)

    st.subheader("Annual overview")
    st.caption(md(
        f"{summary.span} · {summary.month_count} month(s) · "
        f"{summary.transaction_count} transactions across "
        f"{len({t.source_account for t in txns})} accounts and cards"
    ))

    metrics = st.columns(5)
    metrics[0].metric("Total Revenues", f"S${summary.total_revenue:,.0f}")
    metrics[1].metric("Total Expenses", f"S${summary.total_expenses:,.0f}")
    metrics[2].metric(
        "Net Income", f"S${summary.net_income:,.0f}",
        delta=(f"{summary.savings_rate:,.1f}% saved"
               if summary.savings_rate is not None else None),
    )
    metrics[3].metric("Avg Monthly Spend", f"S${summary.avg_monthly_expenses:,.0f}")
    metrics[4].metric("Avg Monthly Net", f"S${summary.avg_monthly_net:,.0f}")

    st.divider()

    # --- The dot plot ------------------------------------------------------
    st.markdown("##### Spending by category, month on month")
    st.caption(
        "Amounts in SGD. One dot per month, joined so you can read the direction "
        "of travel. Categories are ordered by total spend."
    )
    dots = category_by_month(txns)
    if dots.empty:
        st.info("No categorised spending yet.")
    else:
        order = (dots.groupby("Category")["Amount"].sum()
                 .sort_values(ascending=False).index.tolist())
        month_order = [month_short(m) for m in months]
        month_colours = _month_ramp(len(month_order))

        base = alt.Chart(dots).transform_calculate(
            AmountLabel="format(datum.Amount, ',.2f')"
        )
        # A zero rule, so a negative category (a refund with no matching spend)
        # is legible as such rather than just "left of the others".
        zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
            color="#3A4048", strokeWidth=1,
        ).encode(x="x:Q")
        # The connecting line is the point of the chart: it turns twelve
        # separate readings into one trajectory per category.
        line = base.mark_line(
            color="#3A4048", strokeWidth=1.4, point=False,
        ).encode(
            y=alt.Y("Category:N", sort=order, title=None,
                    axis=alt.Axis(labelLimit=200, labelFontSize=12,
                                  domain=False, ticks=False)),
            x=alt.X("Amount:Q", title=None,
                    axis=alt.Axis(format=",.0f", grid=True, gridColor="#1B1E24",
                                  domain=False, ticks=False)),
            detail="Category:N",
        )
        points = base.mark_point(filled=True, size=115, opacity=1).encode(
            y=alt.Y("Category:N", sort=order, title=None),
            x="Amount:Q",
            color=alt.Color(
                "MonthLabel:N", sort=month_order, title="Month",
                scale=alt.Scale(domain=month_order, range=month_colours),
                legend=alt.Legend(orient="top", direction="horizontal",
                                  titleFontSize=11, labelFontSize=11),
            ),
            tooltip=[
                alt.Tooltip("Category:N"),
                alt.Tooltip("MonthLabel:N", title="Month"),
                alt.Tooltip("AmountLabel:N", title="Amount (SGD)"),
                alt.Tooltip("Transactions:Q"),
                alt.Tooltip("Section:N"),
            ],
        )
        st.altair_chart(
            (zero + line + points).properties(
                height=32 * len(order) + 60,
                padding={"left": 12, "right": 8, "top": 4, "bottom": 4},
            )
                           .configure_view(strokeWidth=0)
                           .configure_axis(labelColor="#9AA4B2",
                                           titleColor="#9AA4B2")
                           .configure_legend(labelColor="#C6CBD3",
                                             titleColor="#9AA4B2"),
            use_container_width=True,
        )

    st.divider()

    # --- Revenue / expense / net trajectory --------------------------------
    left, right = st.columns([3, 2])
    with left:
        st.markdown("##### Revenues, expenses and net income")
        st.caption("Amounts in SGD.")
        if len(trend) <= 1:
            st.caption("Load more than one month to see a trajectory.")
        shaped = trend.melt(
            id_vars="Month",
            value_vars=["Total Revenues", "Total Expenses", "Net Income"],
            var_name="Measure", value_name="Amount",
        )
        month_labels = list(trend["Month"])
        # One mark, not a line layer plus a point layer: a layered chart reserves
        # no left gutter under Streamlit's autosize, so "15,000" gets drawn at a
        # negative x and vanishes off the canvas. `point=` on mark_line gives the
        # same connected dots from a single, correctly measured mark.
        flow = alt.Chart(shaped).transform_calculate(
            AmountLabel="format(datum.Amount, ',.2f')"
        ).mark_line(
            strokeWidth=2,
            point=alt.OverlayMarkDef(filled=True, size=90),
        ).encode(
            x=alt.X("Month:N", sort=month_labels, title=None,
                    axis=alt.Axis(labelAngle=0, domain=False, ticks=False)),
            y=alt.Y("Amount:Q", title=None,
                    axis=alt.Axis(format="~s", grid=True, gridColor="#1B1E24",
                                  domain=False, ticks=False, labelPadding=6)),
            color=alt.Color("Measure:N", title=None,
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Measure:N"),
                     alt.Tooltip("AmountLabel:N", title="Amount (SGD)")],
        )
        st.altair_chart(
            flow.properties(height=300)
                .configure_view(strokeWidth=0)
                .configure_axis(labelColor="#9AA4B2", titleColor="#9AA4B2")
                .configure_legend(labelColor="#C6CBD3"),
            use_container_width=True,
        )

    with right:
        st.markdown("##### Fixed vs variable")
        split = trend.melt(
            id_vars="Month", value_vars=["Fixed Expenses", "Variable Expenses"],
            var_name="Kind", value_name="Amount",
        )
        st.altair_chart(
            alt.Chart(split).mark_bar().encode(
                x=alt.X("Month:N", sort=list(trend["Month"]), title=None,
                        axis=alt.Axis(labelAngle=0, domain=False, ticks=False)),
                y=alt.Y("Amount:Q", title=None, stack="zero",
                        axis=alt.Axis(format="~s", grid=True, gridColor="#1B1E24",
                                      domain=False, ticks=False, labelPadding=6)),
                color=alt.Color("Kind:N", title=None,
                                legend=alt.Legend(orient="top")),
                tooltip=["Month", "Kind", alt.Tooltip("Amount:Q", format=",.2f")],
            ).properties(height=300)
             .configure_view(strokeWidth=0)
             .configure_axis(labelColor="#9AA4B2", titleColor="#9AA4B2")
             .configure_legend(labelColor="#C6CBD3"),
            use_container_width=True,
        )

    st.divider()
    st.markdown("##### Month by month")
    shown = trend.copy()
    for column in ("Total Revenues", "Fixed Expenses", "Variable Expenses",
                   "Total Expenses", "Net Income"):
        shown[column] = shown[column].map(lambda v: f"{v:,.2f}")
    shown["Savings Rate"] = trend["Savings Rate"].map(
        lambda v: "" if pd.isna(v) else f"{v:.1f}%"
    )
    st.dataframe(shown, hide_index=True, width="stretch")

    notes = []
    if summary.review_count:
        notes.append(
            f"**{summary.review_count}** transaction(s) still need review — open a "
            f"month and check its ⚠ Review tab."
        )
    if summary.excluded_total:
        notes.append(
            f"**S${summary.excluded_total:,.2f}** of transfers sits outside these "
            f"totals: card bill payments, movements between your own accounts, and "
            f"transfers too large to categorise on a guess."
        )
    if summary.cpf_employee:
        notes.append(
            f"CPF included in revenue: **S${summary.cpf_employee:,.2f}** employee "
            f"share" + (f", plus S${summary.cpf_employer:,.2f} employer share"
                        if include_employer_cpf else
                        f" (employer's S${summary.cpf_employer:,.2f} not counted)")
            + "."
        )
    for note in notes:
        st.caption(md(note))

# --- Parsing log -----------------------------------------------------------
elif month_choice == PARSING_LOG:
    st.subheader("What each file produced")
    for doc in docs:
        with st.expander(
            f"{doc.filename} — {doc.doc_type}, account “{doc.account}”, "
            f"{len(doc.transactions)} transactions",
            expanded=not doc.transactions,
        ):
            if doc.statement_month:
                st.write(f"Statement month detected: **{month_label(doc.statement_month)}**")
            for note in doc.notes:
                st.caption(note)
            for warning in doc.warnings:
                st.warning(warning)
            if doc.skipped_lines:
                st.write(f"**Lines not recognised as transactions ({len(doc.skipped_lines)})**")
                st.code("\n".join(doc.skipped_lines[:80]))
                st.caption(
                    "Statement furniture (totals, footers, marketing) is expected here. "
                    "If you spot a real transaction, add it by hand in the exported "
                    "workbook."
                )
            if doc.transactions:
                st.write("**Rule that matched each transaction**")
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Date": t.date,
                            "Description": t.description,
                            "Category": t.category,
                            "Rule": t.rule_matched or "(fallback)",
                            "Amount": round(t.amount_sgd, 2),
                        }
                        for t in doc.transactions
                    ]),
                    hide_index=True, width="stretch", height=260,
                )

# --- Export ----------------------------------------------------------------
elif month_choice == EXPORT:
    st.subheader("Export to Excel")
    st.caption(
        "One workbook: a Summary sheet, then a Transactions sheet and an Income "
        "Statement sheet for every month you pick, plus a Review sheet."
    )
    chosen = st.multiselect(
        "Months to include", months, default=months, format_func=month_label,
    )
    if chosen:
        workbook = build_workbook(txns, sorted(chosen), *PNL_ARGS)
        label = (month_label(chosen[0]).replace(" ", "-") if len(chosen) == 1
                 else f"{len(chosen)}-months")
        st.download_button(
            "⬇️  Download workbook (.xlsx)",
            data=workbook,
            file_name=f"personal-finances-{label}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        for month_key in chosen:
            st.download_button(
                f"⬇️  {month_label(month_key)} transactions (.csv)",
                data=compilation_frame(txns, month_key).to_csv(index=False).encode(),
                file_name=f"transactions-{month_label(month_key).replace(' ', '-')}.csv",
                mime="text/csv",
                key=f"csv_{month_key}",
            )
    else:
        st.info("Pick at least one month.")
