"""Draft simulator + availability model (Phase 4).

The simulator answers the draft-day question valuation alone cannot:

    "Can I wait on this player, or will the room take him before my next pick?"

Opponents are modeled as ADP-plus-noise for v0. That is deliberately simple: it
is deterministic under a seed, testable with tiny fixtures, and good enough to
wire the rest of the Recommendation Object before Zev-specific modeling exists.
"""

from __future__ import annotations

import random

from ffdraft.config import settings
from ffdraft.valuation import PlayerValuation

from .models import AvailabilityResult, DraftState, PickScore


def snake_pick_order(num_teams: int, rounds: int) -> tuple[int, ...]:
    """Return 1-based team slots for every overall pick in a snake draft."""
    if num_teams <= 0:
        raise ValueError("num_teams must be positive")
    if rounds <= 0:
        raise ValueError("rounds must be positive")

    order: list[int] = []
    forward = list(range(1, num_teams + 1))
    backward = list(range(num_teams, 0, -1))
    for round_idx in range(rounds):
        order.extend(forward if round_idx % 2 == 0 else backward)
    return tuple(order)


def team_at_pick(overall_pick: int, num_teams: int) -> int:
    """Return the 1-based team slot that owns `overall_pick`."""
    if overall_pick <= 0:
        raise ValueError("overall_pick must be 1-based")
    round_idx = (overall_pick - 1) // num_teams
    slot_in_round = (overall_pick - 1) % num_teams + 1
    if round_idx % 2 == 0:
        return slot_in_round
    return num_teams - slot_in_round + 1


def next_pick_for_team(
    *,
    current_pick: int,
    team_slot: int,
    num_teams: int,
    rounds: int,
    include_current: bool = True,
) -> int | None:
    """Return the next overall pick for `team_slot`, or None if draft is over."""
    if current_pick <= 0:
        raise ValueError("current_pick must be 1-based")
    if not 1 <= team_slot <= num_teams:
        raise ValueError("team_slot must be between 1 and num_teams")

    total_picks = num_teams * rounds
    start = current_pick if include_current else current_pick + 1
    for pick_no in range(start, total_picks + 1):
        if team_at_pick(pick_no, num_teams) == team_slot:
            return pick_no
    return None


def next_user_pick_after_current(state: DraftState) -> int | None:
    """Return the user's next pick after the current decision point.

    If it is currently the user's turn, this returns the following user pick.
    Otherwise it returns the user's upcoming pick from the current board state.
    """
    is_user_turn = team_at_pick(state.current_pick, state.num_teams) == state.user_slot
    return next_pick_for_team(
        current_pick=state.current_pick,
        team_slot=state.user_slot,
        num_teams=state.num_teams,
        rounds=state.rounds,
        include_current=not is_user_turn,
    )


def _market_rank(player: PlayerValuation) -> float:
    return float(player.adp if player.adp is not None else player.overall_rank)


def _choose_opponent_pick(
    available: dict[str, PlayerValuation],
    rng: random.Random,
    *,
    noise_stdev: float,
) -> str:
    """Choose one opponent pick by lowest sampled market rank."""
    if not available:
        raise ValueError("cannot choose from an empty player pool")

    def sampled_rank(player: PlayerValuation) -> tuple[float, float, str]:
        noise = rng.gauss(0.0, noise_stdev) if noise_stdev > 0 else 0.0
        return (_market_rank(player) + noise, _market_rank(player), player.player_id)

    return min(available.values(), key=sampled_rank).player_id


def estimate_availability(
    state: DraftState,
    board: list[PlayerValuation],
    *,
    simulations: int = 1000,
    seed: int = settings.random_seed,
    noise_stdev: float = 8.0,
    top_n: int | None = None,
) -> list[AvailabilityResult]:
    """Estimate each available player's chance to survive to the user's next pick.

    The current pick is treated as a decision point. If the user is on the clock,
    simulations start with the next opponent pick and stop just before the user's
    following pick. This models "what happens if I pass on this player now?"
    """
    if simulations <= 0:
        raise ValueError("simulations must be positive")

    drafted = state.drafted_player_ids
    simulation_board = [p for p in board if p.player_id not in drafted]
    candidate_board = simulation_board[:top_n] if top_n is not None else simulation_board

    next_user_pick = next_user_pick_after_current(state)
    if next_user_pick is None:
        return [
            AvailabilityResult(
                player_id=p.player_id,
                name=p.name,
                position=p.position,
                survival_probability=1.0,
                next_user_pick=None,
                simulations=simulations,
            )
            for p in candidate_board
        ]

    is_user_turn = team_at_pick(state.current_pick, state.num_teams) == state.user_slot
    start_pick = state.current_pick + 1 if is_user_turn else state.current_pick
    candidate_ids = [p.player_id for p in candidate_board]
    survival_counts = dict.fromkeys(candidate_ids, 0)

    for sim_idx in range(simulations):
        rng = random.Random(seed + sim_idx)
        available = {p.player_id: p for p in simulation_board}
        for pick_no in range(start_pick, next_user_pick):
            if not available:
                break
            if team_at_pick(pick_no, state.num_teams) == state.user_slot:
                continue
            selected_id = _choose_opponent_pick(available, rng, noise_stdev=noise_stdev)
            del available[selected_id]

        for player_id in candidate_ids:
            if player_id in available:
                survival_counts[player_id] += 1

    by_id = {p.player_id: p for p in candidate_board}
    return [
        AvailabilityResult(
            player_id=player_id,
            name=by_id[player_id].name,
            position=by_id[player_id].position,
            survival_probability=round(survival_counts[player_id] / simulations, 4),
            next_user_pick=next_user_pick,
            simulations=simulations,
        )
        for player_id in candidate_ids
    ]


def rank_pick_options(
    board: list[PlayerValuation],
    availability: list[AvailabilityResult],
    *,
    roster_need_by_position: dict[str, float] | None = None,
    top_n: int | None = None,
) -> list[PickScore]:
    """Rank current pick candidates from valuation plus availability risk."""
    need = roster_need_by_position or {}
    availability_by_id = {a.player_id: a for a in availability}
    out: list[PickScore] = []

    for player in board:
        a = availability_by_id.get(player.player_id)
        if a is None:
            continue
        need_multiplier = float(need.get(player.position, 1.0))
        weighted_vorp = max(player.vorp, 0.0) * need_multiplier
        pass_risk = weighted_vorp * (1.0 - a.survival_probability)
        market_bonus = max(player.value_vs_adp or 0.0, 0.0) * 0.05
        score = weighted_vorp + pass_risk + market_bonus
        out.append(
            PickScore(
                player_id=player.player_id,
                name=player.name,
                position=player.position,
                score=round(score, 4),
                vorp=player.vorp,
                survival_probability=a.survival_probability,
                pass_risk=round(pass_risk, 4),
                value_vs_adp=player.value_vs_adp,
                next_user_pick=a.next_user_pick,
            )
        )

    out.sort(key=lambda row: (row.score, row.vorp, row.value_vs_adp or 0.0), reverse=True)
    if top_n is not None:
        return out[:top_n]
    return out
