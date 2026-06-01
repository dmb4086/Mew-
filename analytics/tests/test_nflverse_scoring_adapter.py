"""Tests for the nflverse scoring adapter."""

from __future__ import annotations

import pytest

from ffdraft.scoring import NFLVERSE_PPR, nflverse_weekly_to_stat_line, score_stat_line
from ffdraft.scoring.nflverse import (
    REQUIRED_NFLVERSE_WEEKLY_COLUMNS,
    validate_nflverse_weekly_schema,
)


def test_nflverse_weekly_row_reproduces_ppr_formula():
    row = {
        "passing_yards": 250,
        "passing_tds": 2,
        "passing_interceptions": 1,
        "rushing_yards": 30,
        "rushing_tds": 1,
        "receptions": 4,
        "receiving_yards": 50,
        "receiving_tds": 1,
        "rushing_fumbles_lost": 1,
        "special_teams_tds": 1,
    }

    stat_line = nflverse_weekly_to_stat_line(row)

    assert stat_line["pass_yd"] == 250.0
    assert stat_line["pass_int"] == 1.0
    assert stat_line["fum_lost"] == 1.0
    # 10 pass yds + 8 pass TD - 2 INT + 3 rush yds + 6 rush TD
    # + 4 rec + 5 rec yds + 6 rec TD - 2 fumble + 6 return TD = 44
    assert score_stat_line(stat_line, NFLVERSE_PPR) == 44.0


def test_nflverse_weekly_schema_validation_accepts_expected_columns():
    validate_nflverse_weekly_schema(REQUIRED_NFLVERSE_WEEKLY_COLUMNS | {"player_id", "season"})


def test_nflverse_weekly_schema_validation_detects_drift():
    drifted = (REQUIRED_NFLVERSE_WEEKLY_COLUMNS - {"passing_yards"}) | {"pass_yds"}

    with pytest.raises(ValueError, match="passing_yards"):
        validate_nflverse_weekly_schema(drifted)
