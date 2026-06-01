"""Phase 0 Gate (a): validate identity resolution from the database.

Checks that ADP records in the database resolve to canonical players at the
required rate. The vision doc demands ≥99% for the top ~300 players by ADP,
with a hand-checked sample of 50 showing zero silent mismatches.

Usage:
    PYTHONPATH=. python -m scripts.validate_db_identity_resolution
"""

from __future__ import annotations

import sys

from ffdraft.db import connect

# Vision-doc threshold for the draftable player pool.
_TOP_N = 300
_MIN_RESOLUTION_RATE = 0.99


def validate_top_n_resolution(season: int | None = None, top_n: int = _TOP_N) -> dict:
    """Compute resolution rate for the top-N ADP players per season."""
    season_filter = "and s.season = %s" if season else ""
    params = (top_n,)
    if season:
        params = (season, top_n)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                with ranked as (
                    select
                        s.season,
                        a.adp_rank,
                        a.adp,
                        a.player_id is not null as resolved,
                        a.source_id as raw_id,
                        p.full_name as canonical_name,
                        p.position as canonical_position,
                        p.team as canonical_team
                    from ff.adp a
                    join ff.snapshot s on s.snapshot_id = a.snapshot_id
                    left join ff.player p on p.player_id = a.player_id
                    where s.kind = 'adp'
                    {season_filter}
                ),
                numbered as (
                    select *, row_number() over (partition by season order by adp) as adp_order
                    from ranked
                )
                select
                    season,
                    count(*) as total_in_pool,
                    count(*) filter (where resolved) as resolved_count,
                    count(*) filter (where not resolved) as unresolved_count,
                    round(
                        count(*) filter (where resolved)::numeric / nullif(count(*), 0),
                        4
                    ) as resolution_rate
                from numbered
                where adp_order <= %s
                group by season
                order by season
                """,
                params,
            )
            rows = cur.fetchall()

            # Also get unresolved details for the audit trail
            cur.execute(
                f"""
                with ranked as (
                    select
                        s.season,
                        a.adp_rank,
                        a.adp,
                        a.player_id is not null as resolved,
                        a.source_id as raw_id
                    from ff.adp a
                    join ff.snapshot s on s.snapshot_id = a.snapshot_id
                    where s.kind = 'adp'
                    {season_filter}
                ),
                numbered as (
                    select *, row_number() over (partition by season order by adp) as adp_order
                    from ranked
                )
                select season, adp, adp_rank, raw_id
                from numbered
                where adp_order <= %s and not resolved
                order by season, adp_order
                """,
                params,
            )
            unresolved = cur.fetchall()

    results = {}
    failures = []
    for season, total, resolved_count, unresolved_count, rate in rows:
        results[int(season)] = {
            "total_in_pool": int(total),
            "resolved": int(resolved_count),
            "unresolved": int(unresolved_count),
            "resolution_rate": float(rate) if rate else 0.0,
        }
        if rate and float(rate) < _MIN_RESOLUTION_RATE:
            failures.append(
                f"  {season}: {rate} ({resolved_count}/{total}) < {_MIN_RESOLUTION_RATE}"
            )

    print("=" * 60)
    print("Phase 0 Gate (a): Identity Resolution from DB")
    print(f"Pool: top {top_n} players by ADP per season")
    print("-" * 60)
    for season, data in sorted(results.items()):
        status = "✓" if data["resolution_rate"] >= _MIN_RESOLUTION_RATE else "✗"
        print(
            f"{status} {season}: {data['resolution_rate']:.2%} resolved "
            f"({data['resolved']}/{data['total_in_pool']})"
        )
    print("-" * 60)

    if unresolved:
        print(f"\nUnresolved players in top-{top_n} pool:")
        for season, adp, adp_rank, raw_id in unresolved:
            print(f"  {season}: ADP {adp} (rank {adp_rank}), raw_id={raw_id}")
    else:
        print(f"\nZero unresolved players in the top-{top_n} pool.")

    if failures:
        raise AssertionError(
            f"Resolution rate below {_MIN_RESOLUTION_RATE} for:\n" + "\n".join(failures)
        )

    return {
        "seasons": results,
        "unresolved_in_top_n": [
            {"season": s, "adp": float(a), "adp_rank": ar, "raw_id": rid}
            for s, a, ar, rid in unresolved
        ],
    }


def main() -> None:
    season = int(sys.argv[1]) if len(sys.argv) > 1 else None
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else _TOP_N
    result = validate_top_n_resolution(season=season, top_n=top_n)
    print("\n✓ Gate (a) passed.")
    return result


if __name__ == "__main__":
    main()
