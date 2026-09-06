# System Limitations & Operational Boundaries (LIMITATIONS.md)

Written for the Operations Manager, Dispatch Planners, and Engineering Leadership.
In strict accordance with Challenge Part 1 deliverables and ARCHITECTURE_v25_FREEZE.md Sections 14 and 18.

---

## 1. Measured Telemetry-Coverage Blind Spot (Fleet Non-Coverage)

- **Audited Fleet Measurement**:
  - **Total Fleet Size**: 332 smart meter gateways registered in `gateway_master.csv`.
  - **Active Reporting Fleet**: 320 gateways have at least one valid telemetry record.
  - **Institutional Blind Spot**: **12 gateways (3.61% of fleet)** have **zero historical telemetry records** across the entire operational recording period.
  - **Affected Gateway Identifiers**:
    `02BCBAD30D53`, `02E1C70E46D1`, `02F25E3EAE98`, `0686FFF4B846`, `06C662180A40`, `06F44C2A64BD`, `06FEDE0E7789`, `0AD39BC595EF`, `0AEF2E5A50F0`, `0E4056A2CD08`, `0E8417B08FC9`, `0ED11B64810A`.
- **Operational Handling & Impact**:
  - Per Section 2B and Rule 6, these units are strictly classified as `NO_TELEMETRY` and excluded from scoring rather than fabricated as "calm" (zero anomaly risk).
  - In the 8 scored submission weeks (February 2, 2026 through March 23, 2026), eligible fleet count expands from 290 to 308 gateways. Exactly 1 gateway experienced recent silence in each of weeks 2026-02-09, 2026-03-02, and 2026-03-09; these were scored using the candidate silence penalty.
  - **Limitation**: The system cannot detect degradation on the 12 uninstrumented gateways. Dispatching technicians to these units requires external cellular provisioning audits rather than algorithmic telemetry scoring.

---

## 2. Retrospective Degradation Detection vs Leading Onset Forecasting

- **Limitation**: The scoring engine detects already-degraded gateways based on accumulated retrospective evidence (chronic reboot loops, elevated disconnect counts, multi-day cellular silence) over a 28-day baseline and 7-day recent window. It does **not** forecast degradation weeks before symptoms manifest.
- **Economic Consequence**: Because €600 accrues each week a gateway remains broken, detecting degradation only after persistence incurs 1–2 weeks of fault penalty before dispatch occurs.
- **Rationale**: Development period data (`field_visits.csv`) reliably supports retrospective audit of established failures, but lacks high-frequency precursor labeling required for statistical onset hazard estimation.

---

## 3. Operational Selection Bias in Historical Field Visits

- **Limitation**: Historical ground-truth evidence in `field_visits.csv` only records gateways that operational personnel already chose to inspect.
  - Of 628 historical visits through January 31, 2026, 382 visits (60.8%) were false alarms (`Kein Fehler gefunden`).
  - Only 218 visits involved confirmed physical component replacements (`Fehler behoben`).
  - Crucially, no record exists for gateways that failed silently and were never inspected by technicians.
- **Operational Consequence**: Any simulated cost-avoidance metric (€600/week fault penalty delta) measures precision-oriented performance on observed operational dispatches, with zero fleet-wide recall guarantees.

---

## 4. Structural Schema Validation vs Continuous Concept Drift

- **Limitation**: Structural schema correctness (column presence, strict dtypes, timestamp granularity, and fleet-wide absence rate) is monitored by `scripts/check_drift.py` (`make drift`) and enforced at the ingestion boundary (`app/data/schema.py` and `app/data/quality.py`). However, the system does not track continuous multivariate statistical concept drift (e.g. Population Stability Index or Wasserstein distance across all 57 raw telemetry signals).
- **Operational Consequence**: Subtle fleet-wide environmental degradation or gradual firmware distribution shifts that do not break schema constraints will not trigger a drift alert.

---

## 5. What Two Additional Weeks of Operational & Engineering Time Would Change

If granted two additional weeks of engineering and operational development time, the following four enhancements would be implemented:

1. **Lead-Time Pre-Failure Hazard Modeling**:
   - Fit a calibrated survival analysis model (e.g., Weibull accelerated failure time) on the 218 confirmed hardware repair episodes to predict failure probability 7–14 days *prior* to full functional collapse.
   - **Economic Benefit**: Recovers approximately 1 week of lead time per true fault, saving an estimated €600 per detected hardware failure by dispatching technicians before service disruption occurs.

2. **Carrier Cellular Provisioning Reconciliation for the 12 Blind-Spot Gateways**:
   - Cross-reference the 12 zero-telemetry gateways with mobile network operator (MNO) SIM registration logs and installation work orders.
   - **Operational Benefit**: Resolves whether these 12 units represent uncommissioned hardware, antenna orientation failures, or dead cellular modems, eliminating the 3.61% fleet blind spot.

3. **Multivariate Statistical Concept Drift Monitoring**:
   - Expand `scripts/check_drift.py` from structural schema monitoring to continuous Population Stability Index (PSI) and Kolmogorov-Smirnov statistics across key telemetry features (`snr_db`, `rssi_dbm`, `battery_voltage_v`).
   - **Reliability Benefit**: Flags network-wide cellular carrier degradation or firmware regressions before they manifest as catastrophic gateway outages.

4. **Technician Review Closure for Right-Censored Work Orders**:
   - Establish an active feedback loop with regional operations to verify terminal outcomes for the 14 late-January/February work orders currently classified as `UNKNOWN_RIGHT_CENSORED`.
   - **Evaluation Benefit**: Expands the verified evaluation cohort beyond the current 137 confirmed broken gateway-weeks, sharpening promotion gate statistical power.
