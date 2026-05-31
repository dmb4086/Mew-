"""Load historical NFL data via nflreadpy (the maintained successor to
nfl_data_py). Returns Polars DataFrames.

We keep this module thin: it wraps nflreadpy and normalizes column names a bit,
but does NOT compute fantasy points (that is the league-specific scoring engine's
job) and does NOT touch the database (that is the ingestion scripts' job). This
separation keeps the scoring gate honest.
"""

from __future__ import annotations

import polars as pl


def _import_nflreadpy():
    try:
        import nflreadpy as nfl  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "nflreadpy is required. Install with `pip install nflreadpy`. "
            "Note: nfl_data_py is end-of-life; do not use it."
        ) from exc
    return nfl


def load_weekly_stats(seasons: list[int]) -> pl.DataFrame:
    """Weekly player stats (offense) for the given seasons.

    These are the raw counting stats (pass yards, rush TDs, receptions, ...) used
    both as historical truth for backtesting and as the input to the scoring
    engine's decimal-match gate.
    """
    nfl = _import_nflreadpy()
    df = nfl.load_player_stats(seasons=seasons, summary_level="week")
    return _ensure_polars(df)


def load_seasonal_stats(seasons: list[int]) -> pl.DataFrame:
    """Season-aggregated player stats for the given seasons."""
    nfl = _import_nflreadpy()
    df = nfl.load_player_stats(seasons=seasons, summary_level="season")
    return _ensure_polars(df)


def load_player_ids() -> pl.DataFrame:
    """The nflverse player-id crosswalk (gsis_id, pfr_id, sleeper_id, espn_id,
    yahoo_id, full_name, position, ...). This is the backbone the identity
    resolver matches everything else against.
    """
    nfl = _import_nflreadpy()
    df = nfl.load_players()
    return _ensure_polars(df)


def _ensure_polars(df: object) -> pl.DataFrame:
    """nflreadpy returns Polars; be defensive if a pandas frame slips through."""
    if isinstance(df, pl.DataFrame):
        return df
    return pl.from_pandas(df)  # type: ignore[arg-type]
