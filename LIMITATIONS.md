# System Limitations & Scope Boundaries (LIMITATIONS.md)

Written in accordance with Section 14 and 18 of the v25 architecture freeze.

1. **Retrospective Detection vs Forward Prediction**:
   - The system detects already-degraded gateways from accumulated retrospective evidence rather than forecasting failure weeks in advance.
   - Economic impact: Because €600 accrues per week faulty, detection-after-persistence forgoes lead time that true onset forecasting would provide. This boundary is chosen because development labels reliably support retrospective audit, not leading indicators.

2. **Selection Bias in Historical Training Labels**:
   - `field_visits.csv` only contains records for gateways that operational personnel already suspected. Gateways that silently failed without investigation have no record in the historical visit log.
   - Consequently, any computed € cost savings metric is precision-oriented on this biased sample and carries no recall claims across the wider fleet.

3. **Telemetry Non-Coverage**:
   - Gateways with zero historical telemetry are excluded with code `NO_TELEMETRY` rather than scored with an invented heuristic. Operations must verify hardware installation dates and cellular provisioning for these units.

4. **Structural Drift vs Statistical Concept Drift**:
   - Version 1 enforces strict structural schema drift monitoring (missing columns, type conversions, timestamp grain anomalies). It does not perform full distribution monitoring (PSI / KS tests) across all 57 raw telemetry features.
