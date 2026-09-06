# Architectural Decisions (DECISIONS.md)

Written for the Operations Manager and Engineering Leadership.
In strict accordance with Challenge Part 1 deliverables and ARCHITECTURE_v25_FREEZE.md Section 16.

---

## 1. Track Selection: MLOps Architecture (Track F)

- **Decision**: Primary track chosen is **Track F (MLOps Architecture)**.
- **Alternative Rejected**: Track ML (Novel Model Optimization as primary focus).
- **Operations Rationale**: The central business challenge for LPDG is the allocation of €45,600 in fixed technician dispatch costs (15 visits/week × 8 weeks × €380) while mitigating €600 weekly fault penalties across an expanding operational fleet. In field operations, deploying a complex black-box model without cryptographic replay determinism, schema drift protection, or verified atomic rollback creates unacceptable financial and service reliability risks. Prioritizing lifecycle governance guarantees auditable, fail-closed maintenance decisions.

---

## 2. Evidence Mode & Ground-Truth Framing (`COST_BACKTEST`)

- **Decision**: Ground truth is framed around **retrospective detection of degraded hardware** evaluated under **`COST_BACKTEST`** mode (€600/week fault penalty differential), supported by audited historical work orders.
- **Alternative Rejected**: Treating raw field visits as uncalibrated positive ground truth, or framing the primary task as leading failure onset forecasting.
- **Operations Rationale**: Historical records show that 60.8% of past field visits (382 of 628) were false alarms where no fault was found (`Kein Fehler gefunden`). Only 218 visits involved confirmed component repairs (power supplies, antennas, swapped gateways). Equating every historical visit to a confirmed failure would severely miscalibrate dispatch priorities. Furthermore, field visits represent an operational selection bias (only suspected gateways were inspected; silently broken gateways lack visit records). The €600/week penalty delta measures real avoided operational losses on confirmed hardware episodes, while the forgone lead-time of retrospective detection is transparently acknowledged in `LIMITATIONS.md`.

---

## 3. Model Architecture & Scope (`v0001` vs `v0002`)

- **Decision**: Maintain **`v0001` (3-sigma baseline anomaly scorer)** as the immutable production foundation, with **`v0002` (deterministic weighted multi-signal scorer)** developed as an offline candidate combining 3-sigma anomaly persistence ($w_{\text{anomaly}} = 0.70$) and recent silence ratio ($w_{\text{silence}} = 0.30$) over a fixed 168-hour weekly grain, bounded by an authoritative **4-hour EDA feature freeze**.
- **Alternative Rejected**: Unconstrained statistical learners, stochastic gradient models, dynamic threshold auto-tuning, open-ended EDA, or gateway-specific reporting denominators.
- **Operations Rationale**: In production, the 3-sigma baseline exhibits a critical vulnerability: completely silent gateways emit zero telemetry rows and are falsely scored as calm (zero risk). The candidate explicitly scores total silence as high risk ($1.0 \times 0.30 = 0.30$), prioritizing silent uncommunicative assets ahead of healthy reporting hardware. Per v25 architecture, candidate feature discovery and EDA were strictly timeboxed to four hours and restricted strictly to development data ($\le$ 2026-01-31) with the 59 holdout gateways quarantined. Features and weights were permanently frozen at the deadline without holdout tuning, preventing post-hoc parameter snooping and preserving full operational explainability within the mandatory 300-character dispatch reason field.

---

## 4. Promotion Gate, Candidate Rejection & Atomic Rollback

- **Decision**: Implement a **four-condition deterministic promotion gate** evaluated over three expanding temporal windows (Nov, Dec, Jan) plus an isolated grouped fleet holdout (`GROUP_HOLDOUT_IDS`), paired with an **atomic filesystem rollback mechanism** with cryptographic replay verification.
- **Alternative Rejected**: Promoting candidate `v0002` based solely on its aggregate temporal score, relaxing the holdout constraint, or relying on code redeployments / manual intervention for rollback.
- **Operations Rationale**: Candidate `v0002` achieved an aggregate 15.49% reduction in missed broken weeks on the development fleet (71 missed in active vs 60 in candidate, saving €6,600 in simulated fault penalties with zero window regressions). However, on the 59 unseen holdout gateways, candidate `v0002` regressed (17 missed in active vs 18 in candidate). The promotion policy strictly failed closed with `REJECT_GROUPED_DISAGREEMENT`, keeping production safely anchored on `v0001`. For operational agility, rollback is achieved in $<1$ second via atomic pointer swap in `registry/active.json`, restoring exact bit-for-bit replay equality.

---

## 5. Data Correctness & Operational Fleet Boundaries

- **Decision**: Enforce authoritative **canonical gateway-ID normalization** (`^[0-9A-F]{12}$`), strict **Monday 00:00:00 UTC cutoff firewalls** across all ingestion paths, a **fleet source-completeness guard** (tripping to `BLOCK_FEATURES` if $>50\%$ of eligible gateways are missing), and a **mandatory 15-visit submission contract** with deferred assets tracked in `backlog_report.json`.
- **Alternative Rejected**: Allowing inconsistent colon-separated/bare ID joins, soft wall-clock timestamps (`datetime.now()`), fabricating zeros for unobserved gateways, or emitting fewer than 15 weekly dispatches when model confidence is low.
- **Operations Rationale**: Operations requires exactly 15 technician dispatches every Monday (€45,600 committed across 8 weeks). Emitting fewer than 15 visits violates service agreements, while emitting unverified padding incurs wasted truck-roll opportunity costs. Gateways with zero historical telemetry are classified as `NO_TELEMETRY` rather than scored with fabricated calmness. High-risk gateways ranked 16+ are preserved with full economic impact in `backlog_report.json` so dispatch managers retain complete visibility into deferred fleet risk.
