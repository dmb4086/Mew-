"""nflverse historical-data integration (via nflreadpy)."""

from .loader import load_seasonal_stats, load_weekly_stats, load_player_ids

__all__ = ["load_seasonal_stats", "load_weekly_stats", "load_player_ids"]
