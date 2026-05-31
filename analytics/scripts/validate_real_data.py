"""Run real-data validation gates against public historical sources.

This script intentionally uses network data and is not part of the default
pytest suite. It validates the real seams that synthetic unit tests cannot:

  1. nflreadpy loaders still match the current upstream API.
  2. Raw nflverse weekly stats reproduce nflverse `fantasy_points_ppr`.
  3. Weekly calculated totals match nflverse season totals for top players.
  4. Fantasy Football Calculator historical ADP loads and resolves to nflverse
     identities at an auditable rate.
  5. Internal preseason projections improve after VORP adjustment.

Usage:
    PYTHONPATH=. python -m scripts.validate_real_data
    PYTHONPATH=. python -m scripts.validate_real_data 2023 2024
"""

from __future__ import annotations

import sys
from collections import defaultdict

from ffdraft.adp import load_ffc_adp
from ffdraft.config import settings
from ffdraft.identity import IdentityResolver
from ffdraft.nflverse import load_player_ids, load_seasonal_stats, load_weekly_stats
from ffdraft.projections import build_internal_projections
from ffdraft.scoring import (
    NFLVERSE_PPR,
    SLEEPER_DEFAULT_PPR,
    nflverse_weekly_to_stat_line,
    score_stat_line,
)
from ffdraft.validation import spearman_rank_correlation
from ffdraft.valuation import PlayerProjection, value_players

_TOLERANCE = 0.01
_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}


def _seasons_from_argv() -> list[int]:
    if len(sys.argv) > 1:
        return [int(a) for a in sys.argv[1:]]
    return settings.seasons


def _regular_rows(df):
    if "season_type" not in df.columns:
        return df.iter_rows(named=True)
    return (row for row in df.iter_rows(named=True) if row.get("season_type") == "REG")


def validate_weekly_scoring(seasons: list[int]) -> dict[str, float | int]:
    weekly = load_weekly_stats(seasons)
    mismatches: list[tuple[str, int, int, float, float]] = []
    checked = 0
    for row in _regular_rows(weekly):
        target = row.get("fantasy_points_ppr")
        if target is None:
            continue
        stat_line = nflverse_weekly_to_stat_line(row)
        actual = score_stat_line(stat_line, NFLVERSE_PPR)
        checked += 1
        if abs(actual - float(target)) > _TOLERANCE:
            mismatches.append(
                (
                    str(row.get("player_name")),
                    int(row.get("season")),
                    int(row.get("week")),
                    actual,
                    float(target),
                )
            )

    if mismatches:
        preview = mismatches[:10]
        raise AssertionError(f"weekly scoring mismatches: {preview}")
    return {"rows_checked": checked, "mismatches": 0}


def validate_season_totals(seasons: list[int], *, top_n: int = 100) -> dict[str, int]:
    weekly = load_weekly_stats(seasons)
    seasonal = load_seasonal_stats(seasons)

    weekly_totals: dict[tuple[str, int], float] = defaultdict(float)
    for row in _regular_rows(weekly):
        player_id = row.get("player_id")
        season = row.get("season")
        if player_id is None or season is None:
            continue
        score = score_stat_line(nflverse_weekly_to_stat_line(row), NFLVERSE_PPR)
        weekly_totals[(str(player_id), int(season))] += score

    checked = 0
    mismatches: list[tuple[str, int, float, float]] = []
    for season in seasons:
        season_rows = [
            row for row in seasonal.iter_rows(named=True)
            if int(row.get("season")) == season and row.get("fantasy_points_ppr") is not None
        ]
        season_rows.sort(key=lambda r: float(r.get("fantasy_points_ppr") or 0.0), reverse=True)
        for row in season_rows[:top_n]:
            key = (str(row.get("player_id")), season)
            actual = round(weekly_totals.get(key, 0.0), 2)
            target = round(float(row.get("fantasy_points_ppr") or 0.0), 2)
            checked += 1
            if abs(actual - target) > _TOLERANCE:
                mismatches.append((str(row.get("player_name")), season, actual, target))

    if mismatches:
        raise AssertionError(f"season total mismatches: {mismatches[:10]}")
    return {"top_players_checked": checked, "mismatches": 0}


