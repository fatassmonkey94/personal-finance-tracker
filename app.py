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
    MONTH_LABELS,
    annual_summary,
    available_months,
    build_pnl,
    category_breakdown,
    category_by_month,
    compilation_frame,
    expense_breakdown,
    income_breakdown,
    line_transactions,
    month_label,
    month_short,
    monthly_trend,
    months_in_year,
    pnl_display_frame,
    review_frame,
    savings_split,
    trendlines,
    years_with_months,
    ytd_series,
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

      /* Header: the app's name, and the one green control beside it. */
      .app-title {
          font-size: 1.62rem; font-weight: 600; letter-spacing: -0.022em;
          line-height: 1.15;
      }
      .app-sub { color: var(--muted); font-size: 0.82rem; margin-top: 0.25rem; }

      /* The intake button is the only green on the page, so it reads as the
         one thing that changes what the app knows. */
      .st-key-open_intake button {
          background: #1FA95F !important;
          border: 1px solid #1FA95F !important;
          color: #04120B !important;
          font-weight: 600;
          margin-top: 0.35rem;
      }
      .st-key-open_intake button:hover {
          background: #24C06D !important; border-color: #24C06D !important;
      }
      .st-key-open_intake button p { color: #04120B !important; }

      /* Sidebar navigation: a year expands to its months. */
      .nav-brand {
          font-size: 1.02rem; font-weight: 600; line-height: 1.25;
          letter-spacing: -0.015em; padding: 0.1rem 0 0.9rem;
      }
      .nav-heading {
          font-size: 0.66rem; letter-spacing: 0.11em; text-transform: uppercase;
          color: var(--muted); margin: 1.1rem 0 0.4rem;
      }
      section[data-testid="stSidebar"] div[data-testid="stExpander"] details {
          border: none; border-bottom: 1px solid var(--hairline);
      }
      section[data-testid="stSidebar"] div[data-testid="stExpander"] summary {
          font-weight: 600; letter-spacing: 0.02em;
      }
      section[data-testid="stSidebar"] button {
          justify-content: flex-start !important;
          text-align: left; font-size: 0.86rem;
      }
      section[data-testid="stSidebar"] button p { text-align: left; }

      /* Pie headings: the figure leads, the label sits above it quietly. */
      .pie-title {
          font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase;
          color: var(--muted);
      }
      .pie-total {
          font-size: 1.55rem; font-weight: 600; letter-spacing: -0.02em;
          font-variant-numeric: tabular-nums; line-height: 1.3;
      }
      .pie-sub { font-size: 0.74rem; color: var(--muted); margin-bottom: 0.2rem; }

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

      /* Review sub-tab - a muted red wash, the dark-theme reading of pastel.
         Scoped to the month sub-tabs: an unscoped nth-of-type would tint the
         third tab of every tab group, the intake dialog's included. */
      .st-key-month_subtabs div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3) {
          background-color: var(--warn-bg);
      }
      .st-key-month_subtabs div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3) p {
          color: var(--warn-fg) !important;
          font-weight: 600;
      }
      .st-key-month_subtabs div[data-baseweb="tab-list"]
        button[data-baseweb="tab"]:nth-of-type(3):hover {
          background-color: #332024;
      }
      .st-key-month_subtabs div[data-baseweb="tab-list"]
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
# Settings live in session state, not in widgets on the page.
#
# They are edited in the header's intake dialog, which only renders its widgets
# while it is open — so the values have to survive independently of it. Keyed
# widgets write straight into session state, and every computation reads from
# there.
# ---------------------------------------------------------------------------
SALARY_BASIS_NET_LABEL = "Take-home pay, after my CPF deduction"
SALARY_BASIS_GROSS_LABEL = "Already the gross figure"

SETTING_DEFAULTS = {
    "cpf_status": cpf.STATUSES[0],
    "cpf_age_band": cpf.AGE_BANDS[0],
    "salary_basis_label": SALARY_BASIS_NET_LABEL,
    "include_employer_cpf": False,
    "employer_text": "",
    "parents_text": "\n".join(load_parent_names()),
    "transfer_threshold": 500.0,
    "pdf_password": "",
    "fallback_month": "",
    "folder_path": os.environ.get("PFT_STATEMENTS", ""),
}
for _key, _default in SETTING_DEFAULTS.items():
    st.session_state.setdefault(_key, _default)

