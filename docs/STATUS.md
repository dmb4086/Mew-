# Project Status & Handoff

_Last updated: 2026-05-31. Branch: `claude/fantasy-draft-system-w4j8X`._

This is the living "where are we / what's next" doc. Read
[`VISION.md`](VISION.md) first for the full architecture and the phased plan with
numeric green-light gates; this doc tracks execution against it.

---

## TL;DR for someone picking this up

- We are building a deterministic fantasy-draft copilot. **Math decides, the LLM
  only explains.** Every phase has a numeric gate — no "looks right to me."
- **Phases 0, 1, 2, 4 are built and unit-tested** (30 tests, all green, no network
  or DB required). Run them with `cd analytics && PYTHONPATH=. python -m pytest`.
- A real-data validator now checks public historical data; latest run validated
  2019-2024 nflverse scoring/totals and resolved 1,028/1,028 historical ADP
  records. It also validates the internal projection baseline: VORP beats raw
  projected points in 6/6 held-out seasons. See [`VALIDATION.md`](VALIDATION.md).
- The whole **edge-producing core (valuation, simulation, backtest) runs on
  historical data** and does NOT need the live league. Only Phase 5 (live sync)
  and Phase 6 (Zev model) require Zev's Sleeper league, which doesn't exist yet.
- **Two confirmed facts** about the target league: platform = **Sleeper**,
  scoring = **full PPR, standard roster** (no Superflex, no TE-premium). This
  matches `SLEEPER_DEFAULT_PPR` in `ffdraft/scoring/league.py`.

---

## What's done

| Phase | Status | Where | Gate status |
|------|--------|-------|-------------|
| 0 — Data spine + identity | **Built + ingested + validated** | `db/migrations/0001_phase0_schema.sql`, `ffdraft/identity/`, `ffdraft/nflverse/`, `scripts/` | Unit tests pass. DB contains 7,963 players, 104,447 weekly stats, 1,028 ADP records. **Three DB validation gates pass:** identity resolution 100% (offensive players), scoring decimal-match 99,783/99,783 rows, season totals 600/600 top-100 players. |
| 1 — League model + scoring | **Built** | `ffdraft/scoring/` | Unit gate passes. Real-data validator reproduces 105,480 nflverse PPR weekly rows exactly. **Live Sleeper decimal-match gate pending** real league settings. |
| 2 — Valuation engine | **Built** | `ffdraft/valuation/`, `ffdraft/projections/` | Unit gates pass. Held-out Spearman gate passes with internal projections (6/6 seasons). **Tier bootstrap-stability gate pending**. |
| 3 — Backtest harness | Not started | — | Historical ADP + internal projection baseline available; needs full draft/roster harness. |
| 4 — Draft simulator + availability | **Built** | `ffdraft/simulator/` | Unit gates pass. **Historical calibration gate pending** draft-history ingestion. |
| 5 — Live copilot + LLM advisor + UI | Not started | — | Needs live Sleeper league. Advisor/tools can be built against synthetic state first. |
| 6 — Zev model | Not started | — | Needs Zev's past drafts. |
| 7 — News / in-season | Deferred (post-draft) | — | Intentionally last. |

### Test suite
```bash
cd analytics
pip install -e ".[dev]"          # or: pip install pytest rapidfuzz python-dotenv pydantic
PYTHONPATH=. python -m pytest     # 30 tests, all green
```
The unit tests ARE the gates. They run with zero network/DB.

**Real-data validators (require network + DB):**
```bash
cd analytics

# Phase 0: network-only validation (reads from APIs directly)
PYTHONPATH=. python -m scripts.validate_real_data

# Phase 0: DB-backed validation gates (reads from Postgres)
PYTHONPATH=. python -m scripts.validate_db_gates

# Individual gates
PYTHONPATH=. python -m scripts.validate_db_identity_resolution
PYTHONPATH=. python -m scripts.validate_db_scoring

# Export a hand-check sample for gate (a)
PYTHONPATH=. python -m scripts.export_identity_audit_sample 50
```