def validate_adp_identity(seasons: list[int]) -> dict[str, int | float]:
    crosswalk = load_player_ids().to_dicts()
    resolver = IdentityResolver(crosswalk)
    total = resolved = fuzzy = unresolved = 0
    low_confidence: list[tuple[int, str, str, float]] = []

    for season in seasons:
        meta, players = load_ffc_adp(year=season, scoring="ppr", teams=12, position="all")
        print(
            f"  FFC {season}: {len(players)} players, "
            f"{meta.get('total_drafts')} drafts, {meta.get('start_date')}..{meta.get('end_date')}"
        )
        for player in players:
            if player.position in {"DEF", "PK", "K"}:
                continue
            total += 1
            result = resolver.resolve(
                source="adp:fantasyfootballcalculator",
                source_id=player.player_id,
                name=player.name,
                position="K" if player.position == "PK" else player.position,
            )
            if result.gsis_id is None:
                unresolved += 1
                continue
            resolved += 1
            if result.method == "fuzzy":
                fuzzy += 1
            if result.confidence < 0.92:
                low_confidence.append((season, player.name, player.position, result.confidence))

    resolution_rate = resolved / total if total else 0.0
    if resolution_rate < 0.95:
        raise AssertionError(
            f"ADP identity resolution below 95%: {resolved}/{total}; "
            f"sample unresolved/low-confidence: {low_confidence[:10]}"
        )
    return {
        "players_checked": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "fuzzy": fuzzy,
        "resolution_rate": round(resolution_rate, 4),
        "low_confidence_under_0_92": len(low_confidence),
    }


def validate_internal_projection_gate(seasons: list[int]) -> dict[str, object]:
    """Validate that projected VORP beats raw projected points on held-out seasons."""
    history_seasons = list(range(min(seasons) - 2, max(seasons) + 1))
    seasonal_rows = load_seasonal_stats(history_seasons).to_dicts()
    resolver = IdentityResolver(load_player_ids().to_dicts())

    by_season: dict[int, dict[str, float | int]] = {}
    wins = 0
    for season in seasons:
        _, adp_players = load_ffc_adp(year=season, scoring="ppr", teams=12, position="all")
        projections = build_internal_projections(
            target_season=season,
            adp_players=adp_players,
            seasonal_rows=seasonal_rows,
            resolver=resolver,
        )
        projected_values = value_players(projections, SLEEPER_DEFAULT_PPR, num_teams=12)
        projected_vorp = {v.player_id: v.vorp for v in projected_values}
        raw_projection = {p.player_id: p.proj_points for p in projections}

        actual_pool = [
            PlayerProjection(
                player_id=str(row["player_id"]),
                name=str(row.get("player_display_name") or row.get("player_name")),
                position=str(row["position"]),
                proj_points=float(row.get("fantasy_points_ppr") or 0.0),
            )
            for row in seasonal_rows
            if int(row.get("season") or 0) == season
            and row.get("position") in _DRAFTABLE_POSITIONS
            and float(row.get("fantasy_points_ppr") or 0.0) > 0.0
        ]
        actual_values = value_players(actual_pool, SLEEPER_DEFAULT_PPR, num_teams=12)
        actual_vorp = {v.player_id: v.vorp for v in actual_values}

        raw_corr = spearman_rank_correlation(raw_projection, actual_vorp)
        vorp_corr = spearman_rank_correlation(projected_vorp, actual_vorp)
        delta = vorp_corr - raw_corr
        if delta > 0:
            wins += 1
        by_season[season] = {
            "players": len(set(raw_projection) & set(actual_vorp)),
            "raw_spearman": round(raw_corr, 4),
            "vorp_spearman": round(vorp_corr, 4),
            "delta": round(delta, 4),
        }

    if wins != len(seasons):
        raise AssertionError(f"projected VORP failed to beat raw projections: {by_season}")
    avg_delta = sum(float(row["delta"]) for row in by_season.values()) / len(by_season)
    return {
        "seasons": by_season,
        "vorp_wins": wins,
        "seasons_checked": len(seasons),
        "avg_delta": round(avg_delta, 4),
    }


def main() -> None:
    seasons = _seasons_from_argv()
    print(f"Validating seasons: {seasons}")

    weekly = validate_weekly_scoring(seasons)
    print(f"✓ Weekly scoring decimal match: {weekly}")

    seasonal = validate_season_totals(seasons)
    print(f"✓ Weekly-to-season top-100 totals: {seasonal}")

    adp = validate_adp_identity(seasons)
    print(f"✓ Historical ADP identity resolution: {adp}")

    projection = validate_internal_projection_gate(seasons)
    print(f"✓ Internal projection/VORP held-out gate: {projection}")

    print("Real-data validation passed.")


if __name__ == "__main__":
    main()
