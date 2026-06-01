"""Historical draft/roster backtesting utilities (Phase 3).

This module intentionally scores what a strategy drafts, not how pretty its
rankings look. It simulates a full snake draft, builds the user's roster, then
scores the best legal starting lineup against actual season points.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping

from ffdraft.scoring import LeagueScoring
from ffdraft.scoring.league import SLEEPER_DEFAULT_PPR
from ffdraft.simulator import next_pick_for_team, snake_pick_order
from ffdraft.valuation import PlayerValuation, starter_demand
from ffdraft.valuation.engine import FLEX_ELIGIBILITY

from .models import BacktestResult, DraftStrategy, DraftedRoster, StarterScore

_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}
_DEFAULT_MAX_BY_POSITION = {
    "QB": 2,
    "RB": 6,
    "WR": 6,
    "TE": 2,
}


def simulate_strategy_draft(
    board: list[PlayerValuation],
    *,
    strategy: DraftStrategy,
    user_slot: int,
    num_teams: int = 12,
    rounds: int = 12,
    seed: int = 0,
    opponent_noise_stdev: float = 8.0,
    max_by_position: Mapping[str, int] | None = None,
) -> DraftedRoster:
    """Simulate a draft and return the user's roster.

    Opponents draft by ADP plus optional seeded Gaussian noise. The user follows
    either strict ADP or projected VORP. Position caps prevent pathological
    roster shapes while staying simple enough for historical sweeps.
    """
    if not 1 <= user_slot <= num_teams:
        raise ValueError("user_slot must be between 1 and num_teams")
    if rounds <= 0:
        raise ValueError("rounds must be positive")

    limits = _normalized_limits(max_by_position)
    rng = random.Random(seed)
    available = {
        player.player_id: player
        for player in board
        if player.position in _DRAFTABLE_POSITIONS
    }
    player_by_id = dict(available)
    rosters: dict[int, list[str]] = defaultdict(list)

    for overall_pick, team_slot in enumerate(snake_pick_order(num_teams, rounds), start=1):
        if not available:
            break
        pick_strategy = strategy if team_slot == user_slot else "adp"
        selected_id = _choose_player(
            available,
            rosters[team_slot],
            player_by_id=player_by_id,
            strategy=pick_strategy,
            overall_pick=overall_pick,
            team_slot=team_slot,
            num_teams=num_teams,
            rounds=rounds,
            rng=rng,
            opponent_noise_stdev=opponent_noise_stdev if team_slot != user_slot else 0.0,
            max_by_position=limits,
        )
        if selected_id is None:
            break
        rosters[team_slot].append(selected_id)
        del available[selected_id]

    return DraftedRoster(team_slot=user_slot, player_ids=tuple(rosters[user_slot]))


def score_roster_starters(
    roster: DraftedRoster,
    board: list[PlayerValuation],
    actual_points: Mapping[str, float],
    *,
    league: LeagueScoring = SLEEPER_DEFAULT_PPR,
) -> StarterScore:
    """Return the best legal starting-lineup score for a drafted roster."""
    by_id = {player.player_id: player for player in board}
    remaining_by_pos: dict[str, list[str]] = defaultdict(list)
    for player_id in roster.player_ids:
        player = by_id.get(player_id)
        if player is None:
            continue
        remaining_by_pos[player.position].append(player_id)

    for ids in remaining_by_pos.values():
        ids.sort(key=lambda player_id: actual_points.get(player_id, 0.0), reverse=True)

    starters: list[str] = []
    dedicated = {
        pos: count
        for pos, count in starter_demand(league.roster_positions, num_teams=1).items()
        if pos in _DRAFTABLE_POSITIONS
    }
    for pos in sorted(dedicated):
        for _ in range(dedicated[pos]):
            if remaining_by_pos[pos]:
                starters.append(remaining_by_pos[pos].pop(0))

    for eligibility in _flex_slots(league):
        best_id: str | None = None
        best_pos: str | None = None
        best_points = float("-inf")
        for pos in eligibility:
            if pos not in _DRAFTABLE_POSITIONS or not remaining_by_pos[pos]:
                continue
            candidate = remaining_by_pos[pos][0]
            points = actual_points.get(candidate, 0.0)
            if points > best_points:
                best_id = candidate
                best_pos = pos
                best_points = points
        if best_id is not None and best_pos is not None:
            starters.append(best_id)
            remaining_by_pos[best_pos].pop(0)

    total = sum(actual_points.get(player_id, 0.0) for player_id in starters)
    return StarterScore(points=round(total, 2), starter_ids=tuple(starters))


def backtest_strategy(
    *,
    season: int,
    board: list[PlayerValuation],
    actual_points: Mapping[str, float],
    strategy: DraftStrategy,
    user_slot: int,
    seed: int,
    num_teams: int = 12,
    rounds: int = 12,
    opponent_noise_stdev: float = 8.0,
    league: LeagueScoring = SLEEPER_DEFAULT_PPR,
) -> BacktestResult:
    """Run one full draft and score the user's resulting starters."""
    roster = simulate_strategy_draft(
        board,
        strategy=strategy,
        user_slot=user_slot,
        num_teams=num_teams,
        rounds=rounds,
        seed=seed,
        opponent_noise_stdev=opponent_noise_stdev,
    )
    score = score_roster_starters(roster, board, actual_points, league=league)
    return BacktestResult(
        season=season,
        strategy=strategy,
        user_slot=user_slot,
        seed=seed,
        starter_points=score.points,
        roster=roster,
        starters=score.starter_ids,
    )


