"""CPF contribution rules, transcribed from CPF Board's official rate tables.

Source: "CPF Contribution Rate Table from 1 January 2026", cpf.gov.sg
  https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPFcontributionratesfrom1Jan2026.pdf
Wage ceilings: https://www.cpf.gov.sg/service/article/what-is-the-ordinary-wage-ow-ceiling

Two things a flat "20% of salary" gets wrong, and this module gets right:

1. **The Ordinary Wage ceiling.** Only the first $8,000 of a month's wages
   attracts CPF (2026; lower in earlier years). On a $14,466 salary the employee
   share is 20% x $8,000 = $1,600, not 20% x $14,466 = $2,893.

2. **The low-wage bands.** Below $50 there is no contribution at all; from $50 to
   $500 the employer contributes but the employee does not; from $500 to $750 the
   employee share phases in gradually.

Rounding follows the Board's stated steps: the total contribution is rounded to
the nearest dollar, the employee's share is rounded *down* to the nearest dollar,
and the employer's share is the difference.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ordinary Wage ceiling, by the month it took effect
# ---------------------------------------------------------------------------
OW_CEILING_HISTORY: List[Tuple[date, float]] = [
    (date(2026, 1, 1), 8000.0),
    (date(2025, 1, 1), 7400.0),
    (date(2024, 1, 1), 6800.0),
    (date(2023, 9, 1), 6300.0),
    (date(1900, 1, 1), 6000.0),
]

# The annual salary ceiling and CPF Annual Limit, for reference in the UI.
ANNUAL_SALARY_CEILING = 102_000.0
CPF_ANNUAL_LIMIT = 37_740.0


def ow_ceiling_for(when: Optional[date]) -> float:
    """The Ordinary Wage ceiling in force for a given month."""
    if when is None:
        return OW_CEILING_HISTORY[0][1]
    for effective_from, ceiling in OW_CEILING_HISTORY:
        if when >= effective_from:
            return ceiling
    return OW_CEILING_HISTORY[-1][1]


# ---------------------------------------------------------------------------
# Contribution rates
# ---------------------------------------------------------------------------
AGE_BANDS = [
    "55 and below",
    "Above 55 to 60",
    "Above 60 to 65",
    "Above 65 to 70",
    "Above 70",
]

STATUS_CITIZEN = "Singapore Citizen / SPR 3rd year onwards"
STATUS_SPR1_GG = "SPR 1st year (graduated)"
STATUS_SPR2_GG = "SPR 2nd year (graduated)"
STATUS_SPR1_FG = "SPR 1st year (full employer, graduated employee)"

STATUSES = [STATUS_CITIZEN, STATUS_SPR1_GG, STATUS_SPR2_GG, STATUS_SPR1_FG]


@dataclass(frozen=True)
class Rates:
    """One age row of one table.

    total_rate / employee_rate apply to Ordinary Wages above $750.
    band_500_total is the total rate applied to total wages in $50-$750.
    phase_in is the employee coefficient on (TW - 500) in the $500-$750 band.
    """

    total_rate: float
    employee_rate: float
    band_500_total: float
    phase_in: float


# Table 1 — Singapore Citizens and SPRs from their 3rd year. The default.
_TABLE_1 = {
    "55 and below":   Rates(0.37,  0.20,  0.17,  0.60),
    "Above 55 to 60": Rates(0.34,  0.18,  0.16,  0.54),
    "Above 60 to 65": Rates(0.25,  0.125, 0.125, 0.375),
    "Above 65 to 70": Rates(0.165, 0.075, 0.09,  0.225),
    "Above 70":       Rates(0.125, 0.05,  0.075, 0.15),
}

# Table 2 — SPR 1st year, graduated / graduated.
_TABLE_2 = {
    "55 and below":   Rates(0.09,  0.05, 0.04,  0.15),
    "Above 55 to 60": Rates(0.09,  0.05, 0.04,  0.15),
    "Above 60 to 65": Rates(0.085, 0.05, 0.035, 0.15),
    "Above 65 to 70": Rates(0.085, 0.05, 0.035, 0.15),
    "Above 70":       Rates(0.085, 0.05, 0.035, 0.15),
}

# Table 3 — SPR 2nd year, graduated / graduated.
_TABLE_3 = {
    "55 and below":   Rates(0.24,  0.15,  0.09,  0.45),
    "Above 55 to 60": Rates(0.185, 0.125, 0.06,  0.375),
    "Above 60 to 65": Rates(0.11,  0.075, 0.035, 0.225),
    "Above 65 to 70": Rates(0.085, 0.05,  0.035, 0.15),
    "Above 70":       Rates(0.085, 0.05,  0.035, 0.15),
}

# Table 4 — SPR 1st year, full employer / graduated employee.
_TABLE_4 = {
    "55 and below":   Rates(0.22,  0.05, 0.17,  0.15),
    "Above 55 to 60": Rates(0.21,  0.05, 0.16,  0.15),
    "Above 60 to 65": Rates(0.175, 0.05, 0.125, 0.15),
    "Above 65 to 70": Rates(0.14,  0.05, 0.09,  0.15),
    "Above 70":       Rates(0.125, 0.05, 0.075, 0.15),
}

_TABLES: Dict[str, Dict[str, Rates]] = {
    STATUS_CITIZEN: _TABLE_1,
    STATUS_SPR1_GG: _TABLE_2,
    STATUS_SPR2_GG: _TABLE_3,
    STATUS_SPR1_FG: _TABLE_4,
}

# Wage band boundaries from the tables.
NIL_BAND = 50.0
EMPLOYER_ONLY_BAND = 500.0
PHASE_IN_BAND = 750.0


def rates_for(status: str = STATUS_CITIZEN, age_band: str = "55 and below") -> Rates:
    table = _TABLES.get(status, _TABLE_1)
    return table.get(age_band, table["55 and below"])


@dataclass
class CpfResult:
    """CPF on one month of Ordinary Wages."""

    gross_ow: float          # wages before the employee's CPF deduction
    ow_subject_to_cpf: float # gross, capped at the ceiling
    ceiling: float
    employee: float
    employer: float
    total: float
    band: str                # which wage band applied
    capped: bool             # was the ceiling binding?
    status: str = STATUS_CITIZEN
    age_band: str = "55 and below"

    @property
    def take_home(self) -> float:
        return round(self.gross_ow - self.employee, 2)


def _round_nearest(value: float) -> float:
    """CPF Board: round to nearest dollar, .50 and above rounds up."""
    from math import floor
    return float(floor(value + 0.5))


def _employee_share_raw(gross_ow: float, rates: Rates, ceiling: float) -> float:
    """Unrounded employee share — kept monotonic so gross-up can invert it."""
    if gross_ow <= NIL_BAND:
        return 0.0
    if gross_ow <= EMPLOYER_ONLY_BAND:
        return 0.0
    if gross_ow <= PHASE_IN_BAND:
        return rates.phase_in * (gross_ow - EMPLOYER_ONLY_BAND)
    return rates.employee_rate * min(gross_ow, ceiling)


def _total_raw(gross_ow: float, rates: Rates, ceiling: float) -> float:
    if gross_ow <= NIL_BAND:
        return 0.0
    if gross_ow <= EMPLOYER_ONLY_BAND:
        return rates.band_500_total * gross_ow
    if gross_ow <= PHASE_IN_BAND:
        return (rates.band_500_total * gross_ow
                + rates.phase_in * (gross_ow - EMPLOYER_ONLY_BAND))
    return rates.total_rate * min(gross_ow, ceiling)


def _band_label(gross_ow: float) -> str:
    if gross_ow <= NIL_BAND:
        return "$50 or less — no contribution"
    if gross_ow <= EMPLOYER_ONLY_BAND:
        return "$50 to $500 — employer only"
    if gross_ow <= PHASE_IN_BAND:
        return "$500 to $750 — employee share phasing in"
    return "above $750 — full rates"


def contributions(gross_ow: float, month: Optional[date] = None,
                  status: str = STATUS_CITIZEN,
                  age_band: str = "55 and below") -> CpfResult:
    """CPF on a month's Ordinary Wages, given the *gross* figure."""
    gross_ow = max(0.0, round(float(gross_ow), 2))
    ceiling = ow_ceiling_for(month)
    rates = rates_for(status, age_band)

    total = _round_nearest(_total_raw(gross_ow, rates, ceiling))
    # The Board rounds the employee's share down to the nearest dollar.
    employee = float(int(_employee_share_raw(gross_ow, rates, ceiling)))
    employer = round(total - employee, 2)

    return CpfResult(
        gross_ow=gross_ow,
        ow_subject_to_cpf=round(min(gross_ow, ceiling), 2),
        ceiling=ceiling,
        employee=employee,
        employer=max(0.0, employer),
        total=total,
        band=_band_label(gross_ow),
        capped=gross_ow > ceiling,
        status=status,
        age_band=age_band,
    )


