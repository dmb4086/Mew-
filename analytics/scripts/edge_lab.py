"""Run the Edge Lab benchmark gauntlet.

This is stricter than the Phase 3 trust gate. It asks whether the current
strategy still wins after giving ADP the same roster-construction guardrails.

Usage:
    PYTHONPATH=. python -m scripts.edge_lab
    PYTHONPATH=. python -m scripts.edge_lab --seeds-per-slot 25 --enforce-edge
"""

from __future__ import annotations

import argparse
from statistics import mean

from ffdraft.adp import load_ffc_adp
from ffdraft.backtest import BacktestResult, backtest_strategy
from ffdraft.backtest.models import DraftStrategy
from ffdraft.config import settings
from ffdraft.identity import IdentityResolver
from ffdraft.nflverse import load_player_ids, load_seasonal_stats
from ffdraft.projections import build_internal_projections
from ffdraft.scoring import SLEEPER_DEFAULT_PPR
from ffdraft.valuation import value_players

_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}
_DEFAULT_STRATEGIES: tuple[DraftStrategy, ...] = (
    "adp",
    "adp_guard",
    "vorp",
    "value_no_guard",
    "value",
    "value_market_rb",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seasons", nargs="*", type=int, default=settings.seasons)
    parser.add_argument("--seeds-per-slot", type=int, default=25)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--opponent-noise", type=float, default=8.0)
    parser.add_argument("--candidate", choices=_DEFAULT_STRATEGIES, default="value_market_rb")
    parser.add_argument("--primary-baseline", choices=_DEFAULT_STRATEGIES, default="adp_guard")
    parser.add_argument("--enforce-edge", action="store_true")
    return parser.parse_args()


def _actual_points(seasonal_rows: list[dict[str, object]], season: int) -> dict[str, float]:
    return {
        str(row["player_id"]): float(row.get("fantasy_points_ppr") or 0.0)
        for row in seasonal_rows
        if int(row.get("season") or 0) == season
        and row.get("position") in _DRAFTABLE_POSITIONS
        and float(row.get("fantasy_points_ppr") or 0.0) > 0.0
    }


def _summarize(results: list[BacktestResult]) -> dict[str, float | int]:
    return {
        "drafts": len(results),
        "avg": round(mean(r.starter_points for r in results), 2),
    }


def _compare(
    candidate: list[BacktestResult],
    baseline: list[BacktestResult],
) -> dict[str, float | int]:
    if len(candidate) != len(baseline):
        raise ValueError("candidate and baseline results must be matched")
    diffs = [
        cand.starter_points - base.starter_points
        for cand, base in zip(candidate, baseline)
    ]
    return {
        "drafts": len(diffs),
        "avg_diff": round(mean(diffs), 2),
        "h2h_win_rate": round(sum(1 for diff in diffs if diff > 0) / len(diffs), 4),
        "ties": sum(1 for diff in diffs if diff == 0),
    }


def _run_season(
    *,
    season: int,
    seasonal_rows: list[dict[str, object]],
    resolver: IdentityResolver,
    strategies: tuple[DraftStrategy, ...],
    seeds_per_slot: int,
    rounds: int,
    teams: int,
    opponent_noise: float,
) -> dict[DraftStrategy, list[BacktestResult]]:
    _, adp_players = load_ffc_adp(year=season, scoring="ppr", teams=teams, position="all")
    projections = build_internal_projections(
        target_season=season,
        adp_players=adp_players,
        seasonal_rows=seasonal_rows,
        resolver=resolver,
    )
    board = value_players(projections, SLEEPER_DEFAULT_PPR, num_teams=teams)
    actual_points = _actual_points(seasonal_rows, season)

    results: dict[DraftStrategy, list[BacktestResult]] = {s: [] for s in strategies}
    for slot in range(1, teams + 1):
        for seed_idx in range(seeds_per_slot):
            seed = season * 10_000 + slot * 100 + seed_idx
            common = {
                "season": season,
                "board": board,
                "actual_points": actual_points,
                "user_slot": slot,
                "seed": seed,
                "num_teams": teams,
                "rounds": rounds,
                "opponent_noise_stdev": opponent_noise,
            }
            for strategy in strategies:
                results[strategy].append(backtest_strategy(strategy=strategy, **common))
    return results


def main() -> None:
    args = _parse_args()
    if args.seeds_per_slot <= 0:
        raise ValueError("--seeds-per-slot must be positive")

    seasons = list(args.seasons)
    strategies = _DEFAULT_STRATEGIES
    history_seasons = list(range(min(seasons) - 2, max(seasons) + 1))
    seasonal_rows = load_seasonal_stats(history_seasons).to_dicts()
    resolver = IdentityResolver(load_player_ids().to_dicts())

    all_results: dict[DraftStrategy, list[BacktestResult]] = {s: [] for s in strategies}
    season_results: dict[int, dict[DraftStrategy, list[BacktestResult]]] = {}

    print(
        f"Edge Lab: {args.teams} teams, {args.rounds} rounds, "
        f"{args.seeds_per_slot} seeds/slot, noise={args.opponent_noise}"
    )
    print(
        f"Candidate: {args.candidate}; primary baseline: {args.primary_baseline}"
    )
    print()

    for season in seasons:
        by_strategy = _run_season(
            season=season,
            seasonal_rows=seasonal_rows,
            resolver=resolver,
            strategies=strategies,
            seeds_per_slot=args.seeds_per_slot,
            rounds=args.rounds,
            teams=args.teams,
            opponent_noise=args.opponent_noise,
        )
        season_results[season] = by_strategy
        for strategy, rows in by_strategy.items():
            all_results[strategy].extend(rows)

        cand = by_strategy[args.candidate]
        base = by_strategy[args.primary_baseline]
        comparison = _compare(cand, base)
        print(
            f"  {season}: {args.candidate} vs {args.primary_baseline} "
            f"diff {comparison['avg_diff']:+}, "
            f"H2H {comparison['h2h_win_rate']:.1%}, "
            f"drafts {comparison['drafts']}"
        )

    print()
    print("Strategy averages:")
    for strategy in strategies:
        summary = _summarize(all_results[strategy])
        print(f"  {strategy:14} avg {summary['avg']}, drafts {summary['drafts']}")

    print()
    print(f"Candidate comparisons ({args.candidate}):")
    primary_season_wins = 0
    primary_h2h = 0.0
    for baseline in strategies:
        if baseline == args.candidate:
            continue
        comparison = _compare(all_results[args.candidate], all_results[baseline])
        season_wins = sum(
            1
            for season in seasons
            if float(
                _compare(
                    season_results[season][args.candidate],
                    season_results[season][baseline],
                )["avg_diff"]
            )
            > 0.0
        )
        if baseline == args.primary_baseline:
            primary_season_wins = season_wins
            primary_h2h = float(comparison["h2h_win_rate"])
        print(
            f"  vs {baseline:14} diff {comparison['avg_diff']:+}, "
            f"H2H {comparison['h2h_win_rate']:.1%}, "
            f"season wins {season_wins}/{len(seasons)}"
        )

    edge_passed = primary_season_wins >= 4 and primary_h2h > 0.55
    print()
    print(f"Edge gate vs {args.primary_baseline}: {'PASS' if edge_passed else 'FAIL'}")
    if args.enforce_edge and not edge_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
