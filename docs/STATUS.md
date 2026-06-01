# Project Status & Handoff

_Last updated: 2026-06-01. Branch: `codex/improve-projection-edge`._

This is the living "where are we / what's next" doc. Read
[`VISION.md`](VISION.md) first for the full architecture and the phased plan with
numeric green-light gates; this doc tracks execution against it.

---

## TL;DR for someone picking this up

- We are building a deterministic fantasy-draft copilot. **Math decides, the LLM
  only explains.** Every phase has a numeric gate — no "looks right to me."
- **Phases 0, 1, 2, 3, 4 are built and unit-tested** (50 tests, all green, no network
  or DB required). Run them with `cd analytics && PYTHONPATH=. python -m pytest`.
- A real-data validator now checks public historical data; latest run validated
  2019-2024 nflverse scoring/totals and resolved 1,021/1,028 historical ADP
  records after failing closed on ambiguous name collisions. It also validates the internal projection baseline: VORP beats raw
  projected points in 6/6 held-out seasons. See [`VALIDATION.md`](VALIDATION.md).
- **Phase 3 backtest trust gate now PASSES**: the value-aware model beats
  ADP-only in `5/6` seasons with `62.1%` head-to-head wins (1,800 matched
  drafts). The fix was VORP-primary drafting with positional roster guardrails
  to prevent degenerate zero-RB rosters in years where RBs boom.
- **Edge Lab now PASSES against a stronger baseline**: `value_market_rb` beats
  `ADP+guardrails` by `+64.60` starter points, with `63.7%` head-to-head wins
  and `5/6` season wins over 1,800 matched drafts.
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
| 0 — Data spine + identity | **Code built**; live ingest not yet run | `db/migrations/0001_phase0_schema.sql`, `ffdraft/identity/`, `ffdraft/sleeper/`, `ffdraft/nflverse/`, `scripts/` | Unit tests pass. Real-data validator resolves 1,021/1,028 FFC ADP records, leaves ambiguous name collisions unresolved, and recomputes top-100 season totals exactly. **DB ingestion run still pending**. |
| 1 — League model + scoring | **Built** | `ffdraft/scoring/` | Unit gate passes. Real-data validator reproduces 105,480 nflverse PPR weekly rows exactly. **Live Sleeper decimal-match gate pending** real league settings. |
| 2 — Valuation engine | **Built** | `ffdraft/valuation/`, `ffdraft/projections/` | Unit gates pass. Held-out Spearman gate passes with internal projections (6/6 seasons). **Tier bootstrap-stability gate pending**. |
| 3 — Backtest harness | **Built** | `ffdraft/backtest/`, `scripts/backtest_phase3.py`, `scripts/edge_lab.py`, `scripts/edge_failure_modes.py` | **Trust gate PASSES**: `5/6` season wins, `62.1%` H2H vs ADP-only. **Edge Lab PASSES** vs `ADP+guardrails`: `5/6` season wins, `63.7%` H2H. |
| 4 — Draft simulator + availability | **Built** | `ffdraft/simulator/` | Unit gates pass. Calibration gate passes: Brier 0.0003, MAE 1.05% on 50 scenarios. |
| 5 — Live copilot + LLM advisor + UI | Not started | — | Needs live Sleeper league. Advisor/tools can be built against synthetic state first. |
| 6 — Zev model | Not started | — | Needs Zev's past drafts. |
| 7 — News / in-season | Deferred (post-draft) | — | Intentionally last. |

### Test suite
```bash
cd analytics
pip install -e ".[dev]"          # or: pip install pytest rapidfuzz python-dotenv pydantic
PYTHONPATH=. python -m pytest     # 50 tests, all green
```
The tests ARE the gates. They run with zero network/DB.

Real-data validator:
```bash
cd analytics
PYTHONPATH=. python -m scripts.validate_real_data
PYTHONPATH=. python -m scripts.edge_lab --seeds-per-slot 25 --enforce-edge
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

## Recommended next steps (in priority order)

These are ordered so nothing waits on the live league.

1. **Harden the edge candidate.** Edge Lab now shows real strategy signal
   against `ADP+guardrails`; `value_market_rb` fixes the 2024 failure by using
   market order inside forced early-RB windows. `2019` still loses badly and is
   the next failure mode to solve before moving this into the advisor.
2. **Run live ingestion (Phase 0/1 live gates).** Stand up Supabase, apply
   `db/migrations/0001_phase0_schema.sql`, run `scripts/ingest_nflverse.py`,
   then add a scoring-gate test that reproduces nflverse `fantasy_points_ppr`
   from raw stats to the decimal.
3. **Build Phase 5 LLM advisor tool interface.** Define the typed
   Recommendation Object and tool functions (`getDraftState`, `getPlayerCard`,
   `comparePlayers`, `simulateDraft`, `recommendPick`, `explainRecommendation`)
   that the LLM will call. Can be built and tested against synthetic draft state.
4. **Mock draft UI / CLI** — a minimal interface showing pick clock, "take this",
   "wait on," "gone before your next pick," and roster-weakness-if-you-pass.

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
