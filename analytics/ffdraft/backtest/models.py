"""Typed inputs/outputs for historical draft backtests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DraftStrategy = Literal[
    "adp",
    "adp_guard",
    "vorp",
    "value_no_guard",
    "value",
    "value_market_rb",
]


@dataclass(frozen=True)
class DraftedRoster:
    """One team's drafted player IDs in pick order."""

    team_slot: int
    player_ids: tuple[str, ...]


@dataclass(frozen=True)
class StarterScore:
    """Best legal starting lineup score from a drafted roster."""

    points: float
    starter_ids: tuple[str, ...]


@dataclass(frozen=True)
class BacktestResult:
    """One strategy run for one season/slot/seed."""

    season: int
    strategy: DraftStrategy
    user_slot: int
    seed: int
    starter_points: float
    roster: DraftedRoster
    starters: tuple[str, ...]
