"""Tests for the Phase 3 draft backtest harness."""

from __future__ import annotations

from ffdraft.backtest import DraftedRoster, backtest_strategy, score_roster_starters
from ffdraft.backtest.engine import simulate_strategy_draft
from ffdraft.valuation import PlayerValuation


def _player(
    idx: int,
    *,
    pos: str,
    vorp: float,
    adp: float,
    proj: float | None = None,
) -> PlayerValuation:
    return PlayerValuation(
        player_id=f"p{idx}",
        name=f"Player {idx}",
        position=pos,
        proj_points=float(proj if proj is not None else 100 - idx),
        replacement_level=50.0,
        vorp=vorp,
        pos_rank=idx,
        overall_rank=idx,
        tier=1,
        adp=adp,
    )


def test_strategy_draft_uses_vorp_for_user_pick():
    board = [
        _player(1, pos="RB", vorp=1.0, adp=1.0),
        _player(2, pos="WR", vorp=50.0, adp=2.0),
    ]

    adp_roster = simulate_strategy_draft(
        board,
        strategy="adp",
        user_slot=1,
        num_teams=2,
        rounds=1,
        opponent_noise_stdev=0.0,
    )
    vorp_roster = simulate_strategy_draft(
        board,
        strategy="vorp",
        user_slot=1,
        num_teams=2,
        rounds=1,
        opponent_noise_stdev=0.0,
    )

    assert adp_roster.player_ids == ("p1",)
    assert vorp_roster.player_ids == ("p2",)


def test_value_strategy_waits_on_vorp_that_market_expects_to_survive():
    board = [
        _player(1, pos="RB", vorp=30.0, adp=1.0),
        _player(2, pos="WR", vorp=50.0, adp=6.0),
        _player(3, pos="TE", vorp=20.0, adp=2.0),
        _player(4, pos="QB", vorp=10.0, adp=3.0),
    ]

    roster = simulate_strategy_draft(
        board,
        strategy="value",
        user_slot=1,
        num_teams=4,
        rounds=2,
        opponent_noise_stdev=0.0,
    )

    # Team 1's next pick is 8, so both p1 and p2 are market-risk candidates.
    assert roster.player_ids[0] == "p2"

    patient_roster = simulate_strategy_draft(
        board,
        strategy="value",
        user_slot=1,
        num_teams=2,
        rounds=2,
        opponent_noise_stdev=0.0,
    )

    # With a quick turn at pick 4, p2's ADP says he should survive, so the model
    # takes the scarcer near-term value first.
    assert patient_roster.player_ids[0] == "p1"


def test_adp_guard_gets_same_early_rb_guardrail_as_value_strategy():
    board = [
        _player(1, pos="WR", vorp=50.0, adp=1.0),
        _player(2, pos="RB", vorp=10.0, adp=2.0),
    ]

    plain_adp = simulate_strategy_draft(
        board,
        strategy="adp",
        user_slot=1,
        num_teams=12,
        rounds=10,
        opponent_noise_stdev=0.0,
    )
    guarded_adp = simulate_strategy_draft(
        board,
        strategy="adp_guard",
        user_slot=1,
        num_teams=12,
        rounds=10,
        opponent_noise_stdev=0.0,
    )

    assert plain_adp.player_ids[0] == "p1"
    assert guarded_adp.player_ids[0] == "p2"


def test_value_no_guard_is_a_true_ablation_of_roster_guardrails():
    board = [
        _player(1, pos="WR", vorp=50.0, adp=1.0),
        _player(2, pos="RB", vorp=10.0, adp=2.0),
    ]

    unguarded = simulate_strategy_draft(
        board,
        strategy="value_no_guard",
        user_slot=1,
        num_teams=12,
        rounds=10,
        opponent_noise_stdev=0.0,
    )
    guarded = simulate_strategy_draft(
        board,
        strategy="value",
        user_slot=1,
        num_teams=12,
        rounds=10,
        opponent_noise_stdev=0.0,
    )

    assert unguarded.player_ids[0] == "p1"
    assert guarded.player_ids[0] == "p2"


def test_value_market_rb_uses_market_order_inside_forced_rb_guardrail():
    board = [
        _player(1, pos="RB", vorp=10.0, adp=1.0),
        _player(2, pos="RB", vorp=50.0, adp=2.0),
        _player(3, pos="WR", vorp=60.0, adp=3.0),
    ]

    value = simulate_strategy_draft(
        board,
        strategy="value",
        user_slot=1,
        num_teams=12,
        rounds=10,
        opponent_noise_stdev=0.0,
    )
    anchored = simulate_strategy_draft(
        board,
        strategy="value_market_rb",
        user_slot=1,
        num_teams=12,
        rounds=10,
        opponent_noise_stdev=0.0,
    )

    assert value.player_ids[0] == "p2"
    assert anchored.player_ids[0] == "p1"


def test_score_roster_starters_uses_best_legal_lineup():
    board = [
        _player(1, pos="QB", vorp=1, adp=1),
        _player(2, pos="RB", vorp=1, adp=2),
        _player(3, pos="RB", vorp=1, adp=3),
        _player(4, pos="RB", vorp=1, adp=4),
        _player(5, pos="WR", vorp=1, adp=5),
        _player(6, pos="WR", vorp=1, adp=6),
        _player(7, pos="TE", vorp=1, adp=7),
        _player(8, pos="TE", vorp=1, adp=8),
    ]
    actual = {
        "p1": 300.0,
        "p2": 200.0,
        "p3": 190.0,
        "p4": 180.0,
        "p5": 210.0,
        "p6": 205.0,
        "p7": 100.0,
        "p8": 90.0,
    }

    score = score_roster_starters(
        DraftedRoster(team_slot=1, player_ids=tuple(player.player_id for player in board)),
        board,
        actual,
    )

    # QB + RB/RB + WR/WR + TE + FLEX, where FLEX chooses the remaining RB.
    assert score.points == 1385.0
    assert score.starter_ids == ("p1", "p2", "p3", "p7", "p5", "p6", "p4")


def test_backtest_strategy_returns_scored_result():
    board = [
        _player(1, pos="QB", vorp=50, adp=1),
        _player(2, pos="RB", vorp=40, adp=2),
        _player(3, pos="WR", vorp=30, adp=3),
    ]
    result = backtest_strategy(
        season=2024,
        board=board,
        actual_points={"p1": 300.0, "p2": 200.0, "p3": 100.0},
        strategy="vorp",
        user_slot=1,
        seed=7,
        num_teams=2,
        rounds=1,
        opponent_noise_stdev=0.0,
    )

    assert result.season == 2024
    assert result.strategy == "vorp"
    assert result.roster.player_ids == ("p1",)
    assert result.starter_points == 300.0
