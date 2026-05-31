"""The scoring calculator.

Turns any stat line into fantasy points under arbitrary league rules. The
contract is intentionally tiny and total: fantasy points are the dot product of
the stat line and the league's per-unit rules, over the stat keys they share.

    points = sum(stat_line[k] * rules[k] for k in rules if k in stat_line)

This is what makes the Phase 1 gate pass/fail: feed a real historical box score
plus a league's exact `scoring_settings` and the output must match the platform's
reported points to the decimal. Any discrepancy means a missing/renamed stat key,
not a "judgment call".
"""

from __future__ import annotations

from typing import Mapping

from .league import LeagueScoring


def score_stat_line(
    stat_line: Mapping[str, float],
    league: LeagueScoring,
    *,
    ndigits: int = 2,
) -> float:
    """Return fantasy points for one stat line under `league`'s rules.

    Only keys present in BOTH the rules and the stat line contribute. Unknown
    stat keys are ignored (they score nothing); rules with no matching stat
    contribute nothing. Result is rounded to `ndigits` (platforms report 2dp).
    """
    total = 0.0
    for key, per_unit in league.rules.items():
        value = stat_line.get(key)
        if value is None:
            continue
        total += float(value) * float(per_unit)
    return round(total, ndigits)


def explain_score(
    stat_line: Mapping[str, float],
    league: LeagueScoring,
) -> list[tuple[str, float, float, float]]:
    """Itemized breakdown for auditing the scoring gate.

    Returns rows of (stat_key, stat_value, per_unit, contribution) for every key
    that contributed, sorted by descending absolute contribution.
    """
    rows: list[tuple[str, float, float, float]] = []
    for key, per_unit in league.rules.items():
        value = stat_line.get(key)
        if value is None:
            continue
        rows.append((key, float(value), float(per_unit), round(float(value) * float(per_unit), 4)))
    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    return rows