def gross_up(take_home: float, month: Optional[date] = None,
             status: str = STATUS_CITIZEN,
             age_band: str = "55 and below") -> CpfResult:
    """Recover gross Ordinary Wages from the amount credited to the bank.

    The salary that reaches your account is already net of your own CPF share,
    so `take_home = gross - employee_share(gross)`. That relation is monotonic in
    gross, so it inverts cleanly; the ceiling makes it piecewise, hence the
    search rather than a single formula.
    """
    take_home = max(0.0, round(float(take_home), 2))
    if take_home == 0:
        return contributions(0.0, month, status, age_band)

    ceiling = ow_ceiling_for(month)
    rates = rates_for(status, age_band)

    def net_of(gross: float) -> float:
        return gross - _employee_share_raw(gross, rates, ceiling)

    low, high = take_home, take_home * 2 + 1000.0
    for _ in range(80):
        mid = (low + high) / 2
        if net_of(mid) < take_home:
            low = mid
        else:
            high = mid
    return contributions(round(high, 2), month, status, age_band)


def month_start(month_key: str) -> Optional[date]:
    """'2026-05' -> date(2026, 5, 1), for picking the right ceiling."""
    try:
        year, month = (int(part) for part in month_key.split("-"))
        return date(year, month, 1)
    except (ValueError, AttributeError):
        return None
