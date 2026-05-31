"""Tests for the internal projection baseline."""

from __future__ import annotations

from ffdraft.adp import FFCAdpPlayer
from ffdraft.identity import IdentityResolver
from ffdraft.projections import build_internal_projections
from ffdraft.validation import spearman_rank_correlation


def test_internal_projection_blends_prior_player_and_market_curve():
    resolver = IdentityResolver(
        [
            {"gsis_id": "p1", "name": "A Back", "position": "RB"},
            {"gsis_id": "p2", "name": "B Back", "position": "RB"},
        ]
    )
    adp = [
        FFCAdpPlayer("1", "A Back", "RB", "CHI", 1.0, "1.01", 10),
        FFCAdpPlayer("2", "B Back", "RB", "CHI", 20.0, "2.08", 10),
    ]
    seasonal = [
        {"player_id": "p1", "player_name": "A Back", "position": "RB", "season": 2023,
         "games": 10, "fantasy_points_ppr": 100.0},
        {"player_id": "p2", "player_name": "B Back", "position": "RB", "season": 2023,
         "games": 17, "fantasy_points_ppr": 200.0},
    ]

    projections = build_internal_projections(
        target_season=2024,
        adp_players=adp,
        seasonal_rows=seasonal,
        resolver=resolver,
        player_weight=0.5,
    )
    by_id = {p.player_id: p for p in projections}

    assert by_id["p1"].proj_points > 0
    assert by_id["p1"].adp == 1.0
    # A Back has weaker personal history but a much stronger ADP market prior,
    # so the blended projection correctly pulls him above the better prior-year
    # producer.
    assert by_id["p1"].proj_points > by_id["p2"].proj_points


def test_spearman_rank_correlation_orders_shared_keys():
    assert spearman_rank_correlation(
        {"a": 3.0, "b": 2.0, "c": 1.0},
        {"a": 30.0, "b": 20.0, "c": 10.0},
    ) == 1.0
