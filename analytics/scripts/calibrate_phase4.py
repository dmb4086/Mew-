#!/usr/bin/env python3
"""Calibrate the Phase 4 availability model.

Measures whether predicted survival probabilities match empirical frequencies
across many draft scenarios. Computes reliability curve and Brier score.

Usage:
    PYTHONPATH=. .venv/bin/python -m scripts.calibrate_phase4
"""
from __future__ import annotations

import argparse
import os
import random
from collections import defaultdict
from statistics import mean

os.environ.setdefault("DATABASE_URL", "postgresql://dev1398@localhost:5432/ffdraft")

from ffdraft.adp import load_ffc_adp
from ffdraft.projections.baseline import build_internal_projections
from ffdraft.valuation import value_players
from ffdraft.simulator import estimate_availability, snake_pick_order, team_at_pick
from ffdraft.simulator.models import DraftState, DraftPick
from ffdraft.identity import IdentityResolver
from ffdraft.nflverse import load_player_ids, load_seasonal_stats
from ffdraft.scoring import SLEEPER_DEFAULT_PPR
from ffdraft.config import settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2023)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--scenarios", type=int, default=200)
    parser.add_argument("--sims-per-scenario", type=int, default=1000)
    parser.add_argument("--validation-sims", type=int, default=5000)
    parser.add_argument("--noise", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=settings.random_seed)
    return parser.parse_args()


def _sample_scenario_state(
    board: list,
    teams: int,
    rounds: int,
    rng: random.Random,
) -> DraftState:
    """Generate a random realistic draft state mid-draft."""
    user_slot = rng.randint(1, teams)
    # Pick a random point in the draft (not too early, not too late)
    total_picks = teams * rounds
    current_pick = rng.randint(teams + 1, total_picks - teams)

    # Simulate deterministic ADP draft up to current_pick - 1
    order = snake_pick_order(teams, rounds)
    available = {p.player_id: p for p in board}
    picks: list[DraftPick] = []
    for overall, slot in enumerate(order[: current_pick - 1], start=1):
        if not available:
            break
        best = min(available.values(), key=lambda p: (p.adp or 999, p.player_id))
        picks.append(DraftPick(overall_pick=overall, team_slot=slot, player_id=best.player_id))
        del available[best.player_id]

    return DraftState(
        num_teams=teams,
        rounds=rounds,
        user_slot=user_slot,
        current_pick=current_pick,
        picks=tuple(picks),
    )


def _empirical_survival(
    state: DraftState,
    board: list,
    player_id: str,
    validations: int,
    noise: float,
    seed: int,
) -> float:
    """Run independent simulations to get empirical survival frequency."""
    from ffdraft.simulator.engine import _choose_opponent_pick

    next_user = None
    from ffdraft.simulator.engine import next_user_pick_after_current
    next_user = next_user_pick_after_current(state)
    if next_user is None:
        return 1.0

    drafted = state.drafted_player_ids
    simulation_board = [p for p in board if p.player_id not in drafted]
    start_pick = state.current_pick + 1 if team_at_pick(state.current_pick, state.num_teams) == state.user_slot else state.current_pick

    survives = 0
    for v in range(validations):
        rng = random.Random(seed + 100000 + v)
        available = {p.player_id: p for p in simulation_board}
        for pick_no in range(start_pick, next_user):
            if not available:
                break
            if team_at_pick(pick_no, state.num_teams) == state.user_slot:
                continue
            selected = _choose_opponent_pick(available, rng, noise_stdev=noise)
            del available[selected]
        if player_id in available:
            survives += 1

    return survives / validations


def main() -> None:
    args = _parse_args()
    rng = random.Random(args.seed)

    print(f"Phase 4 calibration: {args.scenarios} scenarios, {args.sims_per_scenario} prediction sims, {args.validation_sims} validation sims")
    print(f"Season: {args.season}, teams: {args.teams}, rounds: {args.rounds}, noise: {args.noise}")
    print()

    resolver = IdentityResolver(load_player_ids().to_dicts())
    seasonal_rows = load_seasonal_stats(list(range(args.season - 2, args.season + 1))).to_dicts()
    _, adp_players = load_ffc_adp(year=args.season, scoring="ppr", teams=args.teams, position="all")
    projections = build_internal_projections(
        target_season=args.season,
        adp_players=adp_players,
        seasonal_rows=seasonal_rows,
        resolver=resolver,
    )
    board = value_players(projections, SLEEPER_DEFAULT_PPR, num_teams=args.teams)

    records: list[tuple[float, float]] = []  # (predicted_prob, empirical_freq)

    for scenario_idx in range(args.scenarios):
        state = _sample_scenario_state(board, args.teams, args.rounds, rng)
        avail = estimate_availability(
            state, board,
            simulations=args.sims_per_scenario,
            seed=args.seed + scenario_idx,
            noise_stdev=args.noise,
            top_n=15,
        )
        for a in avail:
            empirical = _empirical_survival(
                state, board, a.player_id,
                args.validation_sims, args.noise, args.seed + scenario_idx,
            )
            records.append((a.survival_probability, empirical))

        if (scenario_idx + 1) % 50 == 0:
            print(f"  Completed {scenario_idx + 1}/{args.scenarios} scenarios...")

    print()

    # Brier score
    brier = mean((pred - emp) ** 2 for pred, emp in records)
    print(f"Brier score: {brier:.4f} (lower is better, 0 = perfect)")

    # Reliability curve: bin predictions and compare to empirical frequencies
    bins: dict[str, list[float]] = defaultdict(list)
    for pred, emp in records:
        # Bin by predicted probability in 10% buckets
        bin_key = f"{int(pred * 10) * 10:02d}-{int(pred * 10) * 10 + 9:02d}%"
        bins[bin_key].append(emp)

    print()
    print("Reliability curve (predicted bin -> empirical frequency):")
    for bin_key in sorted(bins.keys(), key=lambda k: int(k.split("-")[0])):
        emps = bins[bin_key]
        avg_emp = mean(emps)
        print(f"  {bin_key}: n={len(emps):4d}, empirical={avg_emp:.3f}")

    # Calibration error (mean absolute difference between bin midpoint and empirical)
    cal_error = 0.0
    cal_count = 0
    for pred, emp in records:
        cal_error += abs(pred - emp)
        cal_count += 1
    mean_abs_error = cal_error / cal_count if cal_count else 0.0
    print()
    print(f"Mean absolute calibration error: {mean_abs_error:.4f}")


if __name__ == "__main__":
    main()
