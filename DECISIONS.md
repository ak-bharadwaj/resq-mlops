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
