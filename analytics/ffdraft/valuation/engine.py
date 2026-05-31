"""Replacement level + VORP.

Replacement level is computed by a greedy starter-fill that correctly handles
FLEX slots — the part naive "rank N at each position" calculators get wrong.

Method:
  1. Fill every dedicated positional starter slot (teams x slots) with the top
     projected players at that position.
  2. Fill each flex slot greedily with the best remaining flex-eligible player
     across positions (this is what makes a strong RB/WR pool deepen the flex,
     and what makes Superflex pull QBs up).
  3. Replacement level for a position = the projection of the best player at that
     position who did NOT end up a starter (the top of the bench). The marginal
     starter therefore has ~0 VORP, which is the definition we want.

VORP = projected_points - replacement_level(position).
"""

from __future__ import annotations

from collections import defaultdict

from ..scoring.league import LeagueScoring
from .models import PlayerProjection, PlayerValuation
from .tiers import assign_tiers

# Sleeper flex tokens -> eligible positions.
FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    "REC_FLEX": ("WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
}
# Dedicated starting positions (everything else in roster_positions that isn't a
# flex token or a bench/reserve token).
DEDICATED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}
BENCH_TOKENS = {"BN", "IR", "TAXI", "NA", "RES"}


def _normalize_pos(pos: str) -> str:
    return "DEF" if pos in ("DST", "D/ST") else pos


def starter_demand(roster_positions: tuple[str, ...], num_teams: int) -> dict[str, int]:
    """Dedicated starter slots per position across the whole league (excludes flex)."""
    demand: dict[str, int] = defaultdict(int)
    for slot in roster_positions:
        token = slot.upper()
        if token in DEDICATED_POSITIONS:
            demand[_normalize_pos(token)] += num_teams
    return dict(demand)


def _flex_slots(roster_positions: tuple[str, ...], num_teams: int) -> list[tuple[str, ...]]:
    """One entry per flex slot in the whole league, each the eligible-position set."""
    slots: list[tuple[str, ...]] = []
    for slot in roster_positions:
        token = slot.upper()
        if token in FLEX_ELIGIBILITY:
            slots.extend([FLEX_ELIGIBILITY[token]] * num_teams)
    # Process more-restrictive flex slots first so they aren't starved by greedy
    # super-flex picks. Deterministic tiebreak by the eligibility tuple itself.
    slots.sort(key=lambda elig: (len(elig), elig))
    return slots


def compute_replacement_levels(
    projections: list[PlayerProjection],
    league: LeagueScoring,
    num_teams: int = 12,
) -> dict[str, float]:
    """Return {position: replacement_level_points}."""
    by_pos: dict[str, list[PlayerProjection]] = defaultdict(list)
    for p in projections:
        by_pos[_normalize_pos(p.position)].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: p.proj_points, reverse=True)

    # Pointer to the first not-yet-claimed player at each position.
    next_idx: dict[str, int] = defaultdict(int)

    # 1) Dedicated starters.
    for pos, count in starter_demand(league.roster_positions, num_teams).items():
        next_idx[pos] += min(count, len(by_pos.get(pos, [])))

    # 2) Flex starters, greedy across eligible positions.
    for eligibility in _flex_slots(league.roster_positions, num_teams):
        best_pos, best_proj = None, float("-inf")
        for pos in eligibility:
            pos = _normalize_pos(pos)
            pool = by_pos.get(pos, [])
            i = next_idx[pos]
            if i < len(pool) and pool[i].proj_points > best_proj:
                best_pos, best_proj = pos, pool[i].proj_points
        if best_pos is not None:
            next_idx[best_pos] += 1

    # 3) Replacement = top remaining (first bench) player per position.
    replacement: dict[str, float] = {}
    for pos, pool in by_pos.items():
        i = next_idx[pos]
        if i < len(pool):
            replacement[pos] = pool[i].proj_points
        elif pool:
            # Everyone projected is a starter; fall back to the last starter.
            replacement[pos] = pool[-1].proj_points
        else:
            replacement[pos] = 0.0
    return replacement


def value_players(
    projections: list[PlayerProjection],
    league: LeagueScoring,
    num_teams: int = 12,
    *,
    tier_z: float = 1.0,
) -> list[PlayerValuation]:
    """Full valuation pass: replacement -> VORP -> ranks -> tiers.

    Returns valuations sorted by descending VORP (overall draft board order).
    """
    replacement = compute_replacement_levels(projections, league, num_teams)

    # Positional ranks and tiers are computed within each position.
    by_pos: dict[str, list[PlayerProjection]] = defaultdict(list)
    for p in projections:
        by_pos[_normalize_pos(p.position)].append(p)

    vorp_by_id: dict[str, float] = {}
    pos_rank_by_id: dict[str, int] = {}
    tier_by_id: dict[str, int] = {}
    for pos, pool in by_pos.items():
        pool_sorted = sorted(pool, key=lambda p: p.proj_points, reverse=True)
        repl = replacement.get(pos, 0.0)
        vorps = [p.proj_points - repl for p in pool_sorted]
        tiers = assign_tiers(vorps, z=tier_z)
        for rank, (p, v, t) in enumerate(zip(pool_sorted, vorps, tiers), start=1):
            vorp_by_id[p.player_id] = v
            pos_rank_by_id[p.player_id] = rank
            tier_by_id[p.player_id] = t

    # Overall ranks by VORP across all positions.
    ordered = sorted(projections, key=lambda p: vorp_by_id[p.player_id], reverse=True)
    out: list[PlayerValuation] = []
    for overall_rank, p in enumerate(ordered, start=1):
        pos = _normalize_pos(p.position)
        out.append(
            PlayerValuation(
                player_id=p.player_id,
                name=p.name,
                position=pos,
                proj_points=p.proj_points,
                replacement_level=replacement.get(pos, 0.0),
                vorp=round(vorp_by_id[p.player_id], 2),
                pos_rank=pos_rank_by_id[p.player_id],
                overall_rank=overall_rank,
                tier=tier_by_id[p.player_id],
                adp=p.adp,
            )
        )
    return out