cpf_status = st.session_state["cpf_status"]
cpf_age_band = st.session_state["cpf_age_band"]
salary_basis = (BASIS_NET
                if st.session_state["salary_basis_label"] == SALARY_BASIS_NET_LABEL
                else BASIS_GROSS)
include_employer_cpf = st.session_state["include_employer_cpf"]
transfer_threshold = st.session_state["transfer_threshold"]
pdf_password = st.session_state["pdf_password"]
fallback_month = st.session_state["fallback_month"]

employer_keywords = [e.strip() for e in st.session_state["employer_text"].split(",")
                     if e.strip()]
parent_names = [p.strip() for p in st.session_state["parents_text"].splitlines()
                if p.strip()]
if parent_names != load_parent_names():
    save_parent_names(parent_names)

PNL_ARGS = (salary_basis, cpf_status, cpf_age_band, include_employer_cpf)


# ---------------------------------------------------------------------------
# Header: the app's name, and one green control that opens everything you feed
# it — statements and the settings that govern how they are read.
# ---------------------------------------------------------------------------
title_col, action_col = st.columns([4, 1])
with title_col:
    st.markdown(
        '<div class="app-title">Your Personal Finance Tracker</div>'
        '<div class="app-sub">Statements in, income statement out. '
        'Everything is processed locally on this machine.</div>',
        unsafe_allow_html=True,
    )
with action_col:
    intake_clicked = st.button(
        "Add statements", key="open_intake", width="stretch",
        help="Drop in statement files and set how they should be read.",
    )

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


@st.dialog("Add statements & settings", width="large")
def intake_dialog():
    """Everything the app needs fed to it, in one place off the main page."""
    tab_files, tab_cpf, tab_rules = st.tabs(
        ["Statements", "CPF", "Categorisation"])

    with tab_files:
        uploads = st.file_uploader(
            "Drop statement files here",
            type=["csv", "tsv", "txt", "xlsx", "xlsm", "xls", "pdf"],
            accept_multiple_files=True,
            key="intake_uploads",
            help="CSV and Excel need description, date, amount and currency. "
                 "PDF card statements need description and amount; dates are "
                 "read when present.",
        )
        if uploads:
            st.caption(f"{len(uploads)} file(s) ready: "
                       + ", ".join(f.name for f in uploads))
        if st.button("Process these files", type="primary",
                     disabled=not uploads, width="stretch"):
            (st.session_state.txns, st.session_state.docs,
             st.session_state.notes) = _process(
                [(f.name, f.getvalue()) for f in uploads])
            st.rerun()

        st.divider()
        st.caption("Or read them straight off this machine — handy month to "
                   "month, so you are not picking files by hand each time.")
        st.text_input("Folder or file paths", key="folder_path",
                      placeholder="~/Downloads/statements")
        if st.button("Read from this path", width="stretch"):
            files, problems = _collect_from_path(st.session_state["folder_path"])
            for problem in problems:
                st.warning(problem)
            if files:
                (st.session_state.txns, st.session_state.docs,
                 st.session_state.notes) = _process(files)
                st.rerun()
            else:
                st.error("Nothing readable at that path.")

        st.divider()
        st.caption("PDF handling")
        st.text_input("PDF password (if statements are locked)", type="password",
                      key="pdf_password",
                      help="Used only in memory to open the PDF; never written "
                           "to disk.")
        st.text_input("Fallback month for dateless PDFs (YYYY-MM)",
                      key="fallback_month",
                      help="Only used when a PDF has no statement period and no "
                           "line dates.")

    with tab_cpf:
        st.caption("CPF follows CPF Board's published rates.")
        st.selectbox("Residency status", cpf.STATUSES, key="cpf_status",
                     help="Singapore Citizens and Permanent Residents from their "
                          "3rd year use CPF Board's Table 1 — the default.")
        st.selectbox("Age band", cpf.AGE_BANDS, key="cpf_age_band",
                     help="Contribution rates step down with age. 55 and below "
                          "pays the full 20% employee share.")
        st.radio(
            "The salary in my bank statement is…",
            [SALARY_BASIS_NET_LABEL, SALARY_BASIS_GROSS_LABEL],
            key="salary_basis_label",
            help="A Singapore salary credit is normally net of your own CPF "
                 "share. On that basis the gross is worked back from it, so "
                 "Salary + CPF equals true gross pay.",
        )
        st.checkbox("Also count the employer's CPF share as revenue",
                    key="include_employer_cpf",
                    help="Off by default: your brief asked for the 20% employee "
                         "contribution. Switch on to show total cost of "
                         "employment.")
        st.caption(md(
            f"Ordinary Wage ceiling: S${cpf.ow_ceiling_for(date.today()):,.0f}"
            f"/month · annual salary ceiling S${cpf.ANNUAL_SALARY_CEILING:,.0f}"
        ))

    with tab_rules:
        st.text_input("Employer name(s) on your salary credit",
                      key="employer_text",
                      help="Optional. Comma-separated. Helps catch salary "
                           "credits that don't say 'SALARY'.")
        st.text_area("Names that mean 'allowance to parents'", height=90,
                     key="parents_text",
                     help="One per line. Kept in data/parent_names.txt, which is "
                          "gitignored — real names never reach the repository.")
        st.number_input("Hold transfers above (SGD) for review",
                        min_value=0.0, step=50.0, key="transfer_threshold",
                        help="Transfers with no recognisable merchant are booked "
                             "to Food & Dining (out) or Additional Income (in). "
                             "Above this amount that guess is held back instead. "
                             "Set 0 to switch this off.")
        if os.path.exists(OVERRIDES_PATH):
            st.divider()
            st.caption(f"Learned category fixes: "
                       f"`{os.path.relpath(OVERRIDES_PATH, BASE_DIR)}`")
            if st.button("Forget learned fixes", width="stretch"):
                os.remove(OVERRIDES_PATH)
                st.success("Cleared. Re-parse to apply.")


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

