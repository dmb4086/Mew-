"""League scoring settings.

We model scoring as a flat mapping of `stat_key -> points_per_unit`, matching
Sleeper's own `scoring_settings` shape exactly. This is deliberate: Sleeper hands
us a league's scoring as such a dict, so importing a real league becomes a direct
copy and the Phase 1 decimal-match gate is honest (same keys, same multipliers).

Stat keys follow Sleeper's vocabulary, e.g.:
  pass_yd, pass_td, pass_int, pass_2pt
  rush_yd, rush_td, rush_2pt
  rec, rec_yd, rec_td, rec_2pt        (rec = points per reception => PPR knob)
  fum_lost, fum_rec_td
  bonus_rec_yd_100, bonus_rush_yd_100, ...
  pass_int, sack, def_td, ... (DST/IDP keys also flow through unchanged)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LeagueScoring:
    """A league's scoring rules.

    `rules` maps a stat key to points per unit. Roster info is kept alongside so
    valuation (Phase 2) can compute league-specific replacement levels.
    """

    rules: dict[str, float]
    roster_positions: tuple[str, ...] = ()
    name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def ppr(self) -> float:
        """Points per reception (the format knob): 1.0 PPR, 0.5 half, 0.0 std."""
        return float(self.rules.get("rec", 0.0))

    @property
    def is_superflex(self) -> bool:
        slots = {p.upper() for p in self.roster_positions}
        return "SUPER_FLEX" in slots or list(self.roster_positions).count("QB") > 1

    @property
    def is_te_premium(self) -> bool:
        # TE premium = bonus points per TE reception beyond the base rec value.
        return float(self.rules.get("bonus_rec_te", 0.0)) > 0.0


# A conventional full-PPR baseline mirroring Sleeper defaults. Used for tests and
# as a sane fallback; real leagues should import their exact settings.
SLEEPER_DEFAULT_PPR = LeagueScoring(
    name="Sleeper default PPR",
    rules={
        "pass_yd": 0.04,      # 1 pt / 25 yds
        "pass_td": 4.0,
        "pass_int": -1.0,
        "pass_2pt": 2.0,
        "rush_yd": 0.1,       # 1 pt / 10 yds
        "rush_td": 6.0,
        "rush_2pt": 2.0,
        "rec": 1.0,           # full PPR
        "rec_yd": 0.1,
        "rec_td": 6.0,
        "rec_2pt": 2.0,
        "fum_lost": -2.0,
        "fum_rec_td": 6.0,
    },
    roster_positions=("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"),
)


def league_from_sleeper(league_payload: dict[str, Any]) -> LeagueScoring:
    """Build LeagueScoring from a Sleeper /league/{id} payload.

    Sleeper puts the multipliers in `scoring_settings` and slots in
    `roster_positions` — we copy them through verbatim.
    """
    scoring = league_payload.get("scoring_settings") or {}
    rules = {str(k): float(v) for k, v in scoring.items()}
    roster = tuple(league_payload.get("roster_positions") or ())
    return LeagueScoring(
        rules=rules,
        roster_positions=roster,
        name=league_payload.get("name"),
        raw=league_payload,
    )
