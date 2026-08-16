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
from finance.report import available_months

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app.py")
SAMPLES = os.path.join(ROOT, "sample_data")

OVERVIEW = "Overview"
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


def _strip(app):
    """The view strip, selected by key so the sidebar radio is not picked."""
    return next(r for r in app.radio if r.key == "month_strip")


def _on_month(app, month=A_MONTH):
    _strip(app).set_value(month).run()
    assert not app.exception, app.exception
    return app


def test_app_runs_with_no_data():
    app = AppTest.from_file(APP, default_timeout=60).run()
    assert not app.exception
    assert any("Personal Finance Tracker" in t.value for t in app.title)


# ---------------------------------------------------------------------------
# The landing page is the annual overview
# ---------------------------------------------------------------------------
def test_landing_page_is_the_annual_overview():
    app, _txns = _app_with_data()
    assert _strip(app).value == OVERVIEW
    assert "Annual overview" in [s.value for s in app.subheader]
    labels = [m.label for m in app.metric]
    assert labels == ["Total Revenues", "Total Expenses", "Net Income",
                      "Avg Monthly Spend", "Avg Monthly Net"]


def test_overview_renders_the_dot_plot_and_trend_charts():
    app, _txns = _app_with_data()
    headings = [m.value for m in app.markdown]
    assert any("Spending by category, month on month" in h for h in headings)
    assert any("Revenues, expenses and net income" in h for h in headings)
    assert any("Fixed vs variable" in h for h in headings)
    assert any("Month by month" in h for h in headings)
    # Three Vega-Lite charts: the dot plot, the flow lines, the stacked bars.
    assert len(app.get("arrow_vega_lite_chart")) == 3


def test_overview_metrics_carry_money_values():
    app, _txns = _app_with_data()
    for metric in app.metric:
        assert metric.value.startswith("S$"), metric.label


def test_strip_lists_overview_then_months_then_utilities():
    app, txns = _app_with_data()
    strip = _strip(app)
    assert list(strip.options) == [OVERVIEW, "May 2025", "Jun 2025",
                                  "Parsing log", "Export"]
    assert list(strip.options)[1:1 + len(available_months(txns))] == [
        "May 2025", "Jun 2025"]


# ---------------------------------------------------------------------------
# Month views
# ---------------------------------------------------------------------------
def test_selecting_a_month_shows_its_headline_figures():
    app, _txns = _app_with_data()
    _on_month(app, "2025-06")
    assert [s.value for s in app.subheader] == ["June 2025"]
    labels = [m.label for m in app.metric]
    for expected in ("Total Revenues", "Fixed Expenses", "Variable Expenses",
                     "Total Expenses", "Net Income"):
        assert labels.count(expected) == 1, (expected, labels)
    net = next(m for m in app.metric if m.label == "Net Income")
    assert net.value.startswith("S$")


def test_switching_month_changes_the_figures():
    app, _txns = _app_with_data()
    _on_month(app, "2025-06")
    june = next(m for m in app.metric if m.label == "Net Income").value
    _on_month(app, "2025-05")
    assert [s.value for s in app.subheader] == ["May 2025"]
    may = next(m for m in app.metric if m.label == "Net Income").value
    assert may != june


def test_utility_views_render():
    app, _txns = _app_with_data()
    for choice, heading in [("Parsing log", "What each file produced"),
                            ("Export", "Export to Excel")]:
        _strip(app).set_value(choice).run()
        assert not app.exception, (choice, app.exception)
        assert heading in [s.value for s in app.subheader], (choice, app.subheader)


def test_month_has_income_statement_transactions_and_review():
    """Three sub-tabs per month, in that order, so Review is always third —
    which is what the muted-red CSS selector relies on."""
    app, _txns = _app_with_data()
    _on_month(app)
    headings = [m.value for m in app.markdown]
    assert any("Income statement" in h for h in headings)
    assert any("Transaction compilation" in h for h in headings)
    assert any("Transactions needing review" in h for h in headings)


def test_apply_edits_button_exists_for_the_open_month():
    app, _txns = _app_with_data()
    _on_month(app)
    assert [b.label for b in app.button].count("Apply edits") == 1


# ---------------------------------------------------------------------------
# CPF settings
# ---------------------------------------------------------------------------
def test_cpf_defaults_to_singapore_citizen():
    app, _txns = _app_with_data()
    statuses = [s for s in app.selectbox if "Residency" in s.label]
    assert statuses, [s.label for s in app.selectbox]
    assert statuses[0].value == cpf.STATUS_CITIZEN
    ages = [s for s in app.selectbox if "Age band" in s.label]
    assert ages[0].value == "55 and below"


def test_changing_age_band_changes_revenue():
    """Older bands contribute less, so revenue (salary + CPF) falls."""
    app, _txns = _app_with_data()
    before = next(m for m in app.metric if m.label == "Total Revenues").value

    ages = [s for s in app.selectbox if "Age band" in s.label]
    ages[0].set_value("Above 70").run()
    assert not app.exception, app.exception
    after = next(m for m in app.metric if m.label == "Total Revenues").value
    assert after != before


def test_salary_basis_toggle_changes_revenue():
    app, _txns = _app_with_data()
    before = next(m for m in app.metric if m.label == "Total Revenues").value

    basis = next(r for r in app.radio if "bank statement" in r.label)
    basis.set_value("Already the gross figure").run()
    assert not app.exception, app.exception
    after = next(m for m in app.metric if m.label == "Total Revenues").value
    assert after != before


def test_employer_cpf_checkbox_raises_revenue():
    app, _txns = _app_with_data()
    before = next(m for m in app.metric if m.label == "Total Revenues").value

    boxes = [c for c in app.checkbox if "employer's CPF" in c.label]
    assert boxes, [c.label for c in app.checkbox]
    boxes[0].set_value(True).run()
    assert not app.exception, app.exception
    after = next(m for m in app.metric if m.label == "Total Revenues").value
    assert after != before


# ---------------------------------------------------------------------------
# Transaction filters
# ---------------------------------------------------------------------------
def test_transaction_filters_are_present():
    app, _txns = _app_with_data()
    _on_month(app)
    multi_labels = [m.label for m in app.multiselect]
    for expected in ("Category", "Account", "Type", "Section"):
        assert expected in multi_labels, multi_labels
    text_labels = [t.label for t in app.text_input]
    assert any("contains" in label for label in text_labels), text_labels
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
    narrowed = [c.value for c in app.caption if "Showing" in str(c.value)]
    assert narrowed != counts


def test_export_offers_every_month_by_default():
    app, txns = _app_with_data()
    _strip(app).set_value("Export").run()
    assert not app.exception, app.exception
    month_pickers = [m for m in app.multiselect if m.label == "Months to include"]
    assert month_pickers
    assert set(month_pickers[0].value) == set(available_months(txns))
