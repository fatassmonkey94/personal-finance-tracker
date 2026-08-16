"""CPF rules checked against CPF Board's published figures.

Source: "CPF Contribution Rate Table from 1 January 2026", cpf.gov.sg.
The "Max." column in that table is the authority these tests assert against —
if a rate is mistyped, the max contribution stops matching.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finance import cpf

MAY_2026 = date(2026, 5, 1)


# ---------------------------------------------------------------------------
# Wage ceilings
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("when,expected", [
    (date(2026, 5, 1), 8000.0),
    (date(2026, 1, 1), 8000.0),
    (date(2025, 12, 31), 7400.0),
    (date(2025, 1, 1), 7400.0),
    (date(2024, 6, 1), 6800.0),
    (date(2023, 10, 1), 6300.0),
    (date(2023, 1, 1), 6000.0),
])
def test_ow_ceiling_by_month(when, expected):
    assert cpf.ow_ceiling_for(when) == expected


def test_annual_ceilings_are_recorded():
    assert cpf.ANNUAL_SALARY_CEILING == 102_000.0
    assert cpf.CPF_ANNUAL_LIMIT == 37_740.0


# ---------------------------------------------------------------------------
# Table 1 — Singapore Citizens / SPR 3rd year onwards (the default)
# ---------------------------------------------------------------------------
# (age band, printed max total, printed max employee share)
TABLE_1_MAXIMA = [
    ("55 and below",   2960, 1600),
    ("Above 55 to 60", 2720, 1440),
    ("Above 60 to 65", 2000, 1000),
    ("Above 65 to 70", 1320,  600),
    ("Above 70",       1000,  400),
]


@pytest.mark.parametrize("age_band,max_total,max_employee", TABLE_1_MAXIMA)
def test_table_1_maxima_match_the_published_figures(age_band, max_total, max_employee):
    """At the ceiling, contributions must equal the table's printed Max."""
    result = cpf.contributions(cpf.ow_ceiling_for(MAY_2026), MAY_2026,
                               cpf.STATUS_CITIZEN, age_band)
    assert result.total == pytest.approx(max_total, abs=0.5)
    assert result.employee == pytest.approx(max_employee, abs=0.5)


@pytest.mark.parametrize("age_band,max_total,max_employee", TABLE_1_MAXIMA)
def test_contributions_never_exceed_the_maxima(age_band, max_total, max_employee):
    """However large the salary, the cap holds."""
    result = cpf.contributions(250_000, MAY_2026, cpf.STATUS_CITIZEN, age_band)
    assert result.total <= max_total + 0.5
    assert result.employee <= max_employee + 0.5


@pytest.mark.parametrize("status,age_band,max_total,max_employee", [
    (cpf.STATUS_SPR1_GG, "55 and below", 720, 400),
    (cpf.STATUS_SPR1_GG, "Above 60 to 65", 680, 400),
    (cpf.STATUS_SPR2_GG, "55 and below", 1920, 1200),
    (cpf.STATUS_SPR2_GG, "Above 55 to 60", 1480, 1000),
    (cpf.STATUS_SPR2_GG, "Above 60 to 65", 880, 600),
    (cpf.STATUS_SPR1_FG, "55 and below", 1760, 400),
    (cpf.STATUS_SPR1_FG, "Above 60 to 65", 1400, 400),
    (cpf.STATUS_SPR1_FG, "Above 70", 1000, 400),
])
def test_spr_tables_match_published_maxima(status, age_band, max_total, max_employee):
    result = cpf.contributions(cpf.ow_ceiling_for(MAY_2026), MAY_2026, status, age_band)
    assert result.total == pytest.approx(max_total, abs=0.5)
    assert result.employee == pytest.approx(max_employee, abs=0.5)


# ---------------------------------------------------------------------------
# The wage bands
# ---------------------------------------------------------------------------
def test_no_contribution_at_or_below_fifty():
    for wage in (0, 1, 49.99, 50):
        result = cpf.contributions(wage, MAY_2026)
        assert result.total == 0
        assert result.employee == 0
        assert result.employer == 0


def test_employer_only_between_fifty_and_five_hundred():
    result = cpf.contributions(400, MAY_2026)
    assert result.employee == 0
    assert result.employer > 0
    # Total is 17% of total wages for the 55-and-below band.
    assert result.total == pytest.approx(round(0.17 * 400), abs=0.5)


def test_employee_share_phases_in_between_five_hundred_and_seven_fifty():
    """Employee share is 0.6 x (TW - 500) in this band."""
    for wage in (550, 600, 700, 750):
        result = cpf.contributions(wage, MAY_2026)
        assert result.employee == pytest.approx(int(0.6 * (wage - 500)), abs=0.5)