---

## Key facts locked

1. **Platform: Sleeper** — read-only, no-auth API. The fast path.
2. **Scoring: full PPR, standard roster** — encoded as `SLEEPER_DEFAULT_PPR`.
   ⚠️ "standard settings" + "PPR" is mildly contradictory in football terms
   (standard usually = 0 PPR). We assume **full PPR (1.0/reception)** until the
   real `scoring_settings` API pull confirms; that pull is the source of truth.

## Still needed from the user (not blocking offline phases)

- **Sleeper league ID or a manager username.** Unlocks: exact settings (real
  Phase 1 gate), past drafts (Phase 6 raw material), and the draft date. The
  league reportedly **doesn't exist yet** — expected later.
- **Draft date** — to put real dates on the calendar.
- **Zev's past drafts** — likely free via the league's `previous_league_id`
  chain once the league ID exists.

## Data dependencies (the real external blockers)

- **nflverse history** (stats, player ID crosswalk): free via `nflreadpy`.
  Needs a network-enabled run + a Postgres/Supabase instance. Unblocks Phase 0
  live gate and Phase 1 live gate (nflverse weekly data carries a
  `fantasy_points_ppr` column we can reproduce to the decimal).
- **Historical ADP** (the market baseline Phase 3 must beat): source identified
  as Fantasy Football Calculator's ADP REST API, with attribution. The loader is
  in `ffdraft/adp/ffc.py`, and 2019-2024 PPR ADP identity validation passes.
- **Historical preseason projections / ECR / platform rankings:** no clean free
  multi-season feed was found that should be baked into this repo. FantasyPros
  has an API but requires approval and carries restricted terms; paid feeds
  exist. We built an internal baseline from prior nflverse production + FFC ADP
  in `ffdraft/projections/baseline.py`.
- **Historical draft boards:** still needed for Phase 4 availability calibration;
  ADP tables alone do not prove survival-probability calibration.

---

## Database setup

Local Postgres is running and populated. See [`DB_SETUP.md`](DB_SETUP.md) for
connection details, Supabase Studio setup, and example queries.

```bash
# Quick connect
psql -h localhost -p 5432 -U $(whoami) -d ffdraft

# Run all DB validation gates
PYTHONPATH=. python -m scripts.validate_db_gates
```

## Recommended next steps (in priority order)

These are ordered so nothing waits on the live league.

1. **Build Phase 3 full draft/roster backtest harness.** Historical ADP and an
   internal preseason projection baseline are now available. Next, simulate
   draft strategies (ADP-only vs. VORP/simulator-driven), build rosters, and
   score starter points against actual season outcomes.
2. **Wire Phase 4 into the Recommendation Object shape.** The simulator now
   emits per-player survival odds and ranked pick scores from VORP +
   availability risk. Define the typed object and tool interfaces that Phase 5's
   LLM advisor will consume, still against synthetic draft state.
3. **Phase 4 calibration gate** — once historical draft boards are ingested,
   bucket survival predictions and calculate the reliability curve + Brier score
   promised in `VISION.md`.

## Conventions for contributors

- **Math lives in `analytics/ffdraft/`. The LLM never computes a ranking** — it
  only consumes typed objects the math layer emits.
- **Determinism is non-negotiable:** snapshot + seed -> identical output. No
  hidden randomness; thread `settings.random_seed`.
- **Everything time-varying is an append-only snapshot** (see schema). Never
  UPDATE a projection/ADP row in place — reconstructing what we believed AT
  DRAFT TIME is the point.
- **Use `nflreadpy`, not `nfl_data_py`** (the latter is end-of-life).
- New deterministic logic ships with a hand-verifiable unit test in
  `analytics/tests/` — that test is the phase's gate, so make it objective.
- Keep web/UI concerns out of `analytics/`; that service is math-only.
