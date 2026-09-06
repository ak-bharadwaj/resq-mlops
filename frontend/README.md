# RESQ Operations Console (Frontend Task 1)

The **RESQ Operations Console** is a lightweight, zero-dependency, read-only operational dashboard for field dispatchers and operations managers. It provides full visibility into technician visit allocations, fleet telemetry health, model governance gates, and backlog risk without modifying underlying pipeline code or mutating registry states.

---

## 1. Quick Start

Run the console using the standard project entry point:

```bash
# On Linux / macOS / Git Bash
make frontend

# On Windows PowerShell / Command Prompt
.\make.cmd frontend

# Direct Python invocation (custom host/port)
python frontend/server.py --host 127.0.0.1 --port 8080
```

Then open your browser to:
**[http://127.0.0.1:8080](http://127.0.0.1:8080)**

---

## 2. Architecture & Design Principles

1. **Zero External Dependencies**: Built entirely with Python's standard library (`http.server`, `urllib`, `json`, `csv`, `pathlib`) and vanilla HTML5/CSS3/ES6 JavaScript. No `npm`, no Node.js, no bundlers, and no heavy web frameworks required.
2. **Read-Only Safety**: The frontend server only provides `GET` endpoints over existing serialized pipeline artifacts. It has zero capability to trigger training, change active models, or overwrite predictions.
3. **Truthful Nullability (Zero Fabrication)**: If an artifact is absent or unparseable (e.g. before `make run` or `make drift` has been executed), the dashboard explicitly renders an `UNAVAILABLE` status pill and descriptive reason code rather than fabricating default or 0.0 values.
4. **Operations-First Register**: All metrics are framed in operations-manager terms—allocating €380 technician visits within a fixed weekly budget (€5,700/wk for 15 visits) and preventing €600 weekly fault penalties.

---

## 3. Five Core Dashboard Sections

| Section | Component | Description & Consumed Artifact |
| :--- | :--- | :--- |
| **1. Header & KPI Strip** | `header`, `.kpi-strip` | Displays the active model version (`v0001`), evaluation week (`02 Feb 2026`), eligible fleet count (`290 eligible`), visit capacity (`15 / 15`), and telemetry health (`PASS`). Consumes `registry/active.json` & `monitoring/drift_reports/schema_check.json`. |
| **2. Dispatch Priority Table** | `.card-section`, `table` | Ranks 1–15 prioritized gateway visits for the selected Monday cutoff, with risk scores and operational decision audits (<=300 chars). Includes an 8-week dropdown selector. Consumes `predictions.csv`. |
| **3. Model Governance & Safety Gate** | `.split-grid` (Left Panel) | Compares Active (`v0001`) vs Candidate (`v0002`), displaying temporal improvement (`+15.49%`), unseen holdout fleet agreement (`18 vs 17 missed`), and gate verdict (`REJECTED`). Consumes `runs/promotion/promotion_decision_v0002.json`. |
| **4. Data Health & Completeness** | `.split-grid` (Right Panel) | Telemetry schema validation, source completeness guard (`SAFE`), fleet absence rate (`16.53%`), and firewall boundary enforcement. Consumes `monitoring/drift_reports/schema_check.json`. |
| **5. Backlog Fleet Risk** | `.backlog-banner` | Accounting for deferred gateways (ranks 16+) to protect operational budget: 275 deferred, 245 elevated risk, and 1,523 proxy hours. Consumes `backlog_report.json`. Includes interactive Backlog Intelligence modal and Gateway Deferral Inspector. |
| **6. Lifecycle & Rollback Strip** | `.lifecycle-card` | Visualizes the candidate evaluation cycle (`v0002 → REJECTED → v0001 RESTORED`) and atomic replay verification (`REPLAY EQUALITY: TRUE`). Consumes `registry/active.json` & `runs/prediction/run.json`. |

---

## 4. API Endpoints

- `GET /api/health`: Health ping (`{"status": "OK", "service": "RESQ Operations Console"}`).
- `GET /api/summary`: Consolidated read-only summary of `registry/active.json`, `monitoring/drift_reports/schema_check.json`, `runs/prediction/run.json`, `backlog_report.json`, and `runs/promotion/promotion_decision_v0002.json`.
- `GET /api/predictions[?week=YYYY-MM-DD]`: Filtered top-15 rows from `predictions.csv` with list of available evaluation weeks.
- `GET /api/backlog`: Direct read-only payload from `backlog_report.json`.
- `GET /api/backlog/lookup?gateway_id=<ID>[&week=YYYY-MM-DD]`: Operational gateway lookup verifying whether a gateway was dispatched (ranks 1–15) or deferred to the backlog (ranks 16+) due to weekly capacity rationing.

---

## 5. Verification

Automated unit tests covering API endpoints, artifact parsing, missing-file nullability, and make-target wiring are located in:
```bash
python -m pytest tests/unit/test_frontend_shell.py -v
```
