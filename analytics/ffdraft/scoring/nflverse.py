"""Adapters for validating scoring against nflverse player stats."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .league import SLEEPER_DEFAULT_PPR, LeagueScoring

# nflverse's built-in `fantasy_points_ppr` convention is close to common PPR but
# uses -2 per passing interception and credits return TDs. Keep it separate from
# `SLEEPER_DEFAULT_PPR`, because the target Sleeper league may use different
# interception settings.
NFLVERSE_PPR = replace(
    SLEEPER_DEFAULT_PPR,
    name="nflverse fantasy_points_ppr",
    rules={
        **SLEEPER_DEFAULT_PPR.rules,
        "pass_int": -2.0,
        "st_td": 6.0,
    },
)

_NFLVERSE_TO_SCORING_KEYS = {
    "passing_yards": "pass_yd",
    "passing_tds": "pass_td",
    "passing_interceptions": "pass_int",
    "passing_2pt_conversions": "pass_2pt",
    "rushing_yards": "rush_yd",
    "rushing_tds": "rush_td",
    "rushing_2pt_conversions": "rush_2pt",
    "receptions": "rec",
    "receiving_yards": "rec_yd",
    "receiving_tds": "rec_td",
    "receiving_2pt_conversions": "rec_2pt",
    "special_teams_tds": "st_td",
}

_FUMBLE_LOST_COLUMNS = (
    "sack_fumbles_lost",
    "rushing_fumbles_lost",
    "receiving_fumbles_lost",
)

REQUIRED_NFLVERSE_WEEKLY_COLUMNS = frozenset(_NFLVERSE_TO_SCORING_KEYS) | frozenset(
    _FUMBLE_LOST_COLUMNS
)


def validate_nflverse_weekly_schema(columns: object) -> None:
    """Fail fast when upstream nflverse weekly stat column names drift."""
    present = {str(c) for c in columns}
    missing = sorted(REQUIRED_NFLVERSE_WEEKLY_COLUMNS - present)
    if missing:
        raise ValueError(f"nflverse weekly stats missing expected columns: {missing}")


def nflverse_weekly_to_stat_line(row: Mapping[str, object]) -> dict[str, float]:
    """Translate one nflverse weekly stat row to scoring-engine keys."""
    stat_line: dict[str, float] = {}
    for nflverse_key, scoring_key in _NFLVERSE_TO_SCORING_KEYS.items():
        value = row.get(nflverse_key)
        if value is None:
            continue
        stat_line[scoring_key] = float(value)

    fumbles_lost = sum(float(row.get(key) or 0.0) for key in _FUMBLE_LOST_COLUMNS)
    if fumbles_lost:
        stat_line["fum_lost"] = fumbles_lost
    return stat_line


def nflverse_ppr_scoring() -> LeagueScoring:
    """Return the scoring rules that reproduce nflverse `fantasy_points_ppr`."""
    return NFLVERSE_PPR
