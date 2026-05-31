"""Valuation engine (Phase 2): replacement level, VORP, tiers/cliffs.

The heart of the system. Given per-player projections and a league config, this
turns raw projected points into the real currency of a draft:

    VORP = projected_points - replacement_level(position)

plus tier assignment with cliff detection. All deterministic: same inputs ->
same output, no randomness, no network, no database. That is what lets Phase 3
backtest it and Phase 5 trust it.
"""

from .models import PlayerProjection, PlayerValuation
from .engine import value_players, compute_replacement_levels, starter_demand
from .tiers import assign_tiers

__all__ = [
    "PlayerProjection",
    "PlayerValuation",
    "value_players",
    "compute_replacement_levels",
    "starter_demand",
    "assign_tiers",
]
