#!/usr/bin/env python3
"""Sweep WR prior-production weight to find the best 2019 fix."""
from __future__ import annotations

import argparse
from statistics import mean

from ffdraft.adp import load_ffc_adp
from ffdraft.backtest import BacktestResult, backtest_strategy
from ffdraft.config import settings
from ffdraft.identity import IdentityResolver
from ffdraft.nflverse import load_player_ids, load_seasonal_stats
from ffdraft.projections.baseline import build_internal_projections
from ffdraft.scoring import SLEEPER_DEFAULT_PPR
from ffdraft.valuation import value_players

_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}


def _actual_points(seasonal_rows: list[dict[str, object]], season: int) -> dict[str, float]:
    return {
        str(row["player_id"]): float(row.get("fantasy_points_ppr") or 0.0)
        for row in seasonal_rows
        if int(row.get("season") or 0) == season
        and row.get("position") in _DRAFTABLE_POSITIONS
        and float(row.get("fantasy_points_ppr") or 0.0) > 0.0
    }


def run_weight(wr_w: float, seeds_per_slot: int, seasons: list[int]) -> dict:
    base_w = {"QB": 0.15, "RB": 0.05, "WR": wr_w, "TE": 0.05}
    history_seasons = list(range(min(seasons) - 2, max(seasons) + 1))
    seasonal_rows = load_seasonal_stats(history_seasons).to_dicts()
    resolver = IdentityResolver(load_player_ids().to_dicts())

    results = {"seasons": {}}
    all_cand: list[BacktestResult] = []
    all_base: list[BacktestResult] = []

    for season in seasons:
        _, adp_players = load_ffc_adp(year=season, scoring="ppr", teams=12, position="all")
        proj = build_internal_projections(
            target_season=season,
            adp_players=adp_players,
            seasonal_rows=seasonal_rows,
            resolver=resolver,
            player_weight=base_w,
        )
        board = value_players(proj, SLEEPER_DEFAULT_PPR, num_teams=12)
        actual = _actual_points(seasonal_rows, season)

        cand_results: list[BacktestResult] = []
        base_results: list[BacktestResult] = []
        for slot in range(1, 13):
            for seed_idx in range(seeds_per_slot):
                seed = season * 10_000 + slot * 100 + seed_idx
                common = {
                    "season": season,
                    "board": board,
                    "actual_points": actual,
                    "user_slot": slot,
                    "seed": seed,
                    "num_teams": 12,
                    "rounds": 12,
                    "opponent_noise_stdev": 8.0,
                }
                cand_results.append(backtest_strategy(strategy="value_market_rb", **common))
                base_results.append(backtest_strategy(strategy="adp_guard", **common))

        diffs = [c.starter_points - b.starter_points for c, b in zip(cand_results, base_results)]
        results["seasons"][season] = {
            "avg_diff": round(mean(diffs), 2),
            "h2h": round(sum(1 for d in diffs if d > 0) / len(diffs), 4),
            "drafts": len(diffs),
        }
        all_cand.extend(cand_results)
        all_base.extend(base_results)

    all_diffs = [c.starter_points - b.starter_points for c, b in zip(all_cand, all_base)]
    results["overall"] = {
        "avg_diff": round(mean(all_diffs), 2),
        "h2h": round(sum(1 for d in all_diffs if d > 0) / len(all_diffs), 4),
        "drafts": len(all_diffs),
        "season_wins": sum(1 for s in results["seasons"].values() if s["avg_diff"] > 0),
    }
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds-per-slot", type=int, default=25)
    parser.add_argument("--seasons", nargs="+", type=int, default=settings.seasons)
    args = parser.parse_args()

    print(f"WR weight sweep: {args.seeds_per_slot} seeds/slot, seasons={args.seasons}")
    print()

    for wr_w in [0.15, 0.25, 0.35, 0.45, 0.55]:
        print(f"WR weight = {wr_w:.2f}")
        res = run_weight(wr_w, args.seeds_per_slot, args.seasons)
        for season, data in res["seasons"].items():
            print(f"  {season}: diff {data['avg_diff']:+6.1f}, H2H {data['h2h']:.1%}")
        o = res["overall"]
        print(f"  OVERALL: diff {o['avg_diff']:+6.1f}, H2H {o['h2h']:.1%}, wins {o['season_wins']}/6")
        print()


if __name__ == "__main__":
    main()
