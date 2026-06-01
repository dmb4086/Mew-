"""Diagnose seasons where the Edge Lab candidate loses to the hard baseline.

The hard baseline is `adp_guard`: ADP drafting with the same roster guardrails
as the value strategies. This script compares paired drafts and shows where the
candidate gives points back by pick number, position, and player.

Usage:
    PYTHONPATH=. python -m scripts.edge_failure_modes 2019 2024
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean

from ffdraft.adp import load_ffc_adp
from ffdraft.backtest import BacktestResult, backtest_strategy, score_roster_starters
from ffdraft.identity import IdentityResolver
from ffdraft.nflverse import load_player_ids, load_seasonal_stats
from ffdraft.projections import build_internal_projections
from ffdraft.scoring import SLEEPER_DEFAULT_PPR
from ffdraft.valuation import PlayerValuation, value_players

_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}


@dataclass
class PlayerDelta:
    player_id: str
    name: str
    position: str
    count: int
    actual_points: float
    proj_points: float
    adp: float | None
    vorp: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seasons", nargs="*", type=int, default=[2019, 2024])
    parser.add_argument("--seeds-per-slot", type=int, default=25)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--opponent-noise", type=float, default=8.0)
    parser.add_argument("--candidate", default="value_market_rb")
    parser.add_argument("--baseline", default="adp_guard")
    parser.add_argument("--top", type=int, default=12)
    return parser.parse_args()


def _actual_points(seasonal_rows: list[dict[str, object]], season: int) -> dict[str, float]:
    return {
        str(row["player_id"]): float(row.get("fantasy_points_ppr") or 0.0)
        for row in seasonal_rows
        if int(row.get("season") or 0) == season
        and row.get("position") in _DRAFTABLE_POSITIONS
        and float(row.get("fantasy_points_ppr") or 0.0) > 0.0
    }


def _position_counts(result: BacktestResult, board_by_id: dict[str, PlayerValuation]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for player_id in result.roster.player_ids:
        player = board_by_id.get(player_id)
        if player:
            counts[player.position] += 1
    return counts


def _position_starter_points(
    result: BacktestResult,
    board_by_id: dict[str, PlayerValuation],
    actual_points: dict[str, float],
) -> dict[str, float]:
    by_pos: dict[str, float] = defaultdict(float)
    starters = score_roster_starters(result.roster, list(board_by_id.values()), actual_points)
    for player_id in starters.starter_ids:
        player = board_by_id.get(player_id)
        if player:
            by_pos[player.position] += actual_points.get(player_id, 0.0)
    return dict(by_pos)


def _player_deltas(
    counts: Counter[str],
    board_by_id: dict[str, PlayerValuation],
    actual_points: dict[str, float],
    top: int,
) -> list[PlayerDelta]:
    rows: list[PlayerDelta] = []
    for player_id, count in counts.items():
        player = board_by_id.get(player_id)
        if player is None:
            continue
        rows.append(
            PlayerDelta(
                player_id=player_id,
                name=player.name,
                position=player.position,
                count=count,
                actual_points=actual_points.get(player_id, 0.0),
                proj_points=player.proj_points,
                adp=player.adp,
                vorp=player.vorp,
            )
        )
    rows.sort(key=lambda row: (row.count, row.actual_points), reverse=True)
    return rows[:top]


def _print_player_rows(title: str, rows: list[PlayerDelta]) -> None:
    print(title)
    for row in rows:
        adp = f"{row.adp:.1f}" if row.adp is not None else "?"
        print(
            f"  {row.count:3d}x {row.name:24} {row.position:2} "
            f"ADP {adp:>5} proj {row.proj_points:6.1f} "
            f"actual {row.actual_points:6.1f} VORP {row.vorp:6.1f}"
        )


def _analyze_season(
    *,
    season: int,
    seasonal_rows: list[dict[str, object]],
    resolver: IdentityResolver,
    seeds_per_slot: int,
    teams: int,
    rounds: int,
    opponent_noise: float,
    candidate_strategy: str,
    baseline_strategy: str,
    top: int,
) -> None:
    _, adp_players = load_ffc_adp(year=season, scoring="ppr", teams=teams, position="all")
    projections = build_internal_projections(
        target_season=season,
        adp_players=adp_players,
        seasonal_rows=seasonal_rows,
        resolver=resolver,
    )
    board = value_players(projections, SLEEPER_DEFAULT_PPR, num_teams=teams)
    board_by_id = {player.player_id: player for player in board}
    actual = _actual_points(seasonal_rows, season)

    diffs: list[float] = []
    losing_diffs: list[float] = []
    pick_diffs: dict[int, list[float]] = defaultdict(list)
    value_only: Counter[str] = Counter()
    baseline_only: Counter[str] = Counter()
    losing_value_only: Counter[str] = Counter()
    losing_baseline_only: Counter[str] = Counter()
    roster_count_delta: dict[str, list[float]] = defaultdict(list)
    starter_point_delta: dict[str, list[float]] = defaultdict(list)

    for slot in range(1, teams + 1):
        for seed_idx in range(seeds_per_slot):
            seed = season * 10_000 + slot * 100 + seed_idx
            common = {
                "season": season,
                "board": board,
                "actual_points": actual,
                "user_slot": slot,
                "seed": seed,
                "num_teams": teams,
                "rounds": rounds,
                "opponent_noise_stdev": opponent_noise,
            }
            candidate = backtest_strategy(strategy=candidate_strategy, **common)
            baseline = backtest_strategy(strategy=baseline_strategy, **common)
            diff = candidate.starter_points - baseline.starter_points
            diffs.append(diff)
            value_ids = set(candidate.roster.player_ids)
            baseline_ids = set(baseline.roster.player_ids)

            for player_id in value_ids - baseline_ids:
                value_only[player_id] += 1
                if diff < 0:
                    losing_value_only[player_id] += 1
            for player_id in baseline_ids - value_ids:
                baseline_only[player_id] += 1
                if diff < 0:
                    losing_baseline_only[player_id] += 1

            value_counts = _position_counts(candidate, board_by_id)
            baseline_counts = _position_counts(baseline, board_by_id)
            value_starters = _position_starter_points(candidate, board_by_id, actual)
            baseline_starters = _position_starter_points(baseline, board_by_id, actual)
            for pos in sorted(_DRAFTABLE_POSITIONS):
                roster_count_delta[pos].append(value_counts[pos] - baseline_counts[pos])
                starter_point_delta[pos].append(
                    value_starters.get(pos, 0.0) - baseline_starters.get(pos, 0.0)
                )

            if diff < 0:
                losing_diffs.append(diff)
                for pick_idx, (value_pid, baseline_pid) in enumerate(
                    zip(candidate.roster.player_ids, baseline.roster.player_ids),
                    start=1,
                ):
                    if value_pid == baseline_pid:
                        continue
                    pick_diffs[pick_idx].append(
                        actual.get(value_pid, 0.0) - actual.get(baseline_pid, 0.0)
                    )

    wins = sum(1 for diff in diffs if diff > 0)
    print("=" * 78)
    print(f"{season}: {candidate_strategy.upper()} vs {baseline_strategy.upper()} failure analysis")
    print("-" * 78)
    print(
        f"Drafts: {len(diffs)}, avg diff {mean(diffs):+.2f}, "
        f"H2H {wins / len(diffs):.1%}, losing drafts {len(losing_diffs)}"
    )
    if losing_diffs:
        print(f"Average losing margin: {mean(losing_diffs):+.2f}")

    print()
    print(f"Roster count delta per draft ({candidate_strategy} minus {baseline_strategy}):")
    for pos in ["QB", "RB", "WR", "TE"]:
        print(f"  {pos}: {mean(roster_count_delta[pos]):+.2f}")

    print()
    print("Starter point delta per draft by position:")
    for pos in ["QB", "RB", "WR", "TE"]:
        print(f"  {pos}: {mean(starter_point_delta[pos]):+.2f}")

    if pick_diffs:
        print()
        print(
            "Worst losing-draft pick-index deltas "
            f"({candidate_strategy} pick actual - {baseline_strategy} pick actual):"
        )
        pick_rows = sorted(
            ((idx, mean(vals), len(vals)) for idx, vals in pick_diffs.items()),
            key=lambda row: row[1],
        )[:8]
        for pick_idx, avg_delta, count in pick_rows:
            print(f"  user pick {pick_idx:2d}: {avg_delta:+7.2f} points over {count} changed picks")

    print()
    _print_player_rows(
        f"Most common {candidate_strategy}-only players in losing drafts:",
        _player_deltas(losing_value_only, board_by_id, actual, top),
    )
    print()
    _print_player_rows(
        f"Most common {baseline_strategy}-only players in losing drafts:",
        _player_deltas(losing_baseline_only, board_by_id, actual, top),
    )
    print()
    _print_player_rows(
        f"Most common {candidate_strategy}-only players overall:",
        _player_deltas(value_only, board_by_id, actual, top),
    )
    print()
    _print_player_rows(
        f"Most common {baseline_strategy}-only players overall:",
        _player_deltas(baseline_only, board_by_id, actual, top),
    )


def main() -> None:
    args = _parse_args()
    if args.seeds_per_slot <= 0:
        raise ValueError("--seeds-per-slot must be positive")

    seasons = list(args.seasons)
    history_seasons = list(range(min(seasons) - 2, max(seasons) + 1))
    seasonal_rows = load_seasonal_stats(history_seasons).to_dicts()
    resolver = IdentityResolver(load_player_ids().to_dicts())

    print(
        f"Edge failure modes: seasons={seasons}, "
        f"candidate={args.candidate}, baseline={args.baseline}, "
        f"seeds/slot={args.seeds_per_slot}, noise={args.opponent_noise}"
    )
    for season in seasons:
        _analyze_season(
            season=season,
            seasonal_rows=seasonal_rows,
            resolver=resolver,
            seeds_per_slot=args.seeds_per_slot,
            teams=args.teams,
            rounds=args.rounds,
            opponent_noise=args.opponent_noise,
            candidate_strategy=args.candidate,
            baseline_strategy=args.baseline,
            top=args.top,
        )


if __name__ == "__main__":
    main()
