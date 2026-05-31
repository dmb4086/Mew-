"""Tests for the Phase 4 draft simulator.

Fixtures are tiny and hand-computable: snake order, the next-pick calculation,
ADP-only opponent behavior with zero noise, and pick scoring from survival risk.
"""

from __future__ import annotations

from ffdraft.simulator import (
    AvailabilityResult,
    DraftState,
    estimate_availability,
    next_pick_for_team,
    next_user_pick_after_current,
    rank_pick_options,
    snake_pick_order,
    team_at_pick,
)
from ffdraft.valuation import PlayerValuation


def _val(i: int, *, vorp: float | None = None, adp: float | None = None) -> PlayerValuation:
    return PlayerValuation(
        player_id=f"p{i}",
        name=f"Player {i}",
        position="RB" if i % 2 else "WR",
        proj_points=100.0 - i,
        replacement_level=50.0,
        vorp=float(50 - i if vorp is None else vorp),
        pos_rank=i,
        overall_rank=i,
        tier=1 if i <= 3 else 2,
        adp=float(i if adp is None else adp),
    )


def test_snake_pick_order_and_team_at_pick():
    assert snake_pick_order(num_teams=4, rounds=3) == (
        1, 2, 3, 4,
        4, 3, 2, 1,
        1, 2, 3, 4,
    )
    assert team_at_pick(1, 4) == 1
    assert team_at_pick(5, 4) == 4
    assert team_at_pick(8, 4) == 1
    assert team_at_pick(10, 4) == 2


def test_next_pick_for_team_handles_current_pick():
    assert next_pick_for_team(
        current_pick=2, team_slot=2, num_teams=4, rounds=3, include_current=True
    ) == 2
    assert next_pick_for_team(
        current_pick=2, team_slot=2, num_teams=4, rounds=3, include_current=False
    ) == 7
    assert next_pick_for_team(
        current_pick=12, team_slot=1, num_teams=4, rounds=3, include_current=True
    ) is None


def test_next_user_pick_after_current_skips_current_turn():
    # Team 1 is on the clock at pick 1, so the relevant next pick is the return
    # trip at pick 8.
    state = DraftState(num_teams=4, rounds=2, user_slot=1, current_pick=1)
    assert next_user_pick_after_current(state) == 8

    # If Team 1 is waiting at pick 3, the upcoming pick 8 is still the target.
    waiting = DraftState(num_teams=4, rounds=2, user_slot=1, current_pick=3)
    assert next_user_pick_after_current(waiting) == 8


def test_zero_noise_adp_opponents_make_survival_hand_computable():
    board = [_val(i) for i in range(1, 9)]
    state = DraftState(num_teams=4, rounds=2, user_slot=1, current_pick=1)

    results = estimate_availability(
        state,
        board,
        simulations=5,
        seed=17,
        noise_stdev=0.0,
    )
    by_id = {r.player_id: r for r in results}

    # Picks 2-7 are opponents before Team 1's next turn at pick 8. With zero
    # noise, they take ADP ranks 1-6, so only p7/p8 survive.
    assert by_id["p1"].survival_probability == 0.0
    assert by_id["p6"].survival_probability == 0.0
    assert by_id["p7"].survival_probability == 1.0
    assert by_id["p8"].survival_probability == 1.0
    assert by_id["p1"].next_user_pick == 8


def test_availability_is_deterministic_with_seeded_noise():
    board = [_val(i) for i in range(1, 13)]
    state = DraftState(num_teams=4, rounds=3, user_slot=2, current_pick=2)

    first = estimate_availability(state, board, simulations=25, seed=99, noise_stdev=3.0)
    second = estimate_availability(state, board, simulations=25, seed=99, noise_stdev=3.0)

    assert first == second


def test_rank_pick_options_rewards_cost_of_passing():
    likely_gone = _val(1, vorp=40.0, adp=1.0)
    likely_available = _val(2, vorp=40.0, adp=2.0)
    board = [likely_gone, likely_available]
    availability = [
        # Same VORP, different survival odds. The player who will not make it
        # back gets the higher score.
        AvailabilityResult(
            player_id="p1",
            name="Player 1",
            position="RB",
            survival_probability=0.1,
            next_user_pick=8,
            simulations=10,
        ),
        AvailabilityResult(
            player_id="p2",
            name="Player 2",
            position="WR",
            survival_probability=0.9,
            next_user_pick=8,
            simulations=10,
        ),
    ]

    scores = rank_pick_options(board, availability)

    assert scores[0].player_id == "p1"
    assert scores[0].pass_risk == 36.0
    assert scores[1].pass_risk == 4.0
