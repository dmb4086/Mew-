"""Phase 0/1 ingestion: pull a Sleeper league, its managers, drafts, and picks.

Picks are resolved onto canonical players via existing aliases (Sleeper ids were
loaded by ingest_nflverse). Unresolved picks are stored with their raw Sleeper id
so nothing is silently dropped.

Usage:
    python -m scripts.ingest_sleeper_league <league_id>
"""

from __future__ import annotations

import json
import sys

from ffdraft.db import connect
from ffdraft.sleeper import SleeperClient


def _player_id_for_sleeper(cur, sleeper_id: str | None):
    if not sleeper_id:
        return None
    cur.execute(
        "select player_id from ff.player_alias where source = 'sleeper' and source_id = %s",
        (str(sleeper_id),),
    )
    hit = cur.fetchone()
    return hit[0] if hit else None


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.ingest_sleeper_league <league_id>")
    league_id = sys.argv[1]

    with SleeperClient() as sleeper, connect() as conn:
        league = sleeper.get_league(league_id)
        users = sleeper.get_league_users(league_id)
        drafts = sleeper.get_league_drafts(league_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                insert into ff.league
                    (league_id, platform, season, name, settings, scoring, roster_positions)
                values (%s, 'sleeper', %s, %s, %s, %s, %s)
                on conflict (league_id) do update set
                    settings = excluded.settings, scoring = excluded.scoring,
                    roster_positions = excluded.roster_positions, name = excluded.name
                """,
                (league_id, _as_int(league.get("season")), league.get("name"),
                 json.dumps(league.get("settings") or {}),
                 json.dumps(league.get("scoring_settings") or {}),
                 league.get("roster_positions") or []),
            )

            for u in users:
                cur.execute(
                    """
                    insert into ff.manager (user_id, platform, username, display_name)
                    values (%s, 'sleeper', %s, %s)
                    on conflict (user_id) do update set
                        username = excluded.username, display_name = excluded.display_name
                    """,
                    (u.get("user_id"), u.get("username"), u.get("display_name")),
                )

            for d in drafts:
                draft_id = d.get("draft_id")
                cur.execute(
                    """
                    insert into ff.draft
                        (draft_id, league_id, platform, season, draft_type, status, settings, slot_to_roster)
                    values (%s, %s, 'sleeper', %s, %s, %s, %s, %s)
                    on conflict (draft_id) do update set status = excluded.status
                    """,
                    (draft_id, league_id, _as_int(d.get("season")), d.get("type"),
                     d.get("status"), json.dumps(d.get("settings") or {}),
                     json.dumps(d.get("slot_to_roster_id") or {})),
                )
                picks = sleeper.get_draft_picks(draft_id)
                for p in picks:
                    pid = _player_id_for_sleeper(cur, p.get("player_id"))
                    cur.execute(
                        """
                        insert into ff.draft_pick
                            (draft_id, pick_no, round, draft_slot, roster_id,
                             picked_by, player_id, source_player_id)
                        values (%s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (draft_id, pick_no) do update set
                            player_id = excluded.player_id, picked_by = excluded.picked_by
                        """,
                        (draft_id, p.get("pick_no"), p.get("round"), p.get("draft_slot"),
                         p.get("roster_id"), p.get("picked_by"), pid, p.get("player_id")),
                    )
                print(f"  draft {draft_id}: {len(picks)} picks")

    print("Done.")


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
