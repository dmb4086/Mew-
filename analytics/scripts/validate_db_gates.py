"""Run ALL Phase 0 DB validation gates in one shot.

This is the single command to prove the database ingestion is correct:

    PYTHONPATH=. python -m scripts.validate_db_gates

Gates:
  1. Identity resolution (top-N offensive players by ADP) ≥99%
  2. Scoring engine decimal-match from DB-resident rows
  3. Season-total consistency (weekly DB rows sum to season totals)

Each gate fails with an AssertionError if its threshold is not met.
"""

from __future__ import annotations

import sys

from ffdraft.config import settings

from .validate_db_identity_resolution import validate_top_n_resolution
from .validate_db_scoring import validate_db_scoring


def validate_db_season_totals(seasons: list[int], top_n: int = 100) -> dict:
    """Gate (c): weekly DB rows sum to season totals for top-N players per season."""
    from ffdraft.db import connect
    from ffdraft.nflverse.loader import load_seasonal_stats
    from ffdraft.scoring import NFLVERSE_PPR, nflverse_weekly_to_stat_line, score_stat_line

    # Load expected season totals from nflverse, keep top N per season
    seasonal = load_seasonal_stats(seasons)
    by_season: dict[int, list[tuple[str, float]]] = {}
    for row in seasonal.iter_rows(named=True):
        pid = row.get("player_id")
        season = row.get("season")
        fp = row.get("fantasy_points_ppr")
        if pid and season and fp:
            by_season.setdefault(int(season), []).append((str(pid), float(fp)))

    expected: dict[tuple[str, int], float] = {}
    for season, players in by_season.items():
        players.sort(key=lambda x: x[1], reverse=True)
        for pid, fp in players[:top_n]:
            expected[(pid, season)] = fp

    # Sum weekly DB rows
    weekly_totals: dict[tuple[str, int], float] = {}
    with connect() as conn:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(seasons))
            cur.execute(
                f"""
                select p.gsis_id, w.season, w.stat_line
                from ff.player_week_stats w
                join ff.player p on p.player_id = w.player_id
                where w.season in ({placeholders})
                  and w.source = 'nflverse'
                  and w.season_type = 'REG'
                """,
                tuple(seasons),
            )
            for gsis_id, season, stat_line in cur.fetchall():
                key = (str(gsis_id), int(season))
                pts = score_stat_line(nflverse_weekly_to_stat_line(stat_line), NFLVERSE_PPR)
                weekly_totals[key] = weekly_totals.get(key, 0.0) + pts

    checked = 0
    mismatches = 0
    mismatch_details: list[dict] = []

    for (pid, season), target in expected.items():
        actual = round(weekly_totals.get((pid, season), 0.0), 2)
        target_rounded = round(target, 2)
        if abs(actual - target_rounded) > 0.02:
            mismatches += 1
            if len(mismatch_details) < 10:
                mismatch_details.append(
                    {"player_id": pid, "season": season, "actual": actual, "target": target_rounded}
                )
        checked += 1

    print("=" * 60)
    print("Phase 0 Gate (c): Season Total Consistency (DB weekly -> season)")
    print(f"Pool: top {top_n} players per season by fantasy points")
    print("-" * 60)
    print(f"Players checked: {checked}")
    print(f"Mismatches:      {mismatches}")
    if mismatch_details:
        print("\nSample mismatches:")
        for m in mismatch_details:
            print(f"  {m}")
    print("-" * 60)

    if mismatches:
        raise AssertionError(
            f"Season totals mismatched for {mismatches} / {checked} top-{top_n} players"
        )

    return {"players_checked": checked, "mismatches": mismatches}


def main() -> None:
    seasons = settings.seasons
    print(f"Running ALL Phase 0 DB gates for seasons: {seasons}\n")

    validate_top_n_resolution(season=None, top_n=300)
    print()

    validate_db_scoring(seasons)
    print()

    validate_db_season_totals(seasons)
    print()

    print("=" * 60)
    print("ALL Phase 0 DB GATES PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
