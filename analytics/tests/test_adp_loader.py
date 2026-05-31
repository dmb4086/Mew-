"""Unit tests for ADP loader parsing without network."""

from __future__ import annotations

import httpx

from ffdraft.adp import load_ffc_adp


def test_load_ffc_adp_parses_players(monkeypatch):
    def fake_get(url, params, timeout):
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "Success",
                "meta": {"type": "PPR", "teams": 12, "total_drafts": 10},
                "players": [
                    {
                        "player_id": 123,
                        "name": "Test Player",
                        "position": "RB",
                        "team": "CHI",
                        "adp": 12.3,
                        "adp_formatted": "2.01",
                        "times_drafted": 8,
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    meta, players = load_ffc_adp(year=2024, scoring="ppr", teams=12)

    assert meta["total_drafts"] == 10
    assert players[0].player_id == "123"
    assert players[0].name == "Test Player"
    assert players[0].adp == 12.3
