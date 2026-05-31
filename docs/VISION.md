# Fantasy Draft System — Vision & Architecture

> **Core thesis:** The LLM is the mouth, not the brain. All ranking, valuation,
> and simulation come from deterministic tools we control; the model only
> explains and converses.

## Honest expectation reset

We are **not** building an oracle. Football has irreducible randomness — a star
tears an ACL in Week 2 and a perfect projection is worthless. We are building a
**better decision-maker under uncertainty**: one that makes systematically
smarter picks than a human can, and that exploits the fact that our opponents
(Zev included) are predictable.

Beating one specific opponent in a single season is mostly variance. A great
draft is necessary but not sufficient — injuries, waivers, and luck swing any
one season. What we can prove and rely on is **edge in expectation**. Over many
simulated leagues we prove the edge is real and large; in the one live league
this year we tilt the odds hard in our favor, but it is not a guarantee.

**Biggest change to the original plan:** backtesting is not a late feature, it
is the *validation substrate* for the entire project. Because we cannot
sanity-check a pick by football instinct, every phase gets an objective,
number-based green-light gate. No "looks right to me" allowed.

## The five football concepts that matter

- **PPR / scoring format** — how points are awarded (e.g. "PPR" = 1 point per
  reception). Different leagues score differently, which changes which players
  are valuable. Getting the exact scoring right is step one.
- **ADP (Average Draft Position)** — where players typically get drafted across
  the market. This is the *market price*. Our projections are *private value*.
  Edge = the gap between the two.
- **Replacement level / VORP (Value Over Replacement Player)** — a player is
  valuable relative to the worst startable player at their position. A QB who
  scores 300 points isn't impressive if the 12th-best QB scores 290. VORP is the
  real currency.
- **Tiers & scarcity** — players cluster into quality tiers with cliffs between
  them. The skill is "take the last player before a cliff at a position you'll
  struggle to fill later," not "take the best player."
- **Snake draft & availability** — you pick, then wait ~22 picks (order reverses
  each round). The right pick is the best player who *won't survive* to your next
  turn. This is where simulation beats human intuition.

## Architecture (five layers)

1. **Warehouse** — Postgres/Supabase where everything is a time-stamped
   snapshot. We must be able to reconstruct what the system believed *at draft
   time*, not after the season.
2. **Projection engine** — per-player point projections.
3. **Valuation engine** — the heart: VORP, scarcity, tiers.
4. **Draft simulator** — Monte Carlo of the rest of the draft.
5. **LLM advisor with tools** — converses, explains, never computes rankings.

### The one hard rule

The LLM may only speak from a typed **Recommendation Object**. The math layer
emits a structured object (recommended player, score, alternatives, reasons,
risks, data timestamp); the LLM turns it into English and answers follow-ups. It
never computes a ranking itself. Paired with **determinism** — given a snapshot +
a random seed, the pipeline produces identical output — so we can reproduce,
debug, and backtest.

## Key technical decisions

- **Default to Sleeper, hard.** Read-only, free, no auth, clean
  `/draft/{id}/picks` endpoint, 1000 calls/min. ESPN needs private cookies
  (`swid` + `espn_s2`); Yahoo needs full OAuth. If Zev's league is ESPN/Yahoo we
  adapt, but Sleeper cuts weeks off the build.
- **Use `nflreadpy`, not `nfl_data_py`.** The latter is end-of-life; all
  development moved to `nflreadpy` (Polars-based, current).
- **Split the stack cleanly.** Next.js + Supabase for app/UI; a separate Python
  analytics service (Polars/pandas, scikit-learn, xgboost) for all the math. The
  LLM is a tool-calling agent only. No valuation logic in the web app.
- **Known gap:** "expected fantasy points" / opportunity modeling
  (`ffopportunity`) is R-native. For v0 we skip it and use raw opportunity volume
  from play-by-play (targets, carries, snap share, red-zone touches). A real
  opportunity model can come later via a small R sidecar. Not a v1 blocker.

## Calendar reality

It's late May. NFL fantasy drafts happen mid-to-late August → ~11–12 weeks.

- **Now → July:** build all plumbing and prove the methodology on historical
  seasons. Early 2026 projections are noisy (small-sample ADP), so this is the
  perfect window for infrastructure + backtesting where the answer is known.
- **August:** real projections firm up after camp/preseason. System goes live,
  we tune, we run mock drafts.

The edge-producing core (valuation + simulation + Zev-modeling) must be done
before mid-August; news automation and in-season tools come after the draft.

## The phased plan — every phase has a numeric green-light

### Phase 0 — Data spine + identity + history
**Build:** Supabase schema with snapshot tables (players, aliases, projections,
ADP, depth charts, injuries, drafts, picks — all time-versioned); player identity
resolver mapping Sleeper ↔ nflverse ↔ ADP IDs; ingest 6 seasons of historical
nflverse data.
**🟢 Gate:** (a) ≥99% of the top ~300 players-by-ADP resolve across all ID
systems, with a hand-checked sample of 50 showing zero silent mismatches; (b) we
can recompute a known past season's fantasy totals for the top 100 players from
raw data.

