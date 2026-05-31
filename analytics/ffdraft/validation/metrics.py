"""Small validation metrics without extra dependencies."""

from __future__ import annotations

from math import sqrt


def spearman_rank_correlation(left: dict[str, float], right: dict[str, float]) -> float:
    """Return Spearman rank correlation over shared keys.

    Higher values mean the two rankings agree. Ties are assigned average ranks.
    """
    keys = sorted(set(left) & set(right))
    if len(keys) < 2:
        raise ValueError("need at least two shared keys")
    left_ranks = _average_ranks({k: left[k] for k in keys})
    right_ranks = _average_ranks({k: right[k] for k in keys})
    xs = [left_ranks[k] for k in keys]
    ys = [right_ranks[k] for k in keys]
    return _pearson(xs, ys)


def _average_ranks(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
    ranks: dict[str, float] = {}
    idx = 0
    while idx < len(ordered):
        end = idx + 1
        while end < len(ordered) and ordered[end][1] == ordered[idx][1]:
            end += 1
        avg_rank = (idx + 1 + end) / 2.0
        for key, _ in ordered[idx:end]:
            ranks[key] = avg_rank
        idx = end
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var == 0 or y_var == 0:
        return 0.0
    return numerator / sqrt(x_var * y_var)
