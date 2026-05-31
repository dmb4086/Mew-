# Project Status & Handoff

_Last updated: 2026-05-31. Branch: `claude/fantasy-draft-system-w4j8X`._

This is the living "where are we / what's next" doc. Read
[`VISION.md`](VISION.md) first for the full architecture and the phased plan with
numeric green-light gates; this doc tracks execution against it.

---

## TL;DR for someone picking this up

- We are building a deterministic fantasy-draft copilot. **Math decides, the LLM
  only explains.** Every phase has a numeric gate — no "looks right to me."
- **Phases 0, 1, 2 are built and unit-tested** (19 tests, all green, no network
  or DB required). Run them with `cd analytics && PYTHONPATH=. python -m pytest`.
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
| 0 — Data spine + identity | **Code built**; live ingest not yet run | `db/migrations/0001_phase0_schema.sql`, `ffdraft/identity/`, `ffdraft/sleeper/`, `ffdraft/nflverse/`, `scripts/` | Unit tests pass. Live gate (≥99% top-300 resolve; reconstruct a past season's top-100 totals) **pending DB + ingestion run**. |
| 1 — League model + scoring | **Built** | `ffdraft/scoring/` | Unit gate passes. **Live decimal-match gate pending** real box-score fixtures. |
| 2 — Valuation engine | **Built** | `ffdraft/valuation/` | Unit gates pass. **Held-out Spearman + bootstrap-stability gate pending** ingested projections. |
| 3 — Backtest harness | Not started | — | Blocked on historical ADP (see Data dependencies). |
| 4 — Draft simulator + availability | Not started | — | Buildable now, no external data. |
| 5 — Live copilot + LLM advisor + UI | Not started | — | Needs live Sleeper league. Advisor/tools can be built against synthetic state first. |
| 6 — Zev model | Not started | — | Needs Zev's past drafts. |
| 7 — News / in-season | Deferred (post-draft) | — | Intentionally last. |

### Test suite
```bash
cd analytics
pip install -e ".[dev]"          # or: pip install pytest rapidfuzz python-dotenv pydantic
PYTHONPATH=. python -m pytest     # 19 tests, all green
```
The tests ARE the gates. They run with zero network/DB.

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
- **Historical ADP** (the market baseline Phase 3 must beat): NOT in nflverse.
  Needs a source we have rights to (model our own, or a licensed feed —
  FantasyPros etc. have ToS constraints). **This is the gating dependency for
  Phase 3.**

---

## Recommended next steps (in priority order)

These are ordered so nothing waits on the live league.

1. **Phase 4 — draft simulator + availability model.** Highest value, zero
   external data. Build a Monte Carlo of the rest of the draft with ADP+noise
   opponents, a per-candidate "probability survives to my next pick," and a
   `score_pick(value, availability)`. Suggested location:
   `ffdraft/simulator/`. Determinism: seed from `settings.random_seed`.
   Gate (Phase 4): reliability curve + Brier score on historical drafts — wire
   the calibration test as soon as draft history is ingested.
2. **Run live ingestion (Phase 0/1 live gates).** Stand up Supabase, apply
   `db/migrations/0001_phase0_schema.sql`, run `scripts/ingest_nflverse.py`,
   then add a scoring-gate test that reproduces nflverse `fantasy_points_ppr`
   from raw stats to the decimal.
3. **Source historical ADP**, then build **Phase 3 backtest harness** — the
   trust gate. Strategies to pit: ADP-only, ECR-only, platform-rankings,
   zero-RB, our VORP model. Bar: beat ADP-only & ECR-only on starter-points in
   ≥4 of 6 leave-one-out seasons and win >55% of head-to-head sims.
4. **Phase 5 advisor scaffolding against synthetic draft state** — define the
   typed Recommendation Object and the tool interfaces (`getDraftState`,
   `getPlayerCard`, `comparePlayers`, `simulateDraft`, `recommendPick`,
   `explainRecommendation`) before the live league exists.

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
