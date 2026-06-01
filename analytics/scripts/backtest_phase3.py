"""Run the Phase 3 historical draft backtest gate.

The harness compares our model drafting strategy against strict ADP drafting in
matched historical rooms: same season, draft slot, and random seed.

Usage:
    PYTHONPATH=. python -m scripts.backtest_phase3
    PYTHONPATH=. python -m scripts.backtest_phase3 --seeds-per-slot 25 --enforce-gate
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seasons", nargs="*", type=int, default=settings.seasons)
    parser.add_argument("--seeds-per-slot", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--opponent-noise", type=float, default=8.0)
    parser.add_argument(
        "--strategy",
        choices=["vorp", "value_no_guard", "value", "value_market_rb"],
        default="value",
    )
    parser.add_argument("--enforce-gate", action="store_true")
    return parser.parse_args()


def _actual_points(seasonal_rows: list[dict[str, object]], season: int) -> dict[str, float]:
    return {
        str(row["player_id"]): float(row.get("fantasy_points_ppr") or 0.0)
        for row in seasonal_rows
        if int(row.get("season") or 0) == season
        and row.get("position") in _DRAFTABLE_POSITIONS
        and float(row.get("fantasy_points_ppr") or 0.0) > 0.0
    }


def _run_season(
    *,
    season: int,
    seasonal_rows: list[dict[str, object]],
    resolver: IdentityResolver,
    seeds_per_slot: int,
    rounds: int,
    teams: int,
    opponent_noise: float,
    strategy: DraftStrategy,
) -> tuple[list[BacktestResult], list[BacktestResult]]:
    _, adp_players = load_ffc_adp(year=season, scoring="ppr", teams=teams, position="all")
    projections = build_internal_projections(
        target_season=season,
        adp_players=adp_players,
        seasonal_rows=seasonal_rows,
        resolver=resolver,
    )
    board = value_players(projections, SLEEPER_DEFAULT_PPR, num_teams=teams)
    actual_points = _actual_points(seasonal_rows, season)

    adp_results: list[BacktestResult] = []
    vorp_results: list[BacktestResult] = []
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
            adp_results.append(backtest_strategy(strategy="adp", **common))
            vorp_results.append(backtest_strategy(strategy=strategy, **common))

    return adp_results, vorp_results


def _summarize_pairs(
    adp_results: list[BacktestResult],
    vorp_results: list[BacktestResult],
) -> dict[str, float | int]:
    if len(adp_results) != len(vorp_results):
        raise ValueError("strategy result sets must be matched")
    diffs = [
        vorp.starter_points - adp.starter_points
        for adp, vorp in zip(adp_results, vorp_results)
    ]
    return {
        "drafts": len(diffs),
        "adp_avg": round(mean(r.starter_points for r in adp_results), 2),
        "vorp_avg": round(mean(r.starter_points for r in vorp_results), 2),
        "avg_diff": round(mean(diffs), 2),
        "h2h_win_rate": round(sum(1 for diff in diffs if diff > 0) / len(diffs), 4),
        "ties": sum(1 for diff in diffs if diff == 0),
    }


def main() -> None:
    args = _parse_args()
    seasons = list(args.seasons)
    if args.seeds_per_slot <= 0:
        raise ValueError("--seeds-per-slot must be positive")

    history_seasons = list(range(min(seasons) - 2, max(seasons) + 1))
    seasonal_rows = load_seasonal_stats(history_seasons).to_dicts()
    resolver = IdentityResolver(load_player_ids().to_dicts())

    all_adp: list[BacktestResult] = []
    all_vorp: list[BacktestResult] = []
    season_wins = 0
    print(
        f"Phase 3 backtest: {args.strategy.upper()} strategy vs ADP-only "
        f"({args.teams} teams, {args.rounds} rounds, {args.seeds_per_slot} seeds/slot)"
    )

    for season in seasons:
        adp_results, vorp_results = _run_season(
            season=season,
            seasonal_rows=seasonal_rows,
            resolver=resolver,
            seeds_per_slot=args.seeds_per_slot,
            rounds=args.rounds,
            teams=args.teams,
            opponent_noise=args.opponent_noise,
            strategy=args.strategy,
        )
        summary = _summarize_pairs(adp_results, vorp_results)
        if float(summary["avg_diff"]) > 0:
            season_wins += 1
        all_adp.extend(adp_results)
        all_vorp.extend(vorp_results)
        label = args.strategy.upper()
        print(
            f"  {season}: ADP {summary['adp_avg']}, {label} {summary['vorp_avg']}, "
            f"diff {summary['avg_diff']:+}, H2H {summary['h2h_win_rate']:.1%}, "
            f"drafts {summary['drafts']}"
        )

    overall = _summarize_pairs(all_adp, all_vorp)
    print(
        "Overall: "
        f"ADP {overall['adp_avg']}, {args.strategy.upper()} {overall['vorp_avg']}, "
        f"diff {overall['avg_diff']:+}, H2H {overall['h2h_win_rate']:.1%}, "
        f"season wins {season_wins}/{len(seasons)}, drafts {overall['drafts']}"
    )

    gate_passed = season_wins >= 4 and float(overall["h2h_win_rate"]) > 0.55
    print(f"Gate: {'PASS' if gate_passed else 'FAIL'}")
    if args.enforce_gate and not gate_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
