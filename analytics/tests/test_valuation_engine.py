"""Tests for the Phase 2 valuation engine.

Crafted, hand-computable fixtures so replacement levels, the flex-deepening
effect, VORP, and tier/cliff detection are all verifiable by inspection — no
network, no database, fully deterministic.
"""

from __future__ import annotations

from dataclasses import replace

from ffdraft.scoring.league import SLEEPER_DEFAULT_PPR
from ffdraft.valuation import (
    PlayerProjection,
    assign_tiers,
    compute_replacement_levels,
    starter_demand,
    value_players,
)


def _proj(pid, name, pos, pts, adp=None):
    return PlayerProjection(player_id=pid, name=name, position=pos, proj_points=pts, adp=adp)


def _make_pool():
    rbs = [_proj(f"rb{i}", f"RB{i}", "RB", pts) for i, pts in
           enumerate([200, 190, 180, 170, 160, 150, 140, 130], 1)]
    wrs = [_proj(f"wr{i}", f"WR{i}", "WR", pts) for i, pts in
           enumerate([195, 185, 175, 165, 155, 145, 135, 125], 1)]
    tes = [_proj(f"te{i}", f"TE{i}", "TE", pts) for i, pts in
           enumerate([150, 120, 100, 90], 1)]
    qbs = [_proj(f"qb{i}", f"QB{i}", "QB", pts) for i, pts in
           enumerate([300, 290, 280, 270], 1)]
    return rbs + wrs + tes + qbs


def test_starter_demand_standard_12_team():
    demand = starter_demand(SLEEPER_DEFAULT_PPR.roster_positions, num_teams=12)
    assert demand["QB"] == 12
    assert demand["RB"] == 24   # two RB slots * 12
    assert demand["WR"] == 24
    assert demand["TE"] == 12
    # FLEX is not a dedicated position and must be excluded here.
    assert "FLEX" not in demand


def test_flex_deepens_replacement_level():
    pool = _make_pool()
    repl = compute_replacement_levels(pool, SLEEPER_DEFAULT_PPR, num_teams=2)
    # Dedicated: 4 RB, 4 WR, 2 TE, 2 QB starters. Then 2 FLEX slots greedily take
    # RB5 (160) and WR5 (155). So replacement = first true bench at each pos:
    assert repl["RB"] == 150   # RB6, because the flex consumed RB5
    assert repl["WR"] == 145   # WR6, because the flex consumed WR5
    assert repl["TE"] == 100   # TE3 (no flex went to TE)
    assert repl["QB"] == 280   # QB3


def test_vorp_and_overall_ranking():
    pool = _make_pool()
    vals = value_players(pool, SLEEPER_DEFAULT_PPR, num_teams=2)
    by_id = {v.player_id: v for v in vals}
    assert by_id["rb1"].vorp == 50.0   # 200 - 150
    assert by_id["wr1"].vorp == 50.0   # 195 - 145
    assert by_id["te1"].vorp == 50.0   # 150 - 100
    assert by_id["qb1"].vorp == 20.0   # 300 - 280  (QBs are shallow here)
    # Output is sorted by descending VORP and overall_rank agrees.
    assert vals[0].overall_rank == 1
    assert [v.overall_rank for v in vals] == sorted(v.overall_rank for v in vals)
    # The shallow QB, despite the highest raw points, is NOT the top overall.
    assert by_id["qb1"].overall_rank > by_id["rb1"].overall_rank


def test_value_vs_adp_flags_market_gaps():
    pool = _make_pool()
    # Give rb1 a late ADP -> the market underrates a top-VORP player.
    pool = [replace(p, adp=30.0) if p.player_id == "rb1" else p for p in pool]
    vals = value_players(pool, SLEEPER_DEFAULT_PPR, num_teams=2)
    rb1 = next(v for v in vals if v.player_id == "rb1")
    assert rb1.overall_rank == 1
    assert rb1.value_vs_adp == 29.0   # ADP 30 - overall rank 1


def test_tier_cliff_detection():
    # One obvious cliff between the 96 and 60 clusters.
    values = [100.0, 98.0, 96.0, 60.0, 58.0, 56.0]
    assert assign_tiers(values, z=1.0) == [1, 1, 1, 2, 2, 2]


def test_flat_values_are_one_tier():
    assert assign_tiers([10.0, 9.0, 8.0, 7.0], z=1.0) == [1, 1, 1, 1]


def test_tier_edge_cases():
    assert assign_tiers([]) == []
    assert assign_tiers([42.0]) == [1]
