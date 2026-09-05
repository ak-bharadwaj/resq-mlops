# Project Operating Invariants & Governance Rules

## 1. Absolute Adherence to Architecture Plan (Zero Unapproved Deviations)
- The architecture plan defined in docs/ARCHITECTURE_v25_FREEZE.md (v25 CONTRACT-RESTORED STRENGTHENED FREEZE) is the binding, authoritative specification for this project.
- **NO DEVIATION** from the plan is permitted without the user's explicit prior approval. This includes:
  - Repository structure, script names, and Makefile contracts (make run, make rollback).
  - Model definitions: 0001 (baseline 3-sigma) and 0002 (deterministic weighted multi-signal scorer with frozen features). No stochastic learners or complex models.
  - Evaluation gate: 3 expanding rolling windows (Nov, Dec, Jan) + isolated grouped holdout (GROUP_HOLDOUT_IDS).
  - Promotion rule: >=10% cost differential on missed broken gateway weeks (€600/wk), zero window regression, and grouped holdout directional agreement.
  - Backlog economics: strictly 15 visits in predictions.csv, ranks 16+ deferred to acklog_report.json.
  - Replay determinism and atomic rollback via 
egistry/active.json.

## 2. Strict Phase Gating & Execution Pacing
- Do not begin writing application logic, training pipelines, or inference scripts when asked to plan, analyze, explore, or inspect.
- Never execute code without explicit user instruction.

## 3. Challenge Repository Privacy & Data Isolation
- The GitHub repository must remain **PRIVATE** until final submission.
- Challenge datasets (data/, *.parquet, *.xlsx, *.zip) must **never** be committed to Git.
- Maintain UTC cutoff (Monday 00:00 UTC) across all files, strictly preventing post-cutoff data leakage.

## 4. Physical Module Separation & AST-Enforced Boundaries
- Maintain strict three-way separation: Ingestion -> Detector Pipeline -> Evaluator.
- pp/model/predict.py and scripts/predict.py must NEVER import evaluation code, label construction, or ield_visits.csv.
- Verify module isolation via AST architecture tests (	ests/test_architecture.py).

## 5. Monotonic Time Authority & Zero Wall-Clock Leakage
- Zero system clock calls (datetime.now(), datetime.utcnow(), 	ime.time()) allowed in the prediction or feature paths.
- All temporal boundaries are driven strictly by the evaluation week parameter (week_start), verified by AST tests.

## 6. Strict Typed Contracts & Explicit Nullability Semantics
- Use Pydantic schemas with strict type annotations for all data contracts (manifest.json, schema.json, policy.json, acklog_report.json).
- Explicit nullability: Missing telemetry or insufficient history must return explicit None/N/A with clear reason codes (NO_TELEMETRY, INSUFFICIENT_HISTORY). Never fabricate 0.0 or average scores.
- predictions.csv must strictly enforce non-nullable loat scores serialized to 6 decimal places with no NaN/Inf.

## 7. Fail-Closed Error Paths & Audit-First Invariants
- Inference failures or corrupt records must route to explicit failure states and audit logs without halting execution or emitting invalid predictions.
- Fleet-wide telemetry absence trips the source-completeness guard into BLOCK_FEATURES, failing closed safely.

## 8. Programmatic Holdout Protection Guard
- Holdout gateways (GROUP_HOLDOUT_IDS) and post-cutoff files (ngineer_review_2026-02.xlsx) are protected by a programmatic guard (HoldoutProtection).
- Accessing holdouts in development mode or without explicit evaluation flags must raise HoldoutAccessError.

## 9. Strategy Pattern for Model Scorers & Clean Signal Masking
- Scorer implementations inherit from a polymorphic BaseScorer abstract class (Baseline3SigmaScorer for 0001, WeightedMultiSignalScorer for 0002).
- Ablations and candidate variants are managed via versioned configuration schemas and feature masks without mutating the underlying data pipeline.

## 10. Dual-Hash Cryptographic Provenance & Deterministic Serialization
- Maintain dual-hash integrity: rtifact_hash (model package) and 
eplay_hash (inputs + predictions.csv).
- Deterministic output serialization: Fixed column order, UTF-8 LF endings, non-increasing score order with canonical gateway ID tie-breaking.

## 11. Operations-Manager Register & Economic Translation
- All decision narratives in DECISIONS.md, prediction 
eason fields (<=300 chars), and presentation documentation must be written from the perspective of an Operations Manager allocating €380 technician visits and mitigating €600 weekly fault penalties.
- Never present proxy anomaly counts as observed € euro savings. Distinguish clearly between fixed visit allocations (€45,600 across 8 weeks) and the variable fault-penalty delta.

## 12. End-to-End Numerical Reconciliation
- Every number, test count, and metric quoted in documentation must match the exact outputs from automated test assertions and committed JSON artifacts (manifest.json, metrics.json, acklog_report.json). Zero placeholder figures in final deliverables.
