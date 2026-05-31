"""Player identity resolution across Sleeper, nflverse, and ADP sources."""

from .resolver import IdentityResolver, ResolvedAlias, normalize_name

__all__ = ["IdentityResolver", "ResolvedAlias", "normalize_name"]
