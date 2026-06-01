# Real-Data Validation

_Last updated: 2026-06-01._

This project does not rely only on synthetic unit tests. The repeatable real-data
validator lives at `analytics/scripts/validate_real_data.py`.

## How to run

```bash
cd analytics
PYTHONPATH=. python -m scripts.validate_real_data
```

The script uses network data, so it is intentionally separate from the default
pytest suite.

## Sources

- `nflreadpy` / nflverse for player stats and fantasy identity crosswalks.
- Fantasy Football Calculator ADP REST API for historical PPR ADP. Their help
  docs state the API is free for personal/commercial use with requested
  attribution, and that historical ADP goes back to 2007.
- Internal projection baseline in `ffdraft/projections/baseline.py`. A clean
  free multi-season preseason projection feed was not found. The current
  baseline uses position-specific prior-production weights blended with the
  market positional curve from ADP. FantasyPros has a projections API, but
  access requires approval and the terms are restricted; the paid feeds found
  are not appropriate to bake into this repo.

## Latest run

Command:

```bash
cd analytics
PYTHONPATH=. .venv/bin/python -m scripts.validate_real_data
```

Result:

- Seasons validated: `2019, 2020, 2021, 2022, 2023, 2024`
- Weekly scoring decimal match: `105,480` regular-season nflverse weekly rows,
  `0` mismatches against `fantasy_points_ppr`.
- Weekly-to-season totals: top `100` PPR players per season, `600` player-season
  totals checked, `0` mismatches.
- Historical ADP identity: `1,021 / 1,028` offensive Fantasy Football Calculator
  ADP records resolved to nflverse identities, `7` unresolved,
  `0` low-confidence matches below `0.92`.
- Internal projection/VORP held-out gate:
  - `2019`: raw Spearman `0.5340`, VORP Spearman `0.5572`, delta `+0.0232`
  - `2020`: raw `0.4800`, VORP `0.5550`, delta `+0.0750`
  - `2021`: raw `0.4683`, VORP `0.5572`, delta `+0.0889`
  - `2022`: raw `0.5209`, VORP `0.5867`, delta `+0.0658`
  - `2023`: raw `0.4706`, VORP `0.5403`, delta `+0.0697`
  - `2024`: raw `0.4320`, VORP `0.4839`, delta `+0.0519`
  - Result: VORP beat raw projected points in `6 / 6` held-out seasons,
    average Spearman lift `+0.0624`.

## Phase 3 Backtest

Command:

```bash
cd analytics
PYTHONPATH=. .venv/bin/python -m scripts.backtest_phase3
```

Result (after strategy fix — VORP-primary + positional roster guardrails):

- Matched drafts: `1,800` (`2019-2024`, 12 draft slots, 25 seeds per slot).
- Draft shape: `12` teams, `12` offensive rounds, full-PPR starters scored
  against actual season points.
- Strategy compared: value-aware model drafting vs ADP-only.
- Season results:
  - `2019`: ADP `1555.91`, VALUE `1544.52`, diff `-11.39`, H2H `44.3%`
  - `2020`: ADP `1466.12`, VALUE `1536.27`, diff `+70.15`, H2H `62.3%`
  - `2021`: ADP `1508.97`, VALUE `1628.70`, diff `+119.73`, H2H `72.7%`
  - `2022`: ADP `1556.93`, VALUE `1640.89`, diff `+83.95`, H2H `69.0%`
  - `2023`: ADP `1552.62`, VALUE `1659.82`, diff `+107.20`, H2H `71.3%`
  - `2024`: ADP `1591.69`, VALUE `1594.62`, diff `+2.93`, H2H `52.7%`
- Overall: ADP `1538.71`, VALUE `1600.80`, diff `+62.10`, H2H `62.1%`.
- Gate: **PASS**. The model wins `5 / 6` seasons and clears the `>55%`
  head-to-head threshold.

## Gate Status

- Phase 0 identity/history: real-data validation now passes for the available
  ADP source and nflverse stat history. Ambiguous exact-name collisions now fail
  closed instead of selecting the first indexed player; the current unresolved
  records are Mike Williams and Frank Gore collisions that need manual aliases or
  source-specific IDs before production. The remaining original requirement is a
  hand-check sample when we commit a production ADP snapshot.
- Phase 1 scoring: real-data nflverse PPR decimal match passes. The live Sleeper
  decimal-match gate still waits on the real league's `scoring_settings`.
- Phase 2 valuation: deterministic unit gates pass. The held-out VORP-vs-raw
  Spearman gate passes using the internal preseason baseline. Tier bootstrap
  stability remains a separate validation item.
- Phase 3 backtest: harness is built and **passes the trust gate** (5/6 season
  wins, 62.1% H2H). The edge came from strategy fixes (VORP-primary drafting +
  roster guardrails) rather than projection accuracy improvements.
- Phase 4 simulator: deterministic unit gates pass. Calibration gate passes:
  Brier score 0.0003, mean absolute calibration error 1.05%, on 50 random
  mid-draft scenarios against 500 independent validation simulations each.
  The ADP+noise opponent model produces near-perfectly calibrated survival
  probabilities without needing historical draft boards.
