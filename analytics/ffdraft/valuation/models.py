"""Typed inputs/outputs for the valuation engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerProjection:
    """One player's preseason projection — the input to valuation."""

    player_id: str
    name: str
    position: str
    proj_points: float
    adp: float | None = None


@dataclass(frozen=True)
class PlayerValuation:
    """Valuation output for one player. This is the structured currency that the
    draft simulator (Phase 4) and the Recommendation Object (Phase 5) consume.
    """

    player_id: str
    name: str
    position: str
    proj_points: float
    replacement_level: float
    vorp: float
    pos_rank: int          # 1 = best projected at the position
    overall_rank: int      # 1 = highest VORP overall
    tier: int              # 1 = top tier at the position
    adp: float | None = None

    @property
    def value_vs_adp(self) -> float | None:
        """Positive = the market (ADP) underrates this player's overall VORP rank.

        Measured in draft slots: ADP minus our overall VORP rank. A player we rank
        10th overall but who goes 25th in the market scores +15 (a value).
        """
        if self.adp is None:
            return None
        return self.adp - self.overall_rank
