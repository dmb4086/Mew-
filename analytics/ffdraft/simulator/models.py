"""Typed draft simulator inputs/outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DraftPick:
    """One completed pick in a draft.

    `overall_pick` is 1-based because that is how draft rooms and Sleeper expose
    picks. `team_slot` is also 1-based: slot 1 picks first in odd rounds.
    """

    overall_pick: int
    team_slot: int
    player_id: str


@dataclass(frozen=True)
class DraftState:
    """Current draft board snapshot for simulation."""

    num_teams: int
    rounds: int
    user_slot: int
    current_pick: int = 1
    picks: tuple[DraftPick, ...] = ()

    @property
    def drafted_player_ids(self) -> frozenset[str]:
        return frozenset(p.player_id for p in self.picks)


@dataclass(frozen=True)
class AvailabilityResult:
    """Probability that a player survives until the user's next pick."""

    player_id: str
    name: str
    position: str
    survival_probability: float
    next_user_pick: int | None
    simulations: int


@dataclass(frozen=True)
class PickScore:
    """A deterministic pick ranking row emitted by Phase 4.

    `pass_risk` is the expected VORP lost by trying to wait until the next pick:

        pass_risk = max(vorp, 0) * (1 - survival_probability)

    The final score intentionally stays simple and auditable for v0.
    """

    player_id: str
    name: str
    position: str
    score: float
    vorp: float
    survival_probability: float
    pass_risk: float
    value_vs_adp: float | None
    next_user_pick: int | None
