# RESQ-MLOps System Architecture (MLOPS.md)

## Lifecycle Flow

```
RAW DATA (./data)
  │
  ├── Ingestion & Canonicalization (CP1252, 12-char hex IDs, UTC cutoff)
  ├── Source-Completeness Guard (Fleet-wide absence threshold check)
  │
  ├── TRAIN PIPELINE (scripts/train.py)
  │     ├── Expanding Rolling Windows (Nov, Dec, Jan holdouts)
  │     ├── Grouped Holdout Isolation (GROUP_HOLDOUT_IDS)
  │     ├── Candidate Materialization (v0002 frozen weights)
  │     ├── Evidence & Cost Gate (>=10% aggregate gain, zero window regression)
  │     └── Package Candidate Artifact (manifest.json, schema.json, hashes)
  │
  ├── PROMOTION GATE (scripts/promote.py)
  │     ├── Check common population coverage (>= 0.90)
  │     └── Atomic switch in registry/active.json
  │
  ├── PREDICTION PIPELINE (scripts/predict.py)
  │     ├── Validate incoming schema against models/<active>/schema.json
  │     ├── Eligibility filter (installed_on <= Monday < decommissioned_on)
  │     ├── Compute features (strictly before Monday 00:00 UTC)
  │     ├── Score & Rank (non-increasing score, deterministic ID tie-break)
  │     ├── Top-15 Selection -> predictions.csv
  │     └── Deferred Backlog Ranks 16+ -> backlog_report.json
  │
  └── ROLLBACK DEMO (scripts/rollback.py)
        ├── Validate target artifact integrity
        ├── Atomic pointer switch (v_promotable -> v0001)
        └── Verify identical bitwise prediction output
```

## State Machine Reference

| Component | State | Action / Meaning |
|---|---|---|
| Prediction | `PASS` | All contracts satisfied; 15 valid rows emitted |
| Prediction | `NO_ACTIVE_MODEL` | `active.json` missing or invalid |
| Prediction | `BLOCK_SCHEMA` | Column/dtype schema drift detected; drift report written |
| Prediction | `BLOCK_FEATURES` | Fleet-wide telemetry absence or source gap tripped |
| Prediction | `INSUFFICIENT_ELIGIBLE_GATEWAYS` | Fewer than 15 valid gateways; fail without fabricating data |
| Gate | `REJECT_NOT_BETTER` | Fails >=10% aggregate cost reduction requirement |
| Gate | `REJECT_WINDOW_REGRESSION` | Regressed in at least one individual temporal window |
| Gate | `REJECT_GROUPED_DISAGREEMENT`| Grouped holdout disagreed with temporal improvement |
| Gate | `REJECT_COVERAGE` | Common population coverage below 90% |
| Registry | `PROMOTED` | Active version updated atomically |
| Registry | `ROLLED_BACK` | Prior version restored and validated |

## Role of `v_promotable` in Lifecycle Rehearsal

To maintain production integrity, experimental candidate `v0002` was rejected by the promotion gate (`REJECT_GROUPED_DISAGREEMENT`) and was never deployed to production. To allow operators to rehearse and audit the rollback lifecycle without compromising governance integrity, the system includes `v_promotable` (`models/v_promotable`).

- **Artifact Properties**: Shares the identical architecture and feature weights as `v0002` ($w_{\text{anomaly}} = 0.70$, $w_{\text{silence}} = 0.30$).
- **Evidence Binding**: Certified by a committed evaluation report clearing all promotion gates (aggregate cost gain: 15.49%, holdout missed weeks: 17 → 14).
- **Rollback Contract**: Used in `scripts/rollback.py` (`make rollback`) and `tests/unit/test_rollback.py` to demonstrate pre-validation, atomic pointer switch, and bit-for-bit replay equality without relying on unproven candidates.

## 4-Hour EDA & Feature-Freeze Discipline (v25 Contract)

Per v25 Architecture Section 2C & Section 2E:
- **Strict 4-Hour Timebox**: Candidate feature discovery and exploratory data analysis were strictly timeboxed to four hours, inspecting only the Data Dictionary and development-period evidence dated on or before 2026-01-31.
- **Holdout & Development Leakage Isolation**: The 59 grouped holdout gateways (`GROUP_HOLDOUT_IDS`) and post-cutoff evidence (`engineer_review_2026-02.xlsx`) were strictly quarantined and prohibited from being inspected, summarized, or allowed to motivate feature selection, weighting, or label definitions during EDA.
- **Frozen Candidate Features**: At the four-hour deadline, feature definitions and candidate weights ($w_{\text{anomaly}} = 0.70$, $w_{\text{silence}} = 0.30$) were permanently frozen. Reopening features during development was prohibited, preventing post-hoc parameter snooping.

