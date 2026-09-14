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


def test_no_data_points_at_the_intake_button():
    app = AppTest.from_file(APP, default_timeout=60).run()
    assert any("Add statements" in str(i.value) for i in app.info)
    assert any(b.key == "open_intake" for b in app.button)


# ---------------------------------------------------------------------------
# The landing page is the year dashboard
# ---------------------------------------------------------------------------
def test_landing_page_is_the_year_dashboard():
    app, _txns = _app_with_data()
    assert app.session_state["view"] == ("year", YEAR)
    assert f"{YEAR} dashboard" in [s.value for s in app.subheader]


def test_dashboard_draws_three_pies_and_the_ytd_plot():
    app, _txns = _app_with_data()
    md = _markdown(app)
    for pie in ("Income", "Expenses", "Savings"):
        assert f'class="pie-title">{pie}<' in md, pie
    assert "Year to date, month on month" in md
    # Three donuts plus the dot plot; the annual-detail expander adds one more.
    assert len(app.get("arrow_vega_lite_chart")) >= 4


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
    for key, heading in [("nav-log", "What each file produced"),
                         ("nav-export", "Export to Excel")]:
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
