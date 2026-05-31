"""Sleeper API client.

The Sleeper read API is free, read-only, and requires no authentication. Rate
ceiling is ~1000 calls/minute; stay well under it. Base URL: https://api.sleeper.app/v1

Endpoints we rely on for the draft copilot:
  - GET /players/nfl                  full player dictionary (large; cache it)
  - GET /league/{league_id}           league settings + scoring
  - GET /league/{league_id}/users     managers
  - GET /league/{league_id}/drafts    drafts for a league
  - GET /draft/{draft_id}             draft metadata
  - GET /draft/{draft_id}/picks       picks (poll this live during a draft)
  - GET /user/{username}              resolve a username to a user_id
  - GET /user/{user_id}/leagues/nfl/{season}   a user's leagues for a season
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://api.sleeper.app/v1"


class SleeperClient:
    def __init__(self, *, base_url: str = BASE_URL, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": "ffdraft/0.0.1 (+https://github.com/dmb4086/mew-)"},
        )

    def __enter__(self) -> "SleeperClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> Any:
        resp = self._client.get(path)
        resp.raise_for_status()
        return resp.json()

    # --- players -----------------------------------------------------------
    def get_players(self) -> dict[str, dict[str, Any]]:
        """Full NFL player dictionary keyed by Sleeper player_id.

        This payload is several MB. Sleeper asks that it be fetched at most once
        per day and cached — do not poll it.
        """
        return self._get("/players/nfl")

    # --- users -------------------------------------------------------------
    def get_user(self, username_or_id: str) -> dict[str, Any] | None:
        return self._get(f"/user/{username_or_id}")

    def get_user_leagues(self, user_id: str, season: int | str) -> list[dict[str, Any]]:
        return self._get(f"/user/{user_id}/leagues/nfl/{season}")

    # --- leagues -----------------------------------------------------------
    def get_league(self, league_id: str) -> dict[str, Any]:
        return self._get(f"/league/{league_id}")

    def get_league_users(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/users")

    def get_league_drafts(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/drafts")

    # --- drafts ------------------------------------------------------------
    def get_draft(self, draft_id: str) -> dict[str, Any]:
        return self._get(f"/draft/{draft_id}")

    def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        """Picks made so far. Poll this during a live draft to sync the board."""
        return self._get(f"/draft/{draft_id}/picks")
