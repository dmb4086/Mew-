# Mew — Fantasy Draft System

A deterministic fantasy-football draft copilot. The math layer (projections,
valuation, simulation) decides; an LLM only explains. See
[`docs/VISION.md`](docs/VISION.md) for the full vision, architecture, and the
phased plan with numeric green-light gates.

## Repository layout

```
docs/                     Vision & architecture
db/migrations/            Postgres/Supabase schema (snapshot tables)
analytics/                Python analytics service (all the math)
  ffdraft/
    config.py             Env-driven config
    db.py                 Postgres connection helpers
    sleeper/client.py     Sleeper read-only API client
    nflverse/loader.py    nflreadpy historical-data loader
    adp/ffc.py            Fantasy Football Calculator historical ADP loader
    projections/          Internal preseason projection baseline
    identity/resolver.py  Player identity resolver (Sleeper <-> nflverse <-> ADP)
    scoring/engine.py      League scoring engine (Phase 1)
    scoring/league.py      League settings model
    valuation/engine.py    Replacement level + VORP (Phase 2)
    valuation/tiers.py     Tier / cliff detection (Phase 2)
    backtest/              Historical draft/roster backtest harness (Phase 3)
    simulator/engine.py    Snake draft Monte Carlo + availability (Phase 4)
  scripts/                Ingestion entrypoints
  tests/                  Pytest suite (the gates live here)
```

## Status

- **Phase 0 — Data spine + identity + history:** in progress.
  - [x] Snapshot schema (`db/migrations/0001_phase0_schema.sql`)
  - [x] Sleeper API client
  - [x] nflverse loader (`nflreadpy`)
  - [x] Player identity resolver
  - [ ] Ingest 6 seasons of history + pass Gate 0
- **Phase 1 — League model + scoring engine:** built (`ffdraft/scoring/`); unit
  gate passing, live decimal-match gate pending real box-score fixtures.
- **Phase 2 — Valuation engine:** built (`ffdraft/valuation/`) —
  flex-aware replacement levels, VORP, value-vs-ADP, tier/cliff detection. Unit
  gates passing; the held-out Spearman + bootstrap-stability gate runs once
  historical projections are ingested.
- **Phase 3 — Backtest harness:** built (`ffdraft/backtest/`,
  `scripts/backtest_phase3.py`) — compares model drafting vs ADP-only in
  matched historical rooms. Current internal-projection model fails the trust
  gate, which means projection/strategy quality needs work before Phase 4/5.
- **Phase 4 — Draft simulator + availability:** built (`ffdraft/simulator/`) —
  snake order, ADP+noise opponent picks, per-player survival probability to your
  next pick, and ranked pick scores from VORP + pass risk. Unit gates passing;
  historical calibration waits on ingested draft boards.
- **Real-data validation:** built (`scripts/validate_real_data.py`) — validates
  nflverse scoring/totals, Fantasy Football Calculator ADP identity, and the
  internal projection/VORP held-out gate against public historical data. See
  `docs/VALIDATION.md`.

The valuation and simulation engines need no live league — they run on
historical or synthetic draft state with the confirmed full-PPR config. Only
Phase 5 (live sync) and Phase 6 (Zev model) require his league.

## Quick start (analytics service)

```bash
cd analytics
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure Postgres/Supabase
cp .env.example .env   # then edit DATABASE_URL

# Apply the schema
psql "$DATABASE_URL" -f ../db/migrations/0001_phase0_schema.sql

# Run tests (the gates)
pytest

# Run real-data validation (network required)
PYTHONPATH=. python -m scripts.validate_real_data
```

## The one hard rule

The LLM may only speak from a typed **Recommendation Object** emitted by the
math layer. It never computes a ranking itself. Given a snapshot + a random
seed, the pipeline is deterministic and reproducible.
