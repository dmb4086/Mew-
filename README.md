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
    identity/resolver.py  Player identity resolver (Sleeper <-> nflverse <-> ADP)
    scoring/engine.py      League scoring engine (Phase 1)
    scoring/league.py      League settings model
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
- **Phase 1 — League model + scoring engine:** scaffolded
  (`ffdraft/scoring/`), gate test pending real box-score fixtures.

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
```

## The one hard rule

The LLM may only speak from a typed **Recommendation Object** emitted by the
math layer. It never computes a ranking itself. Given a snapshot + a random
seed, the pipeline is deterministic and reproducible.
