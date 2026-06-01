"""Internal preseason projection baseline.

No clean free multi-season preseason projection feed was found that we can bake
into the repo. This module builds a transparent baseline from data we can
validate and cite:

  - prior regular-season nflverse fantasy production
  - current preseason ADP from Fantasy Football Calculator

The model is intentionally simple. It is a baseline for Phase 3/held-out gates,
not the final projection engine:

  projection = position-specific prior player production weight
             + remaining weight from market positional curve

For rookies or players with no prior production, it falls back to the market
curve. All inputs are preseason-available for the target season.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable, Mapping

from ffdraft.adp import FFCAdpPlayer
from ffdraft.identity import IdentityResolver
from ffdraft.valuation import PlayerProjection

_DRAFTABLE_POSITIONS = {"QB", "RB", "WR", "TE"}
_DEFAULT_PLAYER_WEIGHTS: Mapping[str, float] = {
    # Held-out 2019-2024 sweeps show the market positional curve is more
    # predictive than prior player production, especially at fragile positions.
    "QB": 0.15,
    "RB": 0.05,
    "WR": 0.45,
    "TE": 0.05,
}


# Team-change penalty by position (from historical regression).
# RBs are most fragile; QBs sometimes improve.
_TEAM_CHANGE_PENALTY: Mapping[str, float] = {
    "QB": 1.00,
    "RB": 0.75,
    "WR": 0.90,
    "TE": 0.85,
}


def build_internal_projections(
    *,
    target_season: int,
    adp_players: list[FFCAdpPlayer],
    seasonal_rows: Iterable[Mapping[str, object]],
    resolver: IdentityResolver,
    player_weight: float | Mapping[str, float] | None = None,
) -> list[PlayerProjection]:
    """Build preseason projections for one target season.

    `seasonal_rows` should include at least `target_season - 1`; two prior
    seasons improves player-history stability. Rows from the target season are
    ignored so this remains a true held-out projection.
    """
    player_weights = _player_weights(player_weight)

    rows_by_player = _history_by_player(target_season=target_season, seasonal_rows=seasonal_rows)
    market_curves = _market_curves(target_season=target_season, seasonal_rows=seasonal_rows)
    fallback_by_pos = {
        pos: median(points_by_rank.values()) if points_by_rank else 0.0
        for pos, points_by_rank in market_curves.items()
    }
    pos_ranks = _adp_position_ranks(adp_players)

    # Build a lookup for prior-season team so we can detect team changes.
    prior_team_by_player: dict[str, str] = {}
    for row in seasonal_rows:
        if int(row.get("season") or 0) != target_season - 1:
            continue
        pid = str(row.get("player_id") or "")
        team = str(row.get("recent_team") or row.get("team") or "")
        if pid and team:
            prior_team_by_player[pid] = team

    projections: list[PlayerProjection] = []
    seen: set[str] = set()
    for adp in sorted(adp_players, key=lambda p: p.adp):
        pos = _normalize_position(adp.position)
        if pos not in _DRAFTABLE_POSITIONS:
            continue
        resolved = resolver.resolve(
            source="adp:fantasyfootballcalculator",
            source_id=adp.player_id,
            name=adp.name,
            position=pos,
        )
        if resolved.gsis_id is None or resolved.gsis_id in seen:
            continue

        pos_rank = pos_ranks.get(adp.player_id, 999)
        market_points = _points_for_pos_rank(market_curves.get(pos, {}), pos_rank, fallback_by_pos[pos])
        player_points = _prior_player_points(rows_by_player.get(resolved.gsis_id, []), pos)

        if player_points is None:
            projected = market_points
        else:
            weight = player_weights.get(pos, 0.0)
            projected = weight * player_points + (1.0 - weight) * market_points
            # Apply team-change penalty if the player switched teams.
            prior_team = prior_team_by_player.get(resolved.gsis_id, "")
            if prior_team and adp.team and prior_team != adp.team:
                projected *= _TEAM_CHANGE_PENALTY.get(pos, 1.0)

        projections.append(
            PlayerProjection(
                player_id=resolved.gsis_id,
                name=adp.name,
                position=pos,
                proj_points=round(projected, 2),
                adp=adp.adp,
            )
        )
        seen.add(resolved.gsis_id)

    return projections


def _normalize_position(pos: str) -> str:
    return "DEF" if pos in {"DST", "D/ST"} else pos


def _player_weights(player_weight: float | Mapping[str, float] | None) -> Mapping[str, float]:
    if player_weight is None:
        return _DEFAULT_PLAYER_WEIGHTS
    if isinstance(player_weight, Mapping):
        normalized = {
            _normalize_position(pos): float(weight)
            for pos, weight in player_weight.items()
        }
        invalid = {
            pos: weight
            for pos, weight in normalized.items()
            if pos in _DRAFTABLE_POSITIONS and not 0.0 <= weight <= 1.0
        }
        if invalid:
            raise ValueError(f"player_weight values must be between 0 and 1: {invalid}")
        return {**_DEFAULT_PLAYER_WEIGHTS, **normalized}
    if not 0.0 <= player_weight <= 1.0:
        raise ValueError("player_weight must be between 0 and 1")
    return {pos: player_weight for pos in _DRAFTABLE_POSITIONS}


def _history_by_player(
    *,
    target_season: int,
    seasonal_rows: Iterable[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    out: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in seasonal_rows:
        season = row.get("season")
        player_id = row.get("player_id")
        if season is None or player_id is None:
            continue
        season = int(season)
        if target_season - 2 <= season <= target_season - 1:
            out[str(player_id)].append(row)
    for rows in out.values():
        rows.sort(key=lambda r: int(r.get("season") or 0), reverse=True)
    return out


def _prior_player_points(rows: list[Mapping[str, object]], position: str) -> float | None:
    if not rows:
        return None
    weights = {1: 0.70, 2: 0.30}
    weighted = 0.0
    used = 0.0
    latest_season = max(int(r.get("season") or 0) for r in rows)
    for row in rows:
        years_back = latest_season - int(row.get("season") or 0) + 1
        weight = weights.get(years_back)
        if weight is None:
            continue
        points = float(row.get("fantasy_points_ppr") or 0.0)
        games = float(row.get("games") or 0.0)
        if games <= 0:
            continue
        expected_games = _expected_games(games=games, position=position)
        weighted += (points / games) * expected_games * weight
        used += weight
    if used <= 0:
        return None
    return weighted / used


def _expected_games(*, games: float, position: str) -> float:
    # Injury/playing-time regression: strong prior-year availability gets pulled
    # toward a healthy season, while tiny samples are not blindly annualized.
    baseline = 15.0 if position == "QB" else 14.0
    return min(17.0, 0.65 * games + 0.35 * baseline)


def _market_curves(
    *,
    target_season: int,
    seasonal_rows: Iterable[Mapping[str, object]],
) -> dict[str, dict[int, float]]:
    prior_season = target_season - 1
    by_pos: dict[str, list[float]] = defaultdict(list)
    for row in seasonal_rows:
        if int(row.get("season") or 0) != prior_season:
            continue
        pos = _normalize_position(str(row.get("position") or ""))
        if pos not in _DRAFTABLE_POSITIONS:
            continue
        points = float(row.get("fantasy_points_ppr") or 0.0)
        if points <= 0:
            continue
        by_pos[pos].append(points)

    curves: dict[str, dict[int, float]] = {}
    for pos, values in by_pos.items():
        values.sort(reverse=True)
        curves[pos] = {rank: points for rank, points in enumerate(values, start=1)}
    return curves


def _points_for_pos_rank(curve: dict[int, float], pos_rank: int, fallback: float) -> float:
    if not curve:
        return fallback
    if pos_rank in curve:
        return curve[pos_rank]
    last_rank = max(curve)
    # Past the curve, decay gently rather than returning zero.
    return max(0.0, curve[last_rank] - (pos_rank - last_rank) * 2.0)


def _adp_position_ranks(adp_players: list[FFCAdpPlayer]) -> dict[str, int]:
    by_pos: dict[str, list[FFCAdpPlayer]] = defaultdict(list)
    for player in adp_players:
        by_pos[_normalize_position(player.position)].append(player)

    ranks: dict[str, int] = {}
    for players in by_pos.values():
        for rank, player in enumerate(sorted(players, key=lambda p: p.adp), start=1):
            ranks[player.player_id] = rank
    return ranks