if intake_clicked:
    intake_dialog()

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
    st.markdown("")
    st.info("Nothing loaded yet — open **Add statements** above to begin.")
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
# ---------------------------------------------------------------------------
# Navigation: a year in the sidebar expands to its months.
#
# Streamlit has no tree widget, so each year is an expander holding buttons.
# The chosen view lives in session state rather than in a widget's own value,
# so opening a dialog cannot reset it.
# ---------------------------------------------------------------------------
YEAR_VIEW, MONTH_VIEW, LOG_VIEW, EXPORT_VIEW = "year", "month", "log", "export"

tree = years_with_months(txns)
default_year = next(iter(tree))

if "view" not in st.session_state:
    st.session_state.view = (YEAR_VIEW, default_year)
# A reload with different statements can strand a view on a month that is gone.
if (st.session_state.view[0] == MONTH_VIEW
        and st.session_state.view[1] not in months):
    st.session_state.view = (YEAR_VIEW, default_year)
if st.session_state.view[0] == YEAR_VIEW and st.session_state.view[1] not in tree:
    st.session_state.view = (YEAR_VIEW, default_year)

view_kind, view_key = st.session_state.view


def go(kind: str, key):
    st.session_state.view = (kind, key)


with st.sidebar:
    st.markdown('<div class="nav-brand">Your Personal<br>Finance Tracker</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="nav-heading">Periods</div>', unsafe_allow_html=True)

    for year, year_months in tree.items():
        showing_this_year = (
            (view_kind == YEAR_VIEW and view_key == year)
            or (view_kind == MONTH_VIEW and view_key.startswith(f"{year}-"))
        )
        with st.expander(year, expanded=showing_this_year):
            st.button(
                f"{year} dashboard", key=f"nav-year-{year}", width="stretch",
                type=("primary" if (view_kind == YEAR_VIEW and view_key == year)
                      else "tertiary"),
                on_click=go, args=(YEAR_VIEW, year),
            )
            for month_key in year_months:
                flagged = int(review_frame(txns, month_key).shape[0])
                label = MONTH_LABELS[int(month_key.split("-")[1]) - 1]
                st.button(
                    f"{label}" + (f"  ·  {flagged} to review" if flagged else ""),
                    key=f"nav-month-{month_key}", width="stretch",
                    type=("primary" if (view_kind == MONTH_VIEW
                                        and view_key == month_key)
                          else "tertiary"),
                    on_click=go, args=(MONTH_VIEW, month_key),
                )

    st.markdown('<div class="nav-heading">Tools</div>', unsafe_allow_html=True)
    st.button("Parsing log", key="nav-log", width="stretch",
              type=("primary" if view_kind == LOG_VIEW else "tertiary"),
              on_click=go, args=(LOG_VIEW, None))
    st.button("Export", key="nav-export", width="stretch",
              type=("primary" if view_kind == EXPORT_VIEW else "tertiary"),
              on_click=go, args=(EXPORT_VIEW, None))


