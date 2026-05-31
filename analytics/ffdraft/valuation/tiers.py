"""Tier assignment via cliff detection.

Players cluster into quality tiers with cliffs between them. The draft skill is
"take the last player before a cliff," so we need to find the cliffs, not just
chop into equal buckets.

Algorithm (deterministic): given values sorted descending, look at the gap
between each consecutive pair. A gap is a "cliff" when it is large relative to
the typical gap at that position:

    cliff  <=>  gap > mean_gap + z * stdev_gap   (and gap >= min_gap floor)

Walking top-to-bottom, every cliff starts a new tier. Phase 2's gate then checks
that these boundaries are stable under bootstrap resampling of the projections.
"""

from __future__ import annotations

from statistics import mean, pstdev


def assign_tiers(
    values_desc: list[float],
    *,
    z: float = 1.0,
    min_gap: float = 1e-9,
) -> list[int]:
    """Return a tier number (1 = top) for each value in `values_desc`.

    `values_desc` must already be sorted descending (the engine passes VORP).
    """
    n = len(values_desc)
    if n == 0:
        return []
    if n == 1:
        return [1]

    gaps = [values_desc[i] - values_desc[i + 1] for i in range(n - 1)]
    # Guard against negative gaps if the caller didn't sort; treat as 0.
    gaps = [g if g > 0 else 0.0 for g in gaps]

    g_mean = mean(gaps)
    g_std = pstdev(gaps)
    threshold = max(min_gap, g_mean + z * g_std)

    tiers = [1] * n
    current = 1
    for i, gap in enumerate(gaps):
        if gap > threshold:
            current += 1
        tiers[i + 1] = current
    return tiers
