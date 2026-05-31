# Real-Data Validation

_Last updated: 2026-05-31._

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
  free multi-season preseason projection feed was not found. FantasyPros has a
  projections API, but access requires approval and the terms are restricted;
  the paid feeds found are not appropriate to bake into this repo.

## Latest run

Command:

```bash
cd analytics
PYTHONPATH=. /tmp/ffdraft-verify-venv/bin/python -m scripts.validate_real_data
```

Result:

- Seasons validated: `2019, 2020, 2021, 2022, 2023, 2024`
- Weekly scoring decimal match: `105,480` regular-season nflverse weekly rows,
  `0` mismatches against `fantasy_points_ppr`.
- Weekly-to-season totals: top `100` PPR players per season, `600` player-season
  totals checked, `0` mismatches.
- Historical ADP identity: `1,028 / 1,028` offensive Fantasy Football Calculator
  ADP records resolved to nflverse identities, `0` unresolved,
  `0` low-confidence matches below `0.92`.
- Internal projection/VORP held-out gate:
  - `2019`: raw Spearman `0.5163`, VORP Spearman `0.5168`, delta `+0.0006`
  - `2020`: raw `0.4538`, VORP `0.5140`, delta `+0.0602`
  - `2021`: raw `0.4587`, VORP `0.5324`, delta `+0.0737`
  - `2022`: raw `0.5244`, VORP `0.5829`, delta `+0.0585`
  - `2023`: raw `0.4556`, VORP `0.5480`, delta `+0.0924`
  - `2024`: raw `0.4272`, VORP `0.4766`, delta `+0.0495`
  - Result: VORP beat raw projected points in `6 / 6` held-out seasons,
    average Spearman lift `+0.0558`.

## Gate Status

- Phase 0 identity/history: real-data validation now passes for the available
  ADP source and nflverse stat history. The remaining original requirement is a
  hand-check sample when we commit a production ADP snapshot.
- Phase 1 scoring: real-data nflverse PPR decimal match passes. The live Sleeper
  decimal-match gate still waits on the real league's `scoring_settings`.
- Phase 2 valuation: deterministic unit gates pass. The held-out VORP-vs-raw
  Spearman gate passes using the internal preseason baseline. Tier bootstrap
  stability remains a separate validation item.
- Phase 3 backtest: historical ADP source and internal projections are now
  available; the full draft/roster backtest harness itself is not built yet.
- Phase 4 simulator: deterministic unit gates pass. Calibration still needs
  historical draft boards or live/mock Sleeper drafts, not just ADP tables.