def test_phase_in_is_continuous_at_the_boundaries():
    assert cpf.contributions(500, MAY_2026).employee == 0
    assert cpf.contributions(500.01, MAY_2026).employee == 0
    # At $750 the phase-in reaches 0.6 x 250 = $150, and full rates give
    # 20% x 750 = $150 too, so the bands meet without a jump.
    assert cpf.contributions(750, MAY_2026).employee == 150
    assert cpf.contributions(750.01, MAY_2026).employee == 150


def test_full_rates_above_seven_fifty():
    result = cpf.contributions(3000, MAY_2026)
    assert result.employee == pytest.approx(600, abs=0.5)   # 20%
    assert result.total == pytest.approx(1110, abs=0.5)     # 37%


def test_contribution_is_monotonic_in_wages():
    previous = -1.0
    wage = 0.0
    while wage <= 12_000:
        employee = cpf.contributions(wage, MAY_2026).employee
        assert employee >= previous
        previous = employee
        wage += 25


# ---------------------------------------------------------------------------
# The cap — the bug this module was written to fix
# ---------------------------------------------------------------------------
def test_ceiling_caps_a_high_salary():
    """A flat 20% of a $16,066 salary would be $3,213; the true figure is $1,600."""
    result = cpf.contributions(16_066.69, MAY_2026)
    assert result.employee == 1600
    assert result.ow_subject_to_cpf == 8000
    assert result.capped is True
    assert result.employee < 0.20 * 16_066.69


def test_salary_at_the_ceiling_is_not_flagged_as_capped():
    assert cpf.contributions(8000, MAY_2026).capped is False
    assert cpf.contributions(8000.01, MAY_2026).capped is True


def test_older_month_uses_the_older_ceiling():
    result = cpf.contributions(10_000, date(2025, 5, 1))
    assert result.ceiling == 7400
    assert result.employee == pytest.approx(0.20 * 7400, abs=0.5)


# ---------------------------------------------------------------------------
# Gross-up: recovering gross pay from the bank credit
# ---------------------------------------------------------------------------
def test_gross_up_round_trips_below_the_ceiling():
    gross = 5000.0
    forward = cpf.contributions(gross, MAY_2026)
    back = cpf.gross_up(forward.take_home, MAY_2026)
    assert back.gross_ow == pytest.approx(gross, abs=1.0)
    assert back.employee == pytest.approx(forward.employee, abs=1.0)


def test_gross_up_round_trips_above_the_ceiling():
    gross = 16_066.69
    forward = cpf.contributions(gross, MAY_2026)
    back = cpf.gross_up(forward.take_home, MAY_2026)
    assert back.gross_ow == pytest.approx(gross, abs=1.0)
    assert back.employee == 1600


def test_gross_up_of_a_real_salary_credit():
    """The May 2026 statement credited S$14,466.69."""
    result = cpf.gross_up(14_466.69, MAY_2026)
    assert result.employee == 1600
    assert result.gross_ow == pytest.approx(16_066.69, abs=1.0)
    assert result.take_home == pytest.approx(14_466.69, abs=1.0)


def test_gross_up_of_zero_is_zero():
    result = cpf.gross_up(0, MAY_2026)
    assert result.gross_ow == 0
    assert result.employee == 0


@pytest.mark.parametrize("credited", [100, 400, 520, 700, 900, 5000, 6000, 7000,
                                      8000, 12_000, 30_000])
def test_gross_up_always_reproduces_the_credited_amount(credited):
    result = cpf.gross_up(credited, MAY_2026)
    assert result.take_home == pytest.approx(credited, abs=1.0)


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------
def test_employer_plus_employee_equals_total():
    for wage in (0, 60, 300, 600, 1000, 8000, 20_000):
        result = cpf.contributions(wage, MAY_2026)
        assert result.employee + result.employer == pytest.approx(result.total, abs=0.01)


def test_employee_share_is_a_whole_number_of_dollars():
    """CPF Board rounds the employee's share down to the nearest dollar."""
    for wage in (612.34, 1234.56, 7999.99):
        assert cpf.contributions(wage, MAY_2026).employee % 1 == 0


def test_citizen_is_the_default_status():
    assert cpf.contributions(5000, MAY_2026).status == cpf.STATUS_CITIZEN
    assert cpf.contributions(5000, MAY_2026).age_band == "55 and below"
    assert cpf.STATUSES[0] == cpf.STATUS_CITIZEN
    assert cpf.AGE_BANDS[0] == "55 and below"


def test_unknown_status_or_age_falls_back_to_the_citizen_default():
    fallback = cpf.rates_for("not a status", "not an age")
    assert fallback == cpf.rates_for(cpf.STATUS_CITIZEN, "55 and below")


def test_month_start_parsing():
    assert cpf.month_start("2026-05") == date(2026, 5, 1)
    assert cpf.month_start("nonsense") is None
