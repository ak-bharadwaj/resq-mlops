# 6–8 Minute Operational Walkthrough Recording Script & Cue-Sheet

Written for the Operations Manager, Dispatch Planners, and Technical Reviewers.
Conforming strictly to Challenge Brief Part 1 Section 7 and ARCHITECTURE_v25_FREEZE.md Section 17.

---

## Technical Overview & Presentation Structure

| Timestamp | Storyline Chapter | Visual Demonstration | Operations-Manager Dialogue Focus |
| :--- | :--- | :--- | :--- |
| **0:00 – 1:00** | Problem & Lifecycle Governance | Terminal & Architecture Overview | Defending €45,600 truck-roll budget against unvetted black-box changes |
| **1:00 – 2:15** | Reviewer Verification | Clean clone `make run` | 120 validated visits across 8 weeks (`validate_submission.py: OK`) |
| **2:15 – 3:15** | Immutable Model Packages | `models/v0001/` & `models/v0002/` | `model.joblib`, dual-hash integrity (`artifact_hash` & `replay_hash`) |
| **3:15 – 4:15** | Temporal Firewall & Schema Guard | Monday 00:00 UTC cutoff | Zero wall-clock leakage, fail-closed telemetry schema validation |
| **4:15 – 5:15** | Multi-Window Evidence Gate | `policy.json` & Gate Evaluation | Candidate `v0002` rejection (`REJECT_GROUPED_DISAGREEMENT`), `v0001` preserved |
| **5:15 – 6:15** | Backlog Economics | `predictions.csv` & `backlog_report.json` | 15 dispatches/week commitment, full visibility into deferred fleet risk |
| **6:15 – 7:15** | Atomic Rollback Proof | `scripts/rollback.py` execution | Pre-validation guard, atomic pointer swap, bit-for-bit replay equality |
| **7:15 – 8:00** | Empirical Fleet Boundaries | `LIMITATIONS.md` | Measured 12-gateway blind spot (3.61%) & two-week operational delta |

---

## Detailed Minute-by-Minute Cue-Sheet

### 0:00 – 1:00: The Problem in One Sentence & Track F Rationale
- **Screen Action**: Display repository root, showing `DECISIONS.md` and `GEMINI.md`.
- **Spoken Dialogue**:
  > *"Good morning. As an Operations Manager for LPDG, my responsibility every Monday morning is allocating our fixed technician fleet: exactly 15 truck rolls per week across 8 operational weeks, committing €45,600 in physical technician costs, while mitigating €600 weekly penalties for broken customer gateways.
  > 
  > We deliberately chose MLOps Architecture (Track F) over chasing novel machine learning algorithms. In field operations, deploying an uncalibrated complex model without cryptographic replay determinism, schema drift protection, or verified atomic rollback creates unacceptable service risks. Our core deliverable is total lifecycle governance: ensuring every technician dispatch is defensible, auditable, and fail-closed."*

### 1:00 – 2:15: Clean Clone Execution & Canonical Entry Point (`make run`)
- **Screen Action**: In an empty terminal, clone the repository into a clean temporary directory, invoke literal `make run`, and observe output.
- **Terminal Commands**:
  ```bash
  git clone https://github.com/ak-bharadwaj/resq-mlops.git clean_review
  cd clean_review
  make run
  ```
- **Spoken Dialogue**:
  > *"To prove reproducibility to reviewers, everything runs through a single canonical command: `make run`. 
  > 
  > Notice what happens: in a completely clean environment without cached state, `make run` ingests telemetry through our Monday 00:00 UTC temporal firewall, ranks eligible gateways, applies our 15-visit weekly cap, generates `predictions.csv`, and executes the official challenge validator `validate_submission.py`. 
  > 
  > The result is instant: exactly 120 dispatches across 8 weeks from February 2 to March 23, 2026, formatted to 6 decimals with operations-ready explanation strings under 300 characters. Result: `predictions.csv: OK`."*

### 2:15 – 3:15: Immutable Model Packages & Dual-Hash Cryptographic Provenance
- **Screen Action**: Inspect `models/v0001/` and `models/v0002/`, showing `model.joblib`, `manifest.json`, and `scorer_identity.txt`.
- **Terminal Commands**:
  ```bash
  ls -l models/v0001/ models/v0002/
  cat models/v0002/manifest.json
  ```
- **Spoken Dialogue**:
  > *"Let's look under the hood at model packaging. Per Section 6 of our frozen architecture, model packages are strictly immutable. 
  > 
  > Every package contains `model.joblib`, `model_config.json`, `feature_schema.json`, and `scorer_identity.txt`. These four behavior-defining files are cryptographically hashed into the `artifact_hash`. Notice that attempting to retrain into an existing package directory fails closed with `PackageAlreadyExistsError`.
  > 
  > Production runs on `v0001`, which packages our 3-sigma decision constants. Candidate `v0002` packages our deterministic multi-signal scorer, combining 3-sigma anomaly persistence with silence ratio."*

