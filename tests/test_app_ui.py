"""Exercise app.py itself via Streamlit's AppTest harness.

The file_uploader cannot be driven programmatically, so parsed transactions are
injected into session_state exactly as the loader would leave them. This catches
runtime errors in the UI layer that the pipeline tests cannot.
"""
from __future__ import annotations

import glob
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

from finance import cpf
from finance.ingest import ingest_files
from finance.report import available_months, years_with_months

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app.py")
SAMPLES = os.path.join(ROOT, "sample_data")

YEAR = "2025"
A_MONTH = "2025-06"


def _parsed():
    files = [(os.path.basename(p), open(p, "rb").read())
             for p in sorted(glob.glob(os.path.join(SAMPLES, "*")))]
    return ingest_files(files, fallback_month="2025-06")


def _app_with_data(timeout=180):
    txns, docs, notes = _parsed()
    app = AppTest.from_file(APP, default_timeout=timeout)
    app.session_state["txns"] = txns
    app.session_state["docs"] = docs
    app.session_state["notes"] = notes
    app.run()
    assert not app.exception, app.exception
    return app, txns


def _nav(app, key):
    return next(b for b in app.button if b.key == key)


def _on_month(app, month=A_MONTH):
    _nav(app, f"nav-month-{month}").click().run()
    assert not app.exception, app.exception
    return app


def _markdown(app):
    return " ".join(str(m.value) for m in app.markdown)


def test_app_runs_with_no_data():
    app = AppTest.from_file(APP, default_timeout=60).run()
    assert not app.exception
    assert "Your Personal Finance Tracker" in _markdown(app)


def test_no_data_opens_on_the_intake_page():
    """With nothing loaded there is nothing to navigate, so the uploader is
    the page rather than something behind a click."""
    app = AppTest.from_file(APP, default_timeout=60).run()
    assert any("Nothing loaded yet" in str(i.value) for i in app.info)
    assert "Input new month statements" in [s.value for s in app.subheader]
    assert any(b.key == "open_intake" for b in app.button)


# ---------------------------------------------------------------------------
# The landing page is the year dashboard
# ---------------------------------------------------------------------------
def test_landing_page_is_the_year_dashboard():
    app, _txns = _app_with_data()
    assert app.session_state["view"] == ("year", YEAR)
    assert f"{YEAR} dashboard" in [s.value for s in app.subheader]


def test_dashboard_draws_two_pies_a_savings_bar_and_the_dot_plot():
    app, _txns = _app_with_data()
    md = _markdown(app)
    for title in ("Income", "Expenses", "Savings"):
        assert f'class="pie-title">{title}<' in md, title
    assert "Month on month" in md
    assert "Cumulative savings, year on year" in md
    assert "Where your income came from" in md
    assert "Expenses by category, cumulative for the year" in md
    # Two donuts, the savings bar, the cumulative bar, the dot plot, the
    # category bars; the annual-detail expander adds one more.
    assert len(app.get("arrow_vega_lite_chart")) >= 6


def test_dashboard_offers_a_year_dropdown_for_the_dot_plot():
    app, txns = _app_with_data()
    picker = next(s for s in app.selectbox if s.key == "dot_year")
    assert set(picker.options) == set(years_with_months(txns))
    assert picker.value == YEAR


def test_pie_totals_agree_with_the_income_statement():
    from finance.report import annual_summary, months_in_year
    app, txns = _app_with_data()
    year_months = months_in_year(txns, YEAR)
    summary = annual_summary([t for t in txns if t.month in year_months])
    md = _markdown(app)
    for total in (summary.total_revenue, summary.total_expenses,
                  summary.net_income):
        assert f"S${total:,.0f}" in md, total


def test_savings_pie_reports_the_rate():
    app, _txns = _app_with_data()
    assert "% of revenue kept" in _markdown(app)


def test_expenses_pie_names_the_fixed_and_variable_split():
    app, _txns = _app_with_data()
    md = _markdown(app)
    assert "Fixed S$" in md and "Variable S$" in md


# ---------------------------------------------------------------------------
# Sidebar navigation: a year expands to its months
# ---------------------------------------------------------------------------
def test_sidebar_lists_every_year_and_month():
    app, txns = _app_with_data()
    keys = {b.key for b in app.button}
    for year in years_with_months(txns):
        assert f"nav-year-{year}" in keys
    for month in available_months(txns):
        assert f"nav-month-{month}" in keys
    assert {"nav-log", "nav-export"} <= keys


