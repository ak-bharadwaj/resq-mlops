# Architectural & Governance Decisions (DECISIONS.md)

Written for the Operations Manager and Engineering Leadership.

## 1. Track Selection: MLOps Architecture (Track F)
- **Chosen**: Track F — MLOps Architecture. Focus on end-to-end lifecycle governance, structural schema drift guards, deterministic evidence evaluation, atomic promotion/rejection, and reversible rollback.
- **Alternative Rejected**: Track ML (Novel Model Optimization).
- **Rationale**: Real-world operational reliability and field-dispatch economics depend on trustworthy lifecycle controls and audit trails. A complex model without strict contracts, replayability, and safe rollback poses higher business risk.

## 2. Evidence Mode & Ground-Truth Framing
- **Chosen**: Retrospective detection of degraded gateways using audited evidence (COST_BACKTEST with €600/week penalty differential, or HEURISTIC fallback if audit sanity < 3 cases).
- **Alternative Rejected**: Treating ambiguous visit notes as uncalibrated ground truth, or attempting onset forecasting without adequate labeled development data.
- **Rationale**: LPDG's ground truth is inaccessible and field visits represent a selection-biased sample (only suspected gateways were visited). We explicitly disclose evaluation scope: precision-oriented on observed subset, not fleet-wide recall.

## 3. Evaluation Gate: Expanding Temporal Windows + Grouped Holdout
- **Chosen**: Three rolling expanding training windows (Aug-Oct -> Nov, Aug-Nov -> Dec, Aug-Dec -> Jan) plus a strictly isolated set of grouped holdout gateways (`GROUP_HOLDOUT_IDS`).
- **Alternative Rejected**: Single temporal split or unstratified random k-fold cross-validation.
- **Rationale**: Directly answers the skeptic's requirement for forward-in-time stability and generalizability across unseen hardware. Promotion requires >=10% aggregate cost improvement, no regression in any individual month, and grouped holdout agreement.

## 4. 15-Visit Hard Limit & Deferred Backlog Reporting
- **Chosen**: predict.py always ranks all eligible gateways and emits the top 15 strictly formatted rows, writing ranks 16+ to `backlog_report.json`.
- **Alternative Rejected**: Outputting fewer than 15 rows when model confidence is low, or omitting low-confidence selections.
- **Rationale**: The challenge and operations contract mandates 15 dispatches per week (€45,600 fixed cost across 8 weeks). Emitting fewer than 15 violates submission contracts. Deferred risks are made visible to operations via backlog reports.

## 5. Rollback Mechanism: Atomic Filesystem Registry with Cryptographic Replay
- **Chosen**: Atomic pointer swap in `registry/active.json`, prior artifact pre-validation, and SHA-256 replay hash verification.
- **Alternative Rejected**: Rolling back by triggering a code rollback or re-training.
- **Rationale**: Operational rollback must be instantaneous (<1 second), fully offline, and demonstrably restore identical predictions.

## 6. Label Audit & Evaluation Target (`label_spec_v1`)
- **Chosen**: Pure deterministic failure proxy `label_gateway_week()` returning `BROKEN`, `NOT_BROKEN`, or `UNKNOWN_RIGHT_CENSORED`, evaluated under `COST_BACKTEST` mode with €600/week fault penalty accounting and `evidence_quality = "strong"`.
- **Alternative Rejected**: Treating all field visits as positive ground-truth failures, treating unobserved terminal outcomes at end-of-data as resolved healthy gateways, or using HEURISTIC mode despite passing interpretability sanity.
- **Rationale**:
  - **Empirical Development Audit (through 2026-01-31)**: Evaluated 628 historical visits; 218 confirmed hardware faults (`outcome == 'Fehler behoben'`) replacing power supplies (`Netzteil`: 38), antennas (`Antenne`: 36), cables (`Kabel`: 35), swapped gateways (`Gateway getauscht`: 28), and SIM cards (`SIM-Karte`: 25). 382 visits (60.8%) were false alarms (`Kein Fehler gefunden`), proving raw visit dispatch cannot be equated with ground-truth failure.
  - **Sanity Gate ($N \ge 3$)**: Three clear, documented historical cases (`0E61D34F9993` with replaced power supply, `0ED0849FD6D8` with replaced antenna, `0A68A2032450` with swapped hardware) confirm that pre-repair chronic telemetry and meter failures (meter read rate dropped to 39%) recover immediately post-visit (reboots drop to 0, meter read rate restores to 90.4%). Exactly 137 broken gateway-weeks are confirmed across the 13 rolling evaluation Mondays.
  - **Episode & Censoring Semantics**: €600/week penalty accrues across active broken weeks between fault request and visit resolution (inclusive of visit week per FAQ 5.2). Faults requested whose resolution cannot be observed before the observation window ends are classified as `UNKNOWN_RIGHT_CENSORED` and excluded from the economic evaluation denominator.
  - **Operational Limitations Disclosed**: Evaluation scope is `precision_biased_sample` (FAQ 4.4: only suspected gateways were visited; no row exists for quietly broken unvisited gateways). System detects already-degraded gateways retrospectively; early forecasting lead time is noted as a future enhancement.

## 7. Deterministic Candidate Scorer (`v0002`) & Frozen Feature Foundation
- **Chosen**: Deterministic weighted multi-signal scorer `WeightedMultiSignalScorer` in `app/model/scorer.py` combining 3-sigma anomaly persistence (`flagged_hours`, normalized to [0.0, 1.0]) and recent silence ratio (`recent_silence_ratio`, missing observations relative to 168 fixed expected hourly contract), with deterministic configuration weights $w_{\text{anomaly}} = 0.70$ and $w_{\text{silence}} = 0.30$.
- **Alternative Rejected**: Stochastic learners, complex ensembles, hyperparameter auto-tuning, or gateway-specific historical reporting denominators.
- **Rationale**:
  - **Silence Risk Remediation**: Baseline 3-sigma evaluates anomalies only over existing telemetry rows. A completely silent gateway emits zero rows and is erroneously scored as zero-risk (calm). Combining `recent_silence_ratio` explicitly scores total silence as high risk ($1.0 \times 0.30 = 0.30$), prioritizing silent gateways above normal calm reporting gateways ($0.0$).
  - **Fixed 168h Denominator**: Per v25 Section 2B, `recent_silence_ratio` uses the frozen hourly contract grain (168 expected hours in a 7-day window), never ambiguous gateway-specific historical averages.
  - **Missing Data Taxonomy**: Institutional non-coverage (zero rows in entire 28-day baseline) is classified as `NO_TELEMETRY` and excluded with audit logging, never fabricated as zero risk. Recently silent gateways with established history are preserved and surfaced via `recent_silence_ratio`.
  - **Grouped Holdout Isolation**: Canonical `GROUP_HOLDOUT_IDS` (59 gateways) are frozen deterministically into `registry/grouped_holdout.json` before candidate selection and strictly barred from candidate development/training via `HoldoutProtection` (Rule 8).
  - **Zero Production Mutation**: Candidate materialization (`train_candidate`) produces immutable package `models/v0002/` and training log `runs/training/train_v0002.json`, leaving `registry/active.json` byte-for-byte untouched (`v0001` remains active). Promotion is strictly deferred to the multi-window evidence gate in Task 15.