### 3:15 – 4:15: Inference Determinism, Cutoff Firewalls & Schema Drift Guards
- **Screen Action**: Inspect `app/data/loader.py` showing `load_telemetry_window` and `app/data/schema.py`.
- **Spoken Dialogue**:
  > *"In field operations, data leakage is lethal. Our temporal firewall enforces a strict Monday 00:00:00 UTC cutoff: any telemetry record stamped at or after midnight is rejected prior to feature calculation. There are zero wall-clock system calls anywhere in the prediction path.
  > 
  > Furthermore, before any model scores a single row, the incoming telemetry is validated against `TelemetrySchemaContract`. If columns are missing or types are corrupted, or if fleet absence exceeds 50%, the pipeline trips to `BLOCK_FEATURES`, failing closed safely without emitting fabricated predictions."*

### 4:15 – 5:15: Multi-Window Evidence Gate & Deterministic Rejection of `v0002`
- **Screen Action**: Display `policy.json` and show candidate evaluation results.
- **Terminal Commands**:
  ```bash
  cat policy.json
  cat registry/active.json
  ```
- **Spoken Dialogue**:
  > *"Now for the central operational decision: why did we NOT promote candidate `v0002`?
  > 
  > Our promotion gate is governed by a strict four-condition policy evaluated across three expanding temporal windows (November, December, January) plus an isolated grouped holdout of 59 gateways.
  > 
  > On historical development windows, `v0002` looked great: it reduced missed broken weeks from 71 to 60, an apparent €6,600 penalty savings. But on the 59 held-out gateways—hardware the model had never seen—the candidate regressed, missing 18 broken weeks compared to 17 in the active model.
  > 
  > Under our frozen gate rule, aggregate gains cannot overwrite holdout regression. The promotion gate issued an authoritative `REJECT_GROUPED_DISAGREEMENT`. Production remained safely locked on `v0001`. Rejection is a successful lifecycle outcome."*

### 5:15 – 6:15: Backlog Economics & Deferred Fleet Risk
- **Screen Action**: Open `backlog_report.json` and inspect deferred ranks 16+.
- **Terminal Commands**:
  ```bash
  cat backlog_report.json | head -n 30
  ```
- **Spoken Dialogue**:
  > *"Because our operational budget strictly caps technician visits at 15 per week, what happens to gateway rank 16 that is also showing signs of failure?
  > 
  > We never drop high-risk gateways into the dark. All candidates ranked 16 and above are captured in `backlog_report.json`. Operations planners can see the exact deferred risk exposure—for example, in week 1, 275 gateways are deferred, with 245 units exhibiting elevated risk scores totaling 1,523 proxy anomaly hours.
  > 
  > This gives dispatch managers the business justification to request emergency overtime or reallocate regional contractor capacity."*

### 6:15 – 7:15: Atomic Rollback Demonstration with Bit-for-Bit Replay Proof (`v_promotable` → `v0001`)
- **Screen Action**: Run `python scripts/rollback.py` in the terminal.
- **Terminal Commands**:
  ```bash
  python scripts/rollback.py
  ```
- **Spoken Dialogue**:
  > *"Because candidate `v0002` was legitimately rejected by our promotion gate, production remained safely anchored on `v0001`. To demonstrate our atomic rollback machinery without violating governance rules or falsely deploying an unvetted candidate, the architecture includes a committed deterministic fixture: `v_promotable`.
  > 
  > When we invoke `scripts/rollback.py`, it executes our canonical rollback rehearsal: rolling back from active `v_promotable` to restore baseline `v0001`.
  > 
  > Notice the five-point safety lifecycle:
  > 1. Target Validation: It validates target package `v0001` before touching the registry, verifying manifest integrity, config schemas, and cryptographic `artifact_hash`.
  > 2. Pre-Rollback Hash: It captures the current active replay hash.
  > 3. Atomic Switch: It swaps `registry/active.json` via an atomic filesystem call in less than 1 millisecond.
  > 4. Replay Proof: It runs post-switch prediction and proves bit-for-bit deterministic replay equality against the expected baseline prediction hash.
  > 5. Active Restored: Registry state confirms `v0001` is restored. Replay equality: PASS."*

### 7:15 – 8:00: Empirical Fleet Boundaries & Two-Week Operational Delta
- **Screen Action**: Display `LIMITATIONS.md` Sections 1 and 5.
- **Spoken Dialogue**:
  > *"We close with operational honesty. In `LIMITATIONS.md`, we disclose that of 332 registered gateways, exactly 12 units—3.61% of our fleet—have zero historical telemetry records. We classify them as `NO_TELEMETRY` rather than inventing calm scores.
  > 
  > If given two additional operational weeks, our priorities are clear:
  > 1. Fit pre-failure survival hazard curves to recover 7 to 14 days of lead time before total outage occurs.
  > 2. Audit carrier cellular SIM provisioning to bring the 12 blind-spot units online.
  > 3. Implement automated multivariate concept drift monitoring in `scripts/check_drift.py`.
  > 4. Close loop reviews with regional technicians on the 14 right-censored work orders.
  > 
  > Thank you. The repository is clean, deterministic, and fully auditable."*

---
