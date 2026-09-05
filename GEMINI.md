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
