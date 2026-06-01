#!/usr/bin/env python3
"""Analyze which picks made/broke the VALUE strategy each year."""
from __future__ import annotations

import argparse
import os
from collections import defaultdict

os.environ.setdefault("DATABASE_URL", "postgresql://dev1398@localhost:5432/ffdraft")

from ffdraft.adp import load_ffc_adp
from ffdraft.projections.baseline import build_internal_projections
from ffdraft.valuation import value_players
from ffdraft.backtest import backtest_strategy
from ffdraft.identity import IdentityResolver
from ffdraft.nflverse import load_player_ids, load_seasonal_stats
from ffdraft.scoring import SLEEPER_DEFAULT_PPR

_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}


def _actual_points(seasonal_rows: list[dict[str, object]], season: int) -> dict[str, float]:
    return {
        str(row["player_id"]): float(row.get("fantasy_points_ppr") or 0.0)
        for row in seasonal_rows
        if int(row.get("season") or 0) == season
        and row.get("position") in _DRAFTABLE_POSITIONS
        and float(row.get("fantasy_points_ppr") or 0.0) > 0.0
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--slot", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    resolver = IdentityResolver(load_player_ids().to_dicts())
    history_seasons = list(range(args.season - 2, args.season + 1))
    seasonal_rows = load_seasonal_stats(history_seasons).to_dicts()

    _, adp_players = load_ffc_adp(year=args.season, scoring="ppr", teams=12, position="all")
    projections = build_internal_projections(
        target_season=args.season,
        adp_players=adp_players,
        seasonal_rows=seasonal_rows,
        resolver=resolver,
    )
    board = value_players(projections, SLEEPER_DEFAULT_PPR, num_teams=12)
    actual_points = _actual_points(seasonal_rows, args.season)
    player_by_id = {p.player_id: p for p in board}

    # Run one VALUE draft
    value_result = backtest_strategy(
        season=args.season, board=board, actual_points=actual_points,
        user_slot=args.slot, seed=args.seed, num_teams=12, rounds=12,
        opponent_noise_stdev=0.0, strategy="value",
    )

    # Run one ADP draft
    adp_result = backtest_strategy(
        season=args.season, board=board, actual_points=actual_points,
        user_slot=args.slot, seed=args.seed, num_teams=12, rounds=12,
        opponent_noise_stdev=0.0, strategy="adp",
    )

    print(f"=== {args.season} Slot {args.slot} Seed {args.seed} ===")
    print(f"VALUE score: {value_result.starter_points:.1f}")
    print(f"ADP   score: {adp_result.starter_points:.1f}")
    print()

    value_pids = set(value_result.roster.player_ids)
    adp_pids = set(adp_result.roster.player_ids)

    only_value = [player_by_id[pid] for pid in (value_pids - adp_pids) if pid in player_by_id]
    only_adp = [player_by_id[pid] for pid in (adp_pids - value_pids) if pid in player_by_id]

    print(f"Players VALUE took instead of ADP ({len(only_value)}):")
    for p in sorted(only_value, key=lambda x: x.adp or 999):
        actual = actual_points.get(p.player_id, 0.0)
        print(f"  Rd {int(p.adp) // 12 + 1 if p.adp else '?'}. {p.name} ({p.position})  ADP:{p.adp:.1f}  PROJ:{p.proj_points:.1f}  ACTUAL:{actual:.1f}  VORP:{p.vorp:.1f}  VAL:{p.value_vs_adp:.1f}")

    print()
    print(f"Players ADP took instead of VALUE ({len(only_adp)}):")
    for p in sorted(only_adp, key=lambda x: x.adp or 999):
        actual = actual_points.get(p.player_id, 0.0)
        print(f"  Rd {int(p.adp) // 12 + 1 if p.adp else '?'}. {p.name} ({p.position})  ADP:{p.adp:.1f}  PROJ:{p.proj_points:.1f}  ACTUAL:{actual:.1f}  VORP:{p.vorp:.1f}  VAL:{p.value_vs_adp:.1f}")

    print()
    # Position breakdown
    pos_value = defaultdict(float)
    pos_adp = defaultdict(float)
    for pid in value_pids:
        p = player_by_id.get(pid)
        if p:
            pos_value[p.position] += actual_points.get(pid, 0.0)
    for pid in adp_pids:
        p = player_by_id.get(pid)
        if p:
            pos_adp[p.position] += actual_points.get(pid, 0.0)
    print("Position breakdown (actual points by position):")
    for pos in ["QB", "RB", "WR", "TE"]:
        print(f"  {pos}: VALUE {pos_value[pos]:.1f}  ADP {pos_adp[pos]:.1f}  diff {pos_value[pos]-pos_adp[pos]:+.1f}")


if __name__ == "__main__":
    main()
