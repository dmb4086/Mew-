"""Phase 0 Gate (b): validate scoring engine using DB-resident data.

Reads raw weekly stats from ff.player_week_stats (the table populated by
ingest_nflverse), feeds them through the scoring engine, and compares against
nflverse's official fantasy_points_ppr loaded fresh from the API.

This proves two things:
  1. The ingestion pipeline didn't corrupt data between nflverse -> DB.
  2. The scoring engine still reproduces official totals from DB-resident rows.

Usage:
    PYTHONPATH=. python -m scripts.validate_db_scoring
    PYTHONPATH=. python -m scripts.validate_db_scoring 2023 2024
"""

from __future__ import annotations

import sys

from ffdraft.config import settings
from ffdraft.db import connect
from ffdraft.nflverse.loader import load_weekly_stats
from ffdraft.scoring import NFLVERSE_PPR, nflverse_weekly_to_stat_line, score_stat_line

_TOLERANCE = 0.01


def _seasons_from_argv() -> list[int]:
    if len(sys.argv) > 1:
        return [int(a) for a in sys.argv[1:]]
    return settings.seasons


def validate_db_scoring(seasons: list[int]) -> dict[str, int | float]:
    """Check that DB stat_lines reproduce nflverse fantasy_points_ppr."""
    # Load expected values fresh from nflverse API
    expected = load_weekly_stats(seasons)
    expected_map: dict[tuple[str, int, int], float] = {}
    for row in expected.iter_rows(named=True):
        if row.get("season_type") != "REG":
            continue
        pid = row.get("player_id")
        season = row.get("season")
        week = row.get("week")
        fp = row.get("fantasy_points_ppr")
        if pid is None or season is None or week is None or fp is None:
            continue
        expected_map[(str(pid), int(season), int(week))] = float(fp)

    checked = 0
    mismatches: list[dict] = []
    db_missing: list[tuple[str, int, int]] = []

    with connect() as conn:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(seasons))
            cur.execute(
                f"""
                select
                    p.gsis_id,
                    w.season,
                    w.week,
                    w.stat_line
                from ff.player_week_stats w
                join ff.player p on p.player_id = w.player_id
                where w.season in ({placeholders})
                  and w.source = 'nflverse'
                  and w.season_type = 'REG'
                order by w.season, w.week
                """,
                tuple(seasons),
            )
            rows = cur.fetchall()

    for gsis_id, season, week, stat_line in rows:
        key = (str(gsis_id), int(season), int(week))
        if key not in expected_map:
            db_missing.append(key)
            continue

        target = expected_map[key]
        # stat_line is stored as jsonb; psycopg returns it as a dict
        actual = score_stat_line(nflverse_weekly_to_stat_line(stat_line), NFLVERSE_PPR)
        checked += 1

        if abs(actual - target) > _TOLERANCE:
            mismatches.append(
                {
                    "gsis_id": gsis_id,
                    "season": season,
                    "week": week,
                    "actual": round(actual, 4),
                    "target": round(target, 4),
                    "diff": round(actual - target, 4),
                }
            )

    print("=" * 60)
    print("Phase 0 Gate (b): DB-Backed Scoring Decimal Match")
    print("-" * 60)
    print(f"DB rows checked:        {checked}")
    print(f"Mismatches:             {len(mismatches)}")
    print(f"DB rows without API match: {len(db_missing)}")
    if db_missing:
        print(f"  (These may be preseason rows not in regular-season API data)")
    print("-" * 60)

    if mismatches:
        print("\nFirst 10 mismatches:")
        for m in mismatches[:10]:
            print(f"  {m}")
        raise AssertionError(
            f"Scoring engine mismatched {len(mismatches)} / {checked} DB rows"
        )

    return {"rows_checked": checked, "mismatches": len(mismatches)}


def main() -> None:
    seasons = _seasons_from_argv()
    print(f"Validating DB scoring for seasons: {seasons}")
    result = validate_db_scoring(seasons)
    print("\n✓ Gate (b) passed.")
    return result


if __name__ == "__main__":
    main()