### Phase 1 — League model + scoring engine
**Build:** import a league's exact settings (roster slots, PPR/half/standard,
passing-TD value, bonuses, Superflex, etc.); a calculator that turns any stat
line into fantasy points under arbitrary rules.
**🟢 Gate (killer objective test):** feed a real historical week's box scores +
a league's exact scoring into the engine and reproduce the platform's officially
reported fantasy points *to the decimal*. Pass/fail, no judgment.

### Phase 2 — Projections + valuation engine
**Build:** ingest projections from 2–3 sources (or build a blended model from
historical + opportunity volume; external feeds like FantasyPros have
licensing/ToS constraints — model our own or use sources we have rights to);
replacement-level calculator (league-specific — Superflex makes QBs explode);
VORP; tiers + tier-cliff detection.
**🟢 Gate:** on held-out seasons, VORP-ranking from preseason projections must
correlate with actual end-of-season value better than raw-projection-ranking
does (Spearman, multiple seasons), and tier boundaries must be stable under
bootstrap resampling.

### Phase 3 — Backtest harness → the trust gate
**Build:** simulate full drafts on historical seasons using competing strategies
— ADP-only, ECR-only, platform-rankings, zero-RB, our model — then score the
resulting rosters against what actually happened.
**🟢 Gate (define the bar before running):** across ~6 leave-one-out seasons,
our model must beat ADP-only and ECR-only baselines on starter-points in ≥4 of 6
seasons and win >55% of head-to-head simulated leagues. If it fails, do not
proceed — fix valuation.

### Phase 4 — Draft simulator + availability model → calibration gate
**Build:** Monte Carlo (1k–10k sims) of how the rest of the draft unfolds;
per-candidate "probability this player survives to my next pick"; a `score_pick`
that weighs value against availability. (Opponents = ADP + noise for now;
Zev-specific modeling lands in Phase 6.)
**🟢 Gate (calibration, not vibes):** on historical drafts, bucket availability
predictions and check empirical frequencies — when it says "70% available," it
must be right ~70% of the time (reliability curve + Brier score under a
threshold).

### Phase 5 — Live copilot + LLM advisor + the UI
**Build:** Sleeper live draft sync (poll → reconcile board → recompute needs →
re-simulate → recommend); the LLM advisor with tools (`getDraftState`,
`getPlayerCard`, `comparePlayers`, `simulateDraft`, `recommendPick`,
`explainRecommendation`); the live-draft screen (pick clock, "take this," "wait
on," "gone before your next pick," roster-weakness-if-you-pass).
**🟢 Gate:** ≥10 end-to-end Sleeper mock drafts with zero crashes and zero board
desyncs (state reconciliation every pick); recommendation refreshes within the
pick-clock budget (target <3–5s after each opponent pick); the system, drafting
blind, beats the field's median projected starter-points in a strong majority of
runs.

### Phase 6 — The Zev model (opponent exploitation) → prediction-accuracy gate
**Build:** a manager-tendency model from Zev's past drafts (position-by-round
patterns, reaches, QB/TE timing, rookie bias, favorite-team lean, how slavishly
he follows platform rankings) fed into the simulator so it predicts Zev's picks,
not generic ADP.
**🟢 Gate:** on Zev's historical drafts, top-3 next-pick prediction must beat an
ADP-only opponent model by a clear margin — and swapping generic opponents for
the Zev-model must measurably improve simulated final-roster value. If it doesn't
help, drop the complexity. (Lives or dies on getting his past drafts.)

### Phase 7 — Post-draft / stretch
Automated news → impact classification → projection deltas, depth-chart/injury
snapshots, eventually waiver/lineup tools. Deliberately after the draft. For
draft day, a human-in-the-loop adjustment covers the gap, avoiding the
hardest/most error-prone subsystem (news entity-resolution) blocking the August
deadline.

## Open questions to lock Phase 0

1. ✅ **Platform: Sleeper.** Read-only, no-auth API — the fast path. Confirmed.
2. ✅ **Scoring: full PPR, standard roster.** Not Superflex, not TE-premium. This
   matches `SLEEPER_DEFAULT_PPR` in `ffdraft/scoring/league.py` exactly (1.0
   pt/reception, 4pt pass TD, 6pt rush/rec TD, standard QB/RB/RB/WR/WR/TE/FLEX).
   The real league's `scoring_settings` will be pulled via API and is the source
   of truth that feeds the Phase 1 decimal-match gate.
3. ⏳ **Past drafts** (and ideally Zev's specifically) — needed for the Phase 6
   Zev model. Available for free via the Sleeper API once we have the league ID;
   previous seasons are reachable through the league's `previous_league_id` chain.
4. ⏳ **Draft date** — still needed to put real dates on the calendar.

**Next concrete step:** provide the Sleeper **league ID** (or a manager username —
we can resolve leagues from `/user/{username}/leagues/nfl/{season}`). That single
value unlocks live settings ingestion, past-draft history, and the real Phase 1
scoring gate against actual box scores.
