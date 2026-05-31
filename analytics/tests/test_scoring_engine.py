"""Tests for the Phase 1 scoring engine.

The Phase 1 gate is "reproduce the platform's reported points to the decimal."
Here we verify the calculator is correct against hand-computed box scores under
several formats. The live gate (real Sleeper box scores) plugs the same engine
into fixtures captured from the API.
"""

from __future__ import annotations

from dataclasses import replace

from ffdraft.scoring import SLEEPER_DEFAULT_PPR, league_from_sleeper, score_stat_line
from ffdraft.scoring.engine import explain_score


def test_full_ppr_wr_line():
    # 8 rec, 112 rec yds, 1 rec TD => 8 + 11.2 + 6 = 25.2
    line = {"rec": 8, "rec_yd": 112, "rec_td": 1}
    assert score_stat_line(line, SLEEPER_DEFAULT_PPR) == 25.2


def test_half_ppr_vs_standard_difference():
    line = {"rec": 8, "rec_yd": 112, "rec_td": 1}
    half = replace(SLEEPER_DEFAULT_PPR, rules={**SLEEPER_DEFAULT_PPR.rules, "rec": 0.5})
    std = replace(SLEEPER_DEFAULT_PPR, rules={**SLEEPER_DEFAULT_PPR.rules, "rec": 0.0})
    assert score_stat_line(line, half) == 21.2   # 4 + 11.2 + 6
    assert score_stat_line(line, std) == 17.2    # 0 + 11.2 + 6


def test_qb_line_with_interceptions_and_fumble():
    # 333 pass yds (13.32), 3 pass TD (12), 1 INT (-1), 22 rush yds (2.2),
    # 1 fumble lost (-2) => 24.52
    line = {"pass_yd": 333, "pass_td": 3, "pass_int": 1, "rush_yd": 22, "fum_lost": 1}
    assert score_stat_line(line, SLEEPER_DEFAULT_PPR) == 24.52


def test_unknown_stat_keys_are_ignored():
    line = {"rec": 5, "rec_yd": 50, "made_up_stat": 9999}
    assert score_stat_line(line, SLEEPER_DEFAULT_PPR) == 10.0  # 5 + 5.0


def test_league_from_sleeper_payload_roundtrip():
    payload = {
        "name": "Zev's League",
        "scoring_settings": {"rec": 1.0, "pass_td": 4, "rec_yd": 0.1, "rush_td": 6},
        "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
    }
    league = league_from_sleeper(payload)
    assert league.ppr == 1.0
    assert league.is_superflex is True
    line = {"rec": 3, "rec_yd": 40, "rush_td": 1}
    assert score_stat_line(line, league) == 13.0  # 3 + 4.0 + 6


def test_explain_score_is_sorted_and_complete():
    line = {"rec": 8, "rec_yd": 112, "rec_td": 1}
    rows = explain_score(line, SLEEPER_DEFAULT_PPR)
    contributions = {k: c for k, _, _, c in rows}
    assert contributions["rec_yd"] == 11.2
    assert contributions["rec_td"] == 6.0
    assert contributions["rec"] == 8.0
    # Sorted by descending |contribution|.
    assert [r[3] for r in rows] == sorted((r[3] for r in rows), key=abs, reverse=True)
