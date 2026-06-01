"""Export a random sample of resolved ADP identities for hand-checking.

The vision doc requires a hand-checked sample of 50 players showing zero
silent mismatches. This script pulls 50 random ADP -> canonical player
mappings from the database and writes them to a CSV for easy review.

Usage:
    PYTHONPATH=. python -m scripts.export_identity_audit_sample
    PYTHONPATH=. python -m scripts.export_identity_audit_sample 50
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from ffdraft.db import connect

_DEFAULT_SAMPLE_SIZE = 50
_OUTPUT_DIR = Path(__file__).parent.parent / "validation_output"


def export_sample(n: int = _DEFAULT_SAMPLE_SIZE) -> Path:
    """Pull n random resolved ADP records and write to CSV."""
    _OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outfile = _OUTPUT_DIR / f"identity_audit_sample_{timestamp}.csv"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    s.season,
                    a.adp,
                    a.source_id as ffc_player_id,
                    p.full_name as canonical_name,
                    p.position as canonical_position,
                    p.team as canonical_team,
                    p.gsis_id as canonical_gsis_id
                from ff.adp a
                join ff.snapshot s on s.snapshot_id = a.snapshot_id
                join ff.player p on p.player_id = a.player_id
                where s.kind = 'adp' and a.player_id is not null
                order by random()
                limit %s
                """,
                (n,),
            )
            rows = cur.fetchall()

    headers = [
        "season",
        "adp",
        "ffc_player_id",
        "canonical_name",
        "canonical_position",
        "canonical_team",
        "canonical_gsis_id",
        "hand_check_status",
        "notes",
    ]

    with open(outfile, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(list(row) + ["", ""])

    print(f"Exported {len(rows)} records to {outfile}")
    print(f"\nReview instructions:")
    print(f"  1. Open {outfile.name}")
    print(f"  2. For each row, verify canonical_name/position/team matches")
    print(f"     the FFC player id at that ADP for that season.")
    print(f"  3. Mark hand_check_status as 'PASS' or 'FAIL'.")
    print(f"  4. The gate requires zero FAILs in the sample.")
    return outfile


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_SAMPLE_SIZE
    export_sample(n)


if __name__ == "__main__":
    main()
