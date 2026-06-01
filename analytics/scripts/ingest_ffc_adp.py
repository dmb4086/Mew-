"""Phase 0 ingestion: load historical FFC ADP into Postgres.

Usage:
    python -m scripts.ingest_ffc_adp           # uses FFDRAFT_SEASONS or default
    python -m scripts.ingest_ffc_adp 2022 2023
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from ffdraft.adp.ffc import load_ffc_adp
from ffdraft.config import settings
from ffdraft.db import connect
from ffdraft.identity.resolver import IdentityResolver
from ffdraft.nflverse.loader import load_player_ids


def _seasons_from_argv() -> list[int]:
    if len(sys.argv) > 1:
        return [int(a) for a in sys.argv[1:]]
    return settings.seasons


def main() -> None:
    seasons = _seasons_from_argv()
    print(f"Ingesting FFC ADP for seasons: {seasons}")

    crosswalk = load_player_ids().to_dicts()
    resolver = IdentityResolver(crosswalk)

    # Pre-load gsis_id -> player_id mapping from DB
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select player_id, gsis_id from ff.player where gsis_id is not null")
            gsis_to_player = {row[1]: row[0] for row in cur.fetchall()}

    for season in seasons:
        try:
            meta, players = load_ffc_adp(year=season, scoring="ppr", teams=12, position="all")
        except Exception as exc:
            print(f"  {season}: FAILED - {exc}")
            continue

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ff.snapshot (kind, source, season, week, captured_at, notes)
                    values ('adp', 'ffc', %s, null, %s, %s)
                    returning snapshot_id
                    """,
                    (season, datetime.now(timezone.utc), str(meta)),
                )
                snapshot_id = cur.fetchone()[0]

                resolved = 0
                unresolved = 0
                # DEF (team defense) and K/PK (kickers) are not in the nflverse
                # player crosswalk, so we skip them from the identity spine. They
                # can be added later as special roster-slot entities if needed.
                _SKIP_POSITIONS = {"DEF", "K", "PK"}

                for p in players:
                    if p.position in _SKIP_POSITIONS:
                        continue

                    alias = resolver.resolve(
                        source="adp:ffc",
                        source_id=p.player_id,
                        name=p.name,
                        position=p.position,
                    )
                    player_id = gsis_to_player.get(alias.gsis_id) if alias.gsis_id else None
                    if player_id:
                        resolved += 1
                    else:
                        unresolved += 1

                    cur.execute(
                        """
                        insert into ff.adp
                            (snapshot_id, player_id, source_id, adp, adp_rank, sample_size)
                        values (%s, %s, %s, %s, %s, %s)
                        on conflict (snapshot_id, coalesce(player_id, -1), coalesce(source_id, ''))
                        do update set adp = excluded.adp,
                                      adp_rank = excluded.adp_rank,
                                      sample_size = excluded.sample_size
                        """,
                        (snapshot_id, player_id, p.player_id, p.adp, None, p.times_drafted),
                    )

                print(
                    f"  {season}: {len(players)} players, "
                    f"{resolved} resolved, {unresolved} unresolved"
                )

    print("Done.")


if __name__ == "__main__":
    main()