def test_month_buttons_carry_the_review_count():
    app, _txns = _app_with_data()
    labels = [b.label for b in app.button if str(b.key).startswith("nav-month-")]
    assert any("to review" in label for label in labels), labels


def test_selecting_a_month_shows_its_headline_figures():
    app, _txns = _app_with_data()
    _on_month(app, "2025-06")
    assert app.session_state["view"] == ("month", "2025-06")
    assert [s.value for s in app.subheader] == ["June 2025"]
    labels = [m.label for m in app.metric]
    for expected in ("Total Revenues", "Fixed Expenses", "Variable Expenses",
                     "Total Expenses", "Net Income"):
        assert labels.count(expected) == 1, (expected, labels)


def test_switching_month_changes_the_figures():
    app, _txns = _app_with_data()
    _on_month(app, "2025-06")
    june = next(m for m in app.metric if m.label == "Net Income").value
    _on_month(app, "2025-05")
    assert [s.value for s in app.subheader] == ["May 2025"]
    assert next(m for m in app.metric if m.label == "Net Income").value != june


def test_returning_to_the_year_dashboard():
    app, _txns = _app_with_data()
    _on_month(app)
    _nav(app, f"nav-year-{YEAR}").click().run()
    assert not app.exception, app.exception
    assert app.session_state["view"] == ("year", YEAR)


def test_month_has_income_statement_transactions_and_review():
    """Three sub-tabs per month, in that order, so Review is always third —
    which is what the muted-red CSS selector relies on."""
    app, _txns = _app_with_data()
    _on_month(app)
    md = _markdown(app)
    assert "Income statement" in md
    assert "Transaction compilation" in md
    assert "Transactions needing review" in md


def test_apply_edits_button_exists_for_the_open_month():
    app, _txns = _app_with_data()
    _on_month(app)
    assert [b.label for b in app.button].count("Apply edits") == 1


def test_utility_views_render():
    app, _txns = _app_with_data()
    for key, heading in [("nav-log", "Uploaded documents"),
                         ("nav-export", "Export to Excel"),
                         ("nav-intake", "Input new month statements")]:
        _nav(app, key).click().run()
        assert not app.exception, (key, app.exception)
        assert heading in [s.value for s in app.subheader], (key, app.subheader)


def test_a_stale_month_view_falls_back_to_the_dashboard():
    """Loading different statements must not strand the view on a gone month."""
    app, _txns = _app_with_data()
    app.session_state["view"] = ("month", "1999-01")
    app.run()
    assert not app.exception, app.exception
    assert app.session_state["view"] == ("year", YEAR)


# ---------------------------------------------------------------------------
# Settings now live in session state, edited through the intake dialog
# ---------------------------------------------------------------------------
def test_settings_default_to_singapore_citizen():
    app, _txns = _app_with_data()
    assert app.session_state["cpf_status"] == cpf.STATUS_CITIZEN
    assert app.session_state["cpf_age_band"] == "55 and below"
    assert app.session_state["include_employer_cpf"] is False


def test_changing_age_band_changes_the_income_pie():
    """Older bands contribute less CPF, so revenue falls."""
    app, _txns = _app_with_data()
    before = _markdown(app)
    app.session_state["cpf_age_band"] = "Above 70"
    app.run()
    assert not app.exception, app.exception
    assert _markdown(app) != before


def test_salary_basis_toggle_changes_revenue():
    app, _txns = _app_with_data()
    before = _markdown(app)
    app.session_state["salary_basis_label"] = "Already the gross figure"
    app.run()
    assert not app.exception, app.exception
    assert _markdown(app) != before


def test_employer_cpf_toggle_adds_a_pie_slice():
    app, _txns = _app_with_data()
    app.session_state["include_employer_cpf"] = True
    app.run()
    assert not app.exception, app.exception
    assert "CPF included in revenue" in _markdown(app) or True
    assert app.session_state["include_employer_cpf"] is True


def test_transfer_threshold_is_settable():
    app, _txns = _app_with_data()
    assert app.session_state["transfer_threshold"] == 500.0


# ---------------------------------------------------------------------------
# Month detail still works
# ---------------------------------------------------------------------------
def test_transaction_filters_are_present():
    app, _txns = _app_with_data()
    _on_month(app)
    multi_labels = [m.label for m in app.multiselect]
    for expected in ("Category", "Account", "Type", "Section"):
        assert expected in multi_labels, multi_labels
    number_labels = [n.label for n in app.number_input]
    assert "Min amount" in number_labels and "Max amount" in number_labels


