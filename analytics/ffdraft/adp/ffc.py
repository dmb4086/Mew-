"""Fantasy Football Calculator ADP loader.

Source: https://fantasyfootballcalculator.com/

Their help docs state the ADP REST API is free for personal and commercial use
with requested attribution, and that historical ADP is available back to 2007.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://fantasyfootballcalculator.com/api/v1/adp"


@dataclass(frozen=True)
class FFCAdpPlayer:
    player_id: str
    name: str
    position: str
    team: str | None
    adp: float
    adp_formatted: str | None
    times_drafted: int | None


def load_ffc_adp(
    *,
    year: int,
    scoring: str = "ppr",
    teams: int = 12,
    position: str = "all",
    timeout: float = 20.0,
) -> tuple[dict[str, Any], list[FFCAdpPlayer]]:
    """Load one historical ADP snapshot from Fantasy Football Calculator."""
    url = f"{BASE_URL}/{scoring}"
    params = {"teams": teams, "year": year, "position": position}
    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "Success":
        raise ValueError(f"FFC ADP request failed: {payload!r}")

    players = [
        FFCAdpPlayer(
            player_id=str(row["player_id"]),
            name=str(row["name"]),
            position=str(row["position"]),
            team=row.get("team"),
            adp=float(row["adp"]),
            adp_formatted=row.get("adp_formatted"),
            times_drafted=row.get("times_drafted"),
        )
        for row in payload.get("players", [])
    ]
    return dict(payload.get("meta") or {}), players
