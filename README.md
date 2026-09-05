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