month_choice = view_key if view_kind == MONTH_VIEW else None

if view_kind == MONTH_VIEW:

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

    with st.container(key="month_subtabs"):
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
elif view_kind == YEAR_VIEW:
    year = view_key
    year_months = months_in_year(txns, year)
    summary = annual_summary(
        [t for t in txns if t.month in year_months], *PNL_ARGS)

    st.subheader(f"{year} dashboard")
    st.caption(md(
        f"{summary.span} · {summary.month_count} month(s) · "
        f"{sum(1 for t in txns if t.month in year_months)} transactions"
    ))

    # --- The three pies -----------------------------------------------------
    income = income_breakdown(txns, year_months, *PNL_ARGS)
    expenses = expense_breakdown(txns, year_months)
    savings = savings_split(txns, year_months, *PNL_ARGS)

    def donut(frame, label_field, colours, total, title, subtitle):
        st.markdown(f'<div class="pie-title">{title}</div>'
                    f'<div class="pie-total">S${total:,.0f}</div>'
                    f'<div class="pie-sub">{subtitle}</div>',
                    unsafe_allow_html=True)
        if frame.empty:
            st.caption("Nothing to show for this year.")
            return
        chart = alt.Chart(frame).transform_calculate(
            AmountLabel="format(datum.Amount, ',.2f')"
        ).mark_arc(innerRadius=32, outerRadius=104, stroke="#0B0C0E",
                   strokeWidth=2).encode(
            theta=alt.Theta("Amount:Q", stack=True),
            color=alt.Color(
                f"{label_field}:N", title=None,
                sort=list(frame[label_field]),
                scale=alt.Scale(domain=list(frame[label_field]), range=colours),
                legend=alt.Legend(orient="bottom", columns=1, symbolType="square",
                                  labelFontSize=11, labelLimit=180),
            ),
            order=alt.Order("Amount:Q", sort="descending"),
            tooltip=[alt.Tooltip(f"{label_field}:N", title=title),
                     alt.Tooltip("AmountLabel:N", title="Amount (SGD)")],
        )
        # The height Streamlit passes is the whole block, legend included, and
        # Vega does not count arc marks when it lays the view out — so a height
        # that only covers the legend leaves the ring clipped at the top and
        # drawn over the legend beneath (measured: the twelve-entry Expenses
        # legend overlapped its own pie by 48px). Reserve the ring's 208px plus
        # a measured 22px per legend row. Per-chart rather than one shared
        # height, so the plotting area is identical across the three and the
        # rings line up as a row while each legend runs as long as it needs.
        st.altair_chart(
            chart.properties(height=2 * 104 + 56 + 22 * len(frame))
                 .configure_view(strokeWidth=0)
                 .configure_legend(labelColor="#C6CBD3"),
            use_container_width=True,
        )

    # Income is coloured by what the money *is*, not by how big the slice is, so
    # the wedges keep their meaning as sources come and go: green is cash that
    # reached your bank, the blues are CPF (yours, but not spendable this month),
    # amber is everything that is not salary. Keying by name rather than position
    # matters because a source with no amount drops out of the frame entirely —
    # a positional range would slide amber onto CPF in a month with no interest.
    INCOME_TONES = {
        "Salary credited": "#3FBF7F",
        "CPF — employee share": "#4E9DD6",
        "CPF — employer share": "#7C74D9",
        "Additional income": "#E0A93F",
    }
    INCOME_FALLBACK = "#5C6470"

    def income_colours(frame):
        return [INCOME_TONES.get(source, INCOME_FALLBACK)
                for source in frame["Source"]]

    # Cool tones for fixed commitments, warm for discretionary spending, so the
    # split the brief asks about reads off the wheel without a second legend.
    FIXED_TONES = ["#8AB4F8", "#6E8FD6", "#5C73B8", "#4A5C99", "#3B4A7D"]
    VARIABLE_TONES = ["#F2A26B", "#E4757B", "#D9628F", "#C97FD0", "#E0A64F",
                      "#CF8A5C", "#B9707E", "#A8628F"]

    def expense_colours(frame):
        cool = iter(FIXED_TONES * 3)
        warm = iter(VARIABLE_TONES * 3)
        return [next(cool) if section == "Fixed" else next(warm)
                for section in frame["Section"]]

    pie_cols = st.columns(3, gap="large")
    with pie_cols[0]:
        donut(income, "Source", income_colours(income),
              summary.total_revenue, "Income",
              "Revenue by source, CPF included")
    with pie_cols[1]:
        fixed_total = sum(expenses.loc[expenses["Section"] == "Fixed", "Amount"]) \
            if not expenses.empty else 0.0
        variable_total = sum(expenses.loc[expenses["Section"] == "Variable", "Amount"]) \
            if not expenses.empty else 0.0
        donut(expenses, "Category", expense_colours(expenses) if not expenses.empty else [],
              summary.total_expenses, "Expenses",
              f"Fixed S${fixed_total:,.0f} (cool) · Variable "
              f"S${variable_total:,.0f} (warm)")
    with pie_cols[2]:
        rate = summary.savings_rate
        donut(savings, "Part", ["#7DD3C0", "#39404A"],
              summary.net_income, "Savings",
              (f"{rate:,.1f}% of revenue kept" if rate is not None
               else "No revenue recorded"))

    negatives = (expenses[expenses["Amount"] < 0] if not expenses.empty
                 else expenses)
    if not negatives.empty:
        st.caption(md(
            "Not on the Expenses pie, because a wedge cannot be negative: "
            + ", ".join(f"{r.Category} S${r.Amount:,.2f}"
                        for r in negatives.itertuples())
            + " — a refund with no matching spend this year."
        ))

    st.divider()

    # --- Year-to-date dot plot with trendlines ------------------------------
    st.markdown("##### Year to date, month on month")
    st.caption(
        "Amounts in SGD. A dot per month for each measure, with a dashed "
        "least-squares trendline through it. Months with no statements loaded "
        "are left out rather than drawn as zero."
    )
    series = ytd_series(txns, year_months, *PNL_ARGS)
    if series.empty:
        st.info("No months loaded for this year.")
    else:
        order = [month_short(m) for m in year_months]
        measures = ["Income", "Expenses", "Savings"]
        measure_colours = ["#7DD3C0", "#E4757B", "#8AB4F8"]
        colour_scale = alt.Scale(domain=measures, range=measure_colours)

        x_axis = alt.X("MonthLabel:N", sort=order, title=None,
                       axis=alt.Axis(labelAngle=0, domain=False, ticks=False))
        y_axis = alt.Y("Amount:Q", title=None,
                       axis=alt.Axis(format="~s", grid=True, gridColor="#1B1E24",
                                     domain=False, ticks=False, labelPadding=6))

        offset = alt.XOffset("Measure:N", sort=measures)

        dots = alt.Chart(series).transform_calculate(
            AmountLabel="format(datum.Amount, ',.2f')"
        ).mark_point(filled=True, size=170, opacity=1,
                     stroke="#0B0C0E", strokeWidth=1.5).encode(
            x=x_axis, y=y_axis, xOffset=offset,
            color=alt.Color("Measure:N", title=None, scale=colour_scale,
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("MonthLabel:N", title="Month"),
                     alt.Tooltip("Measure:N"),
                     alt.Tooltip("AmountLabel:N", title="Amount (SGD)")],
        )

        fits = trendlines(series)
        layers = [alt.Chart(series).mark_rule(color="#2A2F38", strokeWidth=1)
                  .encode(y=alt.datum(0))]
        if not fits.empty:
            layers.append(
                alt.Chart(fits).mark_line(strokeDash=[6, 4], strokeWidth=1.6,
                                          opacity=0.85).encode(
                    x=alt.X("MonthLabel:N", sort=order, title=None),
                    y=alt.Y("Fit:Q", title=None),
                    xOffset=offset,
                    color=alt.Color("Measure:N", title=None, scale=colour_scale),
                )
            )
        layers.append(dots)

        st.altair_chart(
            alt.layer(*layers).properties(height=380)
               .configure_view(strokeWidth=0)
               .configure_axis(labelColor="#9AA4B2", titleColor="#9AA4B2")
               .configure_legend(labelColor="#C6CBD3"),
            use_container_width=True,
        )
        if len(year_months) < 2:
            st.caption("One month loaded, so there is no trend to fit yet.")

    # --- Everything the annual view carried before, kept but out of the way --
    with st.expander("More annual detail", expanded=False):
        trend = monthly_trend([t for t in txns if t.month in year_months], *PNL_ARGS)
        st.markdown("##### Spending by category, month on month")
        dots_frame = category_by_month(txns, year_months)
        if dots_frame.empty:
            st.info("No categorised spending yet.")
        else:
            cat_order = (dots_frame.groupby("Category")["Amount"].sum()
                         .sort_values(ascending=False).index.tolist())
            month_order = [month_short(m) for m in year_months]
            month_colours = _month_ramp(len(month_order))
            base = alt.Chart(dots_frame).transform_calculate(
                AmountLabel="format(datum.Amount, ',.2f')"
            )
            zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
                color="#3A4048", strokeWidth=1).encode(x="x:Q")
            line = base.mark_line(color="#3A4048", strokeWidth=1.4).encode(
                y=alt.Y("Category:N", sort=cat_order, title=None,
                        axis=alt.Axis(labelLimit=200, labelFontSize=12,
                                      domain=False, ticks=False)),
                x=alt.X("Amount:Q", title=None,
                        axis=alt.Axis(format=",.0f", grid=True,
                                      gridColor="#1B1E24", domain=False,
                                      ticks=False)),
                detail="Category:N",
            )
            points = base.mark_point(filled=True, size=115, opacity=1).encode(
                y=alt.Y("Category:N", sort=cat_order, title=None),
                x="Amount:Q",
                color=alt.Color("MonthLabel:N", sort=month_order, title="Month",
                                scale=alt.Scale(domain=month_order,
                                                range=month_colours),
                                legend=alt.Legend(orient="top",
                                                  direction="horizontal")),
                tooltip=[alt.Tooltip("Category:N"),
                         alt.Tooltip("MonthLabel:N", title="Month"),
                         alt.Tooltip("AmountLabel:N", title="Amount (SGD)"),
                         alt.Tooltip("Transactions:Q")],
            )
            st.altair_chart(
                (zero + line + points)
                .properties(height=32 * len(cat_order) + 60)
                .configure_view(strokeWidth=0)
                .configure_axis(labelColor="#9AA4B2", titleColor="#9AA4B2")
                .configure_legend(labelColor="#C6CBD3", titleColor="#9AA4B2"),
                use_container_width=True,
            )

        st.markdown("##### Month by month")
        shown = trend.copy()
        for column in ("Total Revenues", "Fixed Expenses", "Variable Expenses",
                       "Total Expenses", "Net Income"):
            shown[column] = shown[column].map(lambda v: f"{v:,.2f}")
        shown["Savings Rate"] = trend["Savings Rate"].map(
            lambda v: "" if pd.isna(v) else f"{v:.1f}%")
        st.dataframe(shown, hide_index=True, width="stretch")

    notes = []
    if summary.review_count:
        notes.append(
            f"**{summary.review_count}** transaction(s) still need review — open "
            f"a month and check its Review tab.")
    if summary.excluded_total:
        notes.append(
            f"**S${summary.excluded_total:,.2f}** of transfers sits outside these "
            f"totals: card bill payments, movements between your own accounts, "
            f"and transfers too large to categorise on a guess.")
    if summary.cpf_employee:
        notes.append(
            f"CPF counted in Income: **S${summary.cpf_employee:,.2f}** employee "
            f"share"
            + (f", plus S${summary.cpf_employer:,.2f} employer share."
               if include_employer_cpf
               else f" (employer's S${summary.cpf_employer:,.2f} not counted)."))
    for note in notes:
        st.caption(md(note))

elif view_kind == LOG_VIEW:
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
elif view_kind == EXPORT_VIEW:
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