def _choose_player(
    available: Mapping[str, PlayerValuation],
    roster_player_ids: list[str],
    *,
    player_by_id: Mapping[str, PlayerValuation],
    strategy: DraftStrategy,
    overall_pick: int,
    team_slot: int,
    num_teams: int,
    rounds: int,
    rng: random.Random,
    opponent_noise_stdev: float,
    max_by_position: Mapping[str, int],
) -> str | None:
    legal = [
        player
        for player in available.values()
        if _selected_position_count(roster_player_ids, player_by_id, player.position)
        < max_by_position[player.position]
    ]
    if not legal:
        legal = list(available.values())
    if not legal:
        return None

    if strategy == "vorp":
        return max(
            legal,
            key=lambda player: (
                player.vorp,
                player.proj_points,
                -(player.adp or 999.0),
                player.player_id,
            ),
        ).player_id

    if strategy == "value":
        next_pick = next_pick_for_team(
            current_pick=overall_pick,
            team_slot=team_slot,
            num_teams=num_teams,
            rounds=rounds,
            include_current=False,
        )
        if next_pick is None:
            candidates = legal
        else:
            # Draft the best value among players the market says are unlikely
            # to survive to the next turn. This is the backtest analogue of
            # Phase 4's pass-risk idea without running Monte Carlo at each pick.
            candidates = [
                player
                for player in legal
                if _market_rank(player) <= next_pick
            ] or legal

        # Positional roster-construction guardrails: avoid degenerate rosters
        # by forcing minimum RB picks early. This compensates for the fact
        # that our internal projections systematically undervalue RBs vs ADP
        # in some years (2019, 2024).
        current_round = (overall_pick - 1) // num_teams + 1
        rb_count = _selected_position_count(roster_player_ids, player_by_id, "RB")
        te_count = _selected_position_count(roster_player_ids, player_by_id, "TE")

        # Scale guardrails to draft size (calibrated for 12-team, 12-round).
        # Only apply in realistic-sized drafts (>= 8 teams, >= 10 rounds).
        if num_teams >= 8 and rounds >= 10:
            rb_urgency = num_teams / 12.0
            if current_round <= int(5 * rb_urgency) and rb_count < 1:
                rb_candidates = [p for p in candidates if p.position == "RB"]
                if rb_candidates:
                    return max(
                        rb_candidates,
                        key=lambda player: (
                            player.vorp,
                            player.value_vs_adp or 0.0,
                            player.proj_points,
                            -(player.adp or 999.0),
                            player.player_id,
                        ),
                    ).player_id
            if current_round <= int(8 * rb_urgency) and rb_count < 2:
                rb_candidates = [p for p in candidates if p.position == "RB"]
                if rb_candidates:
                    return max(
                        rb_candidates,
                        key=lambda player: (
                            player.vorp,
                            player.value_vs_adp or 0.0,
                            player.proj_points,
                            -(player.adp or 999.0),
                            player.player_id,
                        ),
                    ).player_id
            if current_round <= int(9 * rb_urgency) and te_count < 1:
                te_candidates = [p for p in candidates if p.position == "TE"]
                if te_candidates:
                    return max(
                        te_candidates,
                        key=lambda player: (
                            player.vorp,
                            player.value_vs_adp or 0.0,
                            player.proj_points,
                            -(player.adp or 999.0),
                            player.player_id,
                        ),
                    ).player_id

        return max(
            candidates,
            key=lambda player: (
                player.vorp,
                player.value_vs_adp or 0.0,
                player.proj_points,
                -(player.adp or 999.0),
                player.player_id,
            ),
        ).player_id

    if strategy != "adp":
        raise ValueError(f"unknown draft strategy: {strategy}")

    def market_key(player: PlayerValuation) -> tuple[float, float, str]:
        market_rank = _market_rank(player)
        noise = rng.gauss(0.0, opponent_noise_stdev) if opponent_noise_stdev > 0 else 0.0
        return (market_rank + noise, market_rank, player.player_id)

    return min(legal, key=market_key).player_id


def _market_rank(player: PlayerValuation) -> float:
    return float(player.adp if player.adp is not None else player.overall_rank)


def _selected_position_count(
    roster_player_ids: list[str],
    player_by_id: Mapping[str, PlayerValuation],
    position: str,
) -> int:
    return sum(1 for player_id in roster_player_ids if player_by_id[player_id].position == position)


def _flex_slots(league: LeagueScoring) -> list[tuple[str, ...]]:
    slots: list[tuple[str, ...]] = []
    for slot in league.roster_positions:
        token = slot.upper()
        if token in FLEX_ELIGIBILITY:
            slots.append(FLEX_ELIGIBILITY[token])
    slots.sort(key=lambda eligibility: (len(eligibility), eligibility))
    return slots


def _normalized_limits(max_by_position: Mapping[str, int] | None) -> Mapping[str, int]:
    limits = {**_DEFAULT_MAX_BY_POSITION}
    if max_by_position is not None:
        limits.update({pos: int(limit) for pos, limit in max_by_position.items()})
    missing = _DRAFTABLE_POSITIONS - set(limits)
    if missing:
        raise ValueError(f"missing max_by_position limits for: {sorted(missing)}")
    return limits
