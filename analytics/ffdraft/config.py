"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Six seasons of history is the Phase 0 default (serves both current use and
# backtesting). Override with FFDRAFT_SEASONS.
_DEFAULT_SEASONS = [2019, 2020, 2021, 2022, 2023, 2024]


def _parse_seasons() -> list[int]:
    raw = os.getenv("FFDRAFT_SEASONS")
    if not raw:
        return list(_DEFAULT_SEASONS)
    return [int(s.strip()) for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ffdraft"
        )
    )
    seasons: list[int] = field(default_factory=_parse_seasons)
    # Determinism: a fixed seed makes the whole pipeline reproducible.
    random_seed: int = field(default_factory=lambda: int(os.getenv("FFDRAFT_SEED", "1729")))


settings = Settings()
