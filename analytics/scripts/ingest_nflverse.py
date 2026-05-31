"""Phase 0 ingestion: load N seasons of nflverse history into Postgres.

Loads the player crosswalk into ff.player (+ aliases) and weekly stats into
ff.player_week_stats. Idempotent: re-running upserts on natural keys.

Usage:
    python -m scripts.ingest_nflverse           # uses FFDRAFT_SEASONS or default
    python -m scripts.ingest_nflverse 2022 2023
"""

from __future__ import annotations

import json
import sys

import polars as pl

from ffdraft.config import settings
from ffdraft.db import connect
from ffdraft.nflverse import load_player_ids, load_weekly_stats

# Columns we treat as identity/metadata rather than countable stats.
_NON_STAT_COLS = {
    "player_id", "player_name", "player_display_name", "position", "position_group",
    "headshot_url", "recent_team", "team", "season", "week", "season_type",
    "opponent_team", "gsis_id",
}


def _seasons_from_argv() -> list[int]:
    if len(sys.argv) > 1:
        return [int(a) for a in sys.argv[1:]]
    return settings.seasons


def ingest_players(conn) -> int:
    crosswalk = load_player_ids()
    rows = crosswalk.to_dicts()
    inserted = 0
    with conn.cursor() as cur:
        for r in rows:
            gsis = r.get("gsis_id")
            if not gsis:
                continue
            name = r.get("full_name") or r.get("display_name") or r.get("name")
            cur.execute(
                """
                insert into ff.player (full_name, first_name, last_name, position, team, gsis_id)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (gsis_id) where gsis_id is not null
                do update set full_name = excluded.full_name,
                              position = excluded.position,
                              team = excluded.team,
                              updated_at = now()
                returning player_id
                """,
                (name, r.get("first_name"), r.get("last_name"),
                 r.get("position"), r.get("team_abbr") or r.get("team"), gsis),
            )
            player_id = cur.fetchone()[0]
            inserted += 1
            # Aliases for each foreign id present.
            for col, source in (
                ("sleeper_id", "sleeper"), ("espn_id", "espn"),
                ("yahoo_id", "yahoo"), ("pfr_id", "pfr"), ("gsis_id", "nflverse"),
            ):
                val = r.get(col)
                if val in (None, ""):
                    continue
                cur.execute(
                    """
                    insert into ff.player_alias
                        (player_id, source, source_id, source_name, confidence, method)
                    values (%s, %s, %s, %s, 1.0, 'id_key')
                    on conflict (source, source_id) do nothing
                    """,
                    (player_id, source, str(val), name),
                )
    return inserted


def ingest_weekly(conn, seasons: list[int]) -> int:
    weekly = load_weekly_stats(seasons)
    stat_cols = [c for c in weekly.columns if c not in _NON_STAT_COLS]
    count = 0
    with conn.cursor() as cur:
        for r in weekly.iter_rows(named=True):
            gsis = r.get("player_id") or r.get("gsis_id")
            if not gsis:
                continue
            cur.execute("select player_id from ff.player where gsis_id = %s", (gsis,))
            hit = cur.fetchone()
            if hit is None:
                continue
            stat_line = {
                k: r[k] for k in stat_cols
                if r.get(k) is not None and not (isinstance(r[k], float) and r[k] != r[k])
            }
            cur.execute(
                """
                insert into ff.player_week_stats
                    (player_id, season, week, team, opponent, stat_line, source)
                values (%s, %s, %s, %s, %s, %s, 'nflverse')
                on conflict (player_id, season, week, source)
                do update set stat_line = excluded.stat_line, loaded_at = now()
                """,
                (hit[0], r.get("season"), r.get("week"),
                 r.get("recent_team") or r.get("team"), r.get("opponent_team"),
                 json.dumps(stat_line, default=_json_default)),
            )
            count += 1
    return count


def _json_default(o):
    if isinstance(o, (pl.Series,)):
        return o.to_list()
    return float(o)


def main() -> None:
    seasons = _seasons_from_argv()
    print(f"Ingesting nflverse history for seasons: {seasons}")
    with connect() as conn:
        n_players = ingest_players(conn)
        print(f"  players upserted: {n_players}")
        n_weeks = ingest_weekly(conn, seasons)
        print(f"  weekly stat rows upserted: {n_weeks}")
    print("Done.")


if __name__ == "__main__":
    main()