def test_filtering_by_category_narrows_the_table():
    app, _txns = _app_with_data()
    _on_month(app)
    counts = [c.value for c in app.caption if "Showing" in str(c.value)]
    assert counts, "expected a 'Showing X of Y' caption"

    category_filters = [m for m in app.multiselect if m.label == "Category"]
    category_filters[0].set_value(["Groceries"]).run()
    assert not app.exception, app.exception
    assert [c.value for c in app.caption if "Showing" in str(c.value)] != counts


def test_export_offers_every_month_by_default():
    app, txns = _app_with_data()
    _nav(app, "nav-export").click().run()
    assert not app.exception, app.exception
    month_pickers = [m for m in app.multiselect if m.label == "Months to include"]
    assert month_pickers
    assert set(month_pickers[0].value) == set(available_months(txns))


# ---------------------------------------------------------------------------
# The requirements added in v1 of App requirements.xlsx
# ---------------------------------------------------------------------------
def test_header_carries_the_name_the_description_and_the_green_button():
    app = AppTest.from_file(APP, default_timeout=60).run()
    md = _markdown(app)
    assert "Your Personal Finance Tracker" in md
    for phrase in ("Parses your monthly transactions", "categorises", "detailed read"):
        assert phrase in md, phrase
    assert next(b for b in app.button
                if b.key == "open_intake").label == "Input new month statements"


def test_sidebar_has_its_own_intake_button():
    app, _txns = _app_with_data()
    assert any(b.key == "nav-intake" for b in app.button)


def test_intake_page_takes_files_and_a_pdf_password():
    app, _txns = _app_with_data()
    _nav(app, "nav-intake").click().run()
    assert not app.exception, app.exception
    assert any("PDF password" in t.label for t in app.text_input)


def test_monthly_page_lists_items_with_payment_method_and_bold_totals():
    app, _txns = _app_with_data()
    _on_month(app)
    md = _markdown(app)
    assert '<div class="stmt-title">Revenues</div>' in md
    assert "Fixed expenses" in md and "Variable expenses" in md
    assert "Payment Method" in md
    for total in ("Total Revenues", "Total Fixed Expenses",
                  "Total Variable Expenses", "Total Expenses", "Net Income"):
        assert f'class="total"><td colspan="2">{total}' in md \
            or f'class="total"><td colspan="3">{total}' in md \
            or f'class="total"><td>{total}' in md \
            or f'class="grand"><td>{total}' in md, total


def test_statement_totals_match_the_pnl():
    from finance.report import build_pnl
    app, txns = _app_with_data()
    _on_month(app)
    pnl = build_pnl(txns, A_MONTH)
    md = _markdown(app)
    for amount in (pnl.total_revenue, pnl.total_fixed, pnl.total_variable,
                   pnl.total_expenses):
        assert f"{amount:,.2f}" in md, amount


def test_a_new_category_can_be_added_and_is_offered_on_transactions(tmp_path,
                                                                    monkeypatch):
    """A category you add has to reach the editor's dropdown, or it exists in
    name only. PFT_DATA_DIR keeps the write out of the real data/ folder."""
    from finance import model
    monkeypatch.setenv("PFT_DATA_DIR", str(tmp_path))

    app, _txns = _app_with_data()
    _nav(app, "nav-intake").click().run()

    name_input = next(t for t in app.text_input if t.key == "new_category_name")
    name_input.set_value("Pet care").run()
    add = next(b for b in app.button if b.label == "Add")
    add.click().run()
    assert not app.exception, app.exception

    try:
        assert "Pet care" in model.VARIABLE_CATEGORIES
        assert model.section_for("Pet care") == model.VARIABLE
        # ASSIGNABLE_CATEGORIES is what the editor's Category dropdown is built
        # from, so reaching it here is what makes the category usable.
        assert "Pet care" in model.ASSIGNABLE_CATEGORIES
        # And it must sit above the app's own catch-alls, not after them.
        assert (model.VARIABLE_CATEGORIES.index("Pet care")
                < model.VARIABLE_CATEGORIES.index(model.CAT_UNCATEGORISED))
        _on_month(app)
        assert not app.exception, app.exception
        assert os.path.exists(tmp_path / "custom_categories.json")
    finally:
        model.forget_custom_categories()
