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

    raw_players = payload.get("players", [])
    if not isinstance(raw_players, list):
        raise ValueError("FFC ADP response field 'players' must be a list")

    players: list[FFCAdpPlayer] = []
    for idx, row in enumerate(raw_players):
        if not isinstance(row, dict):
            raise ValueError(f"FFC ADP player row {idx} must be an object")
        player_id = row.get("player_id")
        name = str(row.get("name") or "").strip()
        position = str(row.get("position") or "").strip()
        adp = row.get("adp")
        if player_id in (None, ""):
            raise ValueError(f"FFC ADP player row {idx} missing player_id")
        if not name:
            raise ValueError(f"FFC ADP player row {idx} missing name")
        if not position:
            raise ValueError(f"FFC ADP player row {idx} missing position")
        if adp is None:
            raise ValueError(f"FFC ADP player row {idx} missing adp")

        players.append(
            FFCAdpPlayer(
                player_id=str(player_id),
                name=name,
                position=position,
                team=row.get("team"),
                adp=float(adp),
                adp_formatted=row.get("adp_formatted"),
                times_drafted=row.get("times_drafted"),
            )
        )
    return dict(payload.get("meta") or {}), players
