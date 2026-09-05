# RESQ-MLOps: LPDG Innovation Hub Selection Challenge 2026 (Track F)

Production-grade, contract-governed MLOps lifecycle system for smart meter gateway risk scoring and field visit prioritization.

## Quickstart (Reviewer Entry Point - P0 Contract)

As specified in the Challenge Brief and Section 5A of the architecture freeze, the reviewer workflow requires only:

```bash
# 1. Ensure dependencies are installed
pip install -r requirements.lock

# 2. Place raw challenge files in data/
# (data/telemetry, data/gateway_master.csv, data/field_visits.csv, data/meter_read_success.csv)

# 3. Run the canonical reviewer entry point
make run
```

`make run` executes the following single pipeline (Task 1 Foundation):
1. Validates the execution environment and required data files.
2. Loads master data with CP1252 encoding and ID normalization.
3. Verifies gateway eligibility foundation across all 8 required challenge weeks (Mondays: 2026-02-02 through 2026-03-23).

## Architecture & Lifecycle Commands

- `make run`: Single reviewer entry point (inference only, strictly no training).
- `make train`: Runs offline candidate construction, rolling-window backtesting, and evidence generation.
- `make predict`: Generates predictions for a single week or batch.
- `make promote`: Evaluates candidate against frozen promotion criteria (>=10% cost differential, no window regression, grouped holdout agreement).
- `make rollback`: Demonstrates atomic rollback from `v0002` to `v0001` with cryptographic replay proof.
- `make test`: Runs the automated test suite (all P0 contracts).
- `make drift`: Checks incoming telemetry against the frozen schema contract.

## Project Structure

```
resq-mlops/
|-- app/
|   |-- data/          # Ingestion, CP1252 parsing, ID normalisation, eligibility
|   |-- features/      # Frozen feature definitions, temporal boundary enforcement
|   |-- model/         # v0001 & v0002 inference, scoring, tie-breaking
|   |-- registry/      # Filesystem registry, atomic promotion, rollback
|   `-- monitoring/    # Structural schema drift monitor, reporting
|-- scripts/           # train.py, predict.py, make_submission.py, promote.py, rollback.py, check_drift.py
|-- models/            # Immutable model packages (v0001, v0002)
|-- registry/          # active.json, history.jsonl
|-- policy.json        # Frozen evaluation and retraining governance
|-- monitoring/        # schema_baseline.json, drift_reports/
|-- tests/             # P0 test matrix (determinism, rollback, gates, submission)
|-- docs/              # Architecture specification & challenge references
|-- DECISIONS.md       # Architectural decisions in operations-manager register
|-- MLOPS.md           # Detailed system design, contracts, state machines
|-- LIMITATIONS.md     # Honest scope boundaries and blind spots
`-- AI-USAGE.md        # AI assistance disclosure and verification log
```

## Operations-Manager Summary

This system does not claim complete fleet visibility or calibrated failure probability. It deterministically ranks gateways using observable telemetry and historical operational evidence, enforcing a mandatory 15-visit weekly cap while tracking deferred risk in backlog reports. All evaluations use expanding temporal holdouts and grouped unseen gateways.

## 6–8 Minute Walkthrough Recording (Operations-Manager Register)

Per Challenge Brief Part 1 and ARCHITECTURE_v25_FREEZE.md Section 17, the 6–8 minute operations-manager walkthrough video demonstrates the end-to-end lifecycle, deterministic rejection of `v0002`, and atomic rollback with replay proof:

- **Video Recording URL**: [LPDG Track F Walkthrough Recording](https://youtu.be/PLACEHOLDER_SUBMISSION_RECORDING) *(or local video file `docs/recording/walkthrough.mp4`)*
- **Storyline Structure (v25 Section 17)**:
  1. `0:00 - 1:00`: Core operational problem & why MLOps lifecycle governance (Track F) protects the €380/visit allocation.
  2. `1:00 - 2:15`: Clean clone execution via `make run` generating 120 validated predictions and passing `validate_submission.py`.
  3. `2:15 - 3:15`: Immutable model packages (`v0001`, `v0002`), dual-hash cryptographic provenance (`artifact_hash` & `replay_hash`).
  4. `3:15 - 4:15`: Inference determinism, Monday 00:00 UTC cutoff firewall, and schema drift detection.
  5. `4:15 - 5:15`: Evidence gate: multi-window rolling backtest, grouped holdout disagreement, and deterministic rejection of `v0002` (production preserved on `v0001`).
  6. `5:15 - 6:15`: Backlog economics: 15-visit weekly cap (€45,600 baseline) and deferred risk in `backlog_report.json`.
  7. `6:15 - 7:15`: Atomic rollback demonstration (`scripts/rollback.py`) with pre-validation and bit-for-bit replay proof.
  8. `7:15 - 8:00`: Measured telemetry coverage blind spot (12 unprovisioned gateways) and what two additional weeks would buy.
