LPDG INNOVATION HUB • SELECTION CHALLENGE 2026

MLOps Architecture — v25 CONTRACT-RESTORED STRENGTHENED FREEZE

Same freeze thesis as v20–v23. v24 strengthened the evidence layer; v25 restores every implementation contract that must remain binding while preserving those evidence upgrades. This pass is contract restoration and precision, not a model or infrastructure redesign.

Changelog — v24, strengthening pass

Framing: v20→v23 were bug fixes. These are upgrades to an already-sound design, made because scope was previously capped by a schedule that no longer applies to these specific choices.

STRENGTHEN — evidence depth  Section 8 used one clean temporal holdout, deferred to a single window specifically to protect the build schedule. With that constraint lifted, replaced with three rolling train/holdout windows (Nov, Dec, Jan holdouts against progressively longer training periods) — the promotion gate now requires the candidate to beat the active model's aggregate cost across all three, not one. This is a materially stronger claim ("consistently better across periods" vs "better in the one period we happened to check") and it costs nothing at the live session, since the backtest runs during train.py, never during predict.py or the rollback demo.

STRENGTHEN — a second, harder validation axis  The existing evaluation only ever held out time (later weeks). Added a second, independent holdout: a fixed subset of gateways excluded entirely from feature/weight selection, then scored only on that unseen subset. This directly answers the skeptic's question the FAQ names for the ML track (6.12: "grouped and forward, both not either") — applying the same discipline to MLOps's evidence gate is a genuine judgement-score upgrade, not a track-crossing error, since nothing stops MLOps from being evaluated as rigorously as ML is asked to be.

STRENGTHEN — a real second rejection, not only the fixture  10A already stages a committed, deterministic fixture that the frozen gate correctly rejects, to guarantee the rejection demo works live regardless of what the real candidate does. Added an optional second data point: attempt one genuinely different, honestly-motivated v0002 variant (e.g. a slightly different feature weighting reached by a defensible but ultimately weaker rationale) and let the real frozen gate reject it on its own merits, evidence attached. Two independent proofs that the gate discriminates — one guaranteed, one earned — is stronger than either alone. This is explicitly optional (Section 19) and never replaces the guaranteed fixture.

ADD — restored and updated recording storyline  Earlier drafts of this architecture included a timestamped 6–8 minute recording structure; it was dropped when the document was rebuilt against the FAQ. Restored as Section 17, updated to match every mechanism actually in v24 (rejection demo, rolling-window evidence, grouped holdout, rollback proof). The recording is a required, graded deliverable (15% explanation) — a rehearsed structure is not optional polish.

ADD — ops-manager translation layer  The FAQ repeatedly specifies that DECISIONS.md, the reason field, and the recording must be written for an operations manager, not for the reviewer. v20–v23 got the mechanics right but stayed engineer-facing throughout. Added Section 18: a short, concrete translation table mapping every technical field this system produces (evidence_quality, missed_broken_gateway_weeks, exposure_method, etc.) to the plain-English sentence an ops manager should actually hear. This is a direct, low-effort lever on the 15% explanation criterion.

ADD — optional judgement-strengthening enhancements  Section 19, new: the second rejection case above, and a tightly-scoped value-distribution check limited to only the 2–3 features v0002 actually uses (not full PSI/KS across all 57 telemetry columns). Both are explicitly optional, explicitly not required for the Part 1 gate or the F track's own bullet points, and explicitly bounded so they cannot become the kind of "clever part" the FAQ warns will hurt you live.

ADD — freeze real numbers before hand-in  Every illustrative JSON example and "~90 cases" reference in this document is a placeholder for a real number the data audit will produce. Added an explicit Definition-of-Done line: before hand-in, every illustrative value in manifest.json, metrics.json, and backlog_report.json examples is replaced with the actual computed value from the real run — a frozen document with placeholder numbers throughout is not evidence of anything.

NOT changing, and why (read this before adding more)  Three things this pass deliberately does not touch, because more time does not make them better ideas: (1) v0002 stays a small, fixed-weight scorer — the F track is graded against its own six bullets, none of which reward model sophistication, and the ML track explicitly is the one graded on beating baseline; making v0002 bigger dilutes focus without earning marks. (2) Drift monitoring stays schema/shape-based as the required mechanism — the bullet point says "notice if it changed shape," and Section 19's optional distribution check is bounded specifically so it doesn't become an unscoped statistics project. (3) No Docker/CI/K8s registry buildout beyond what's already specified — FAQ 6.15 states these are scored under DevOps, not MLOps; building them here spends effort where it isn't rewarded. "Prefer fewer clever parts" (FAQ 7.2) is a live-session survival rule, not a symptom of insufficient time — it stays true regardless of how much time is available.

The v22→v23 self-audit changelog is retained below, unchanged, for the full history.

v22 → v23 changelog (retained)

Five findings, all from re-reading v22 end to end rather than against any new external source. Each is listed once here; the corresponding inline fix is placed at the exact section it touches, marked v23.

A hedged figure ("~90 usable cases") was correctly softened in one place (Section 8) but left asserted as settled fact in two others (the retained v20→v21 changelog, and a live Operations-Manager Summary note) — fixed in both.

The train.py pseudocode still said "-> fit ->" after the ownership table's "Candidate fitting" was renamed to "Candidate construction/materialization" — the two were inconsistent with each other.

Section 10's rollback demo used the command name make demo-rollback, while Section 5A's canonical command list only defines make rollback — unified to one name.

The new Section 2B source-completeness guard (added in v22 to stop a fleet-wide outage from reading as hundreds of gateway failures) had no test verifying it actually fires — added as a new P0 test.

Section 5A calls make run a "P0 delivery contract," but the test proving it actually works on a clean clone (clean_environment_smoke) sat in P1 — promoted to P0 to match the severity the document itself already claims.

The v22 changelog is retained below, unchanged, for the full history.

v21 → v22 changelog (retained)

This pass is contract-tightening, not redesign — consistent with the reviewer's own conclusion that after these fixes, architecture work should stop and implementation should start.

FIX (must-fix — leakage)  The four-hour feature-freeze instruction said to inspect "telemetry, meter-read success, field visits and engineer review" without restricting that inspection to the development period. Section 2C already restricted holdout-period evidence from defining label_spec_v1, but that restriction did not extend to general feature/EDA discovery — a distinct risk: even if the 2026-02-15 engineer review never enters a feature vector, letting it inform which features or weights get chosen during EDA contaminates the holdout it's later evaluated against. Fixed: the four-hour window is now explicitly scoped to development-period evidence only (through 2026-01-31); holdout-period reviews/outcomes may not inform feature discovery, feature selection, parameter selection or model-design decisions at all, and may only be consumed later, by the already-frozen label specification, strictly where the prediction cutoff permits.

FIX (must-fix — new failure mode)  recent_silence_ratio (added in v21) correctly stops total silence from reading as "calm," but on its own it creates a new failure mode: a fleet-wide ingestion outage (e.g. a 48-hour pipeline failure hitting many gateways at once) would be read as hundreds of simultaneous gateway failures, and the existing schema monitor would not catch it — columns and dtypes stay valid, the rows are just absent. Fixed: added a source-completeness guard ahead of feature scoring — fleet-wide expected-vs-received telemetry coverage is checked per hour/day; if the fleet-wide absence rate exceeds a frozen threshold, the run enters BLOCK_FEATURES rather than silently scoring every affected gateway as high-risk. A small guard, not a new monitoring subsystem.

FIX (must-fix — logical contradiction)  v21 said rank must be "strictly descending" while also specifying a deterministic tie-break by gateway_id — those two statements conflict, since a tie-break only has meaning when scores are allowed to be equal. Corrected to: rank corresponds to non-increasing model score; equal scores are ordered deterministically by canonical gateway_id.

FIX (must-fix — delivery contract)  The FAQ states a reviewer clones the repository, drops data into data/, runs one command, and validates the output — nothing else is assumed, and a repository that doesn't run on their machine isn't scored. v21 named train.py / predict.py / make_submission.py as separate scripts but never defined a single reviewer-facing entry point; a Makefile being present in the repo tree is not the same as a defined contract. Added Section 5A: make run (or equivalent) is now the canonical, contractually-required single command — it validates the environment, runs the active model through prediction only (never training), writes predictions.csv, and invokes the supplied validate_submission.py. make train / make predict / make promote / make rollback remain available underneath for development and the live demo, but make run is the only command a reviewer is required to know.

FIX (worth-fixing — premature evidence)  v21 stated the development sample has "roughly 90 usable cases" as justification for the frozen 10% margin. That figure came from exploratory audit work done ahead of this document, not from the frozen label-audit step (2C/2D) itself — stating it as settled fact inside an architecture freeze risks exactly the kind of invented-number problem this document elsewhere warns against. Corrected: the document now states 10% is a precommitted materiality threshold sized to the expected development evidence volume, notes that preliminary exploration located approximately 90 candidate cases, and makes explicit that the frozen label-audit step re-establishes and reports the exact count before COST_BACKTEST is used — the number is not asserted as final here.

FIX (worth-fixing — precision)  recent_silence_ratio's denominator ("relative to the gateway's own reporting history") was ambiguous — installation-age-based expectation, median historical hours, and contractual telemetry frequency would each produce a different value. Defined precisely: missing expected hourly observations in the trailing 7-day window, divided by expected observations in that window per the frozen hourly telemetry grain contract (schema.json) — not a gateway-specific historical average. A separate feature may capture gateway-specific reporting behavior later if justified; the two must not be conflated.

FIX (worth-fixing)  unseen_month_prediction (P0) tested that an arbitrary unseen month runs without crashing, but didn't name the two specific robustness cases the FAQ calls out (6.11): a gateway ID never seen before, and a previously-reporting gateway that has gone quiet. Both are now named as required fixture cases within that test — cheap to add since the underlying logic (eligibility filtering, recent_silence_ratio) already exists.

FIX (worth-fixing — honesty of wording)  The train.py ownership table listed "Candidate fitting" for v0002, but v0002 is a small, fixed-weight scorer that may be manually selected or deterministically materialized from training data rather than fit by a learning algorithm. Changed to "Candidate construction/materialization" so the documentation doesn't imply a fitting procedure that may not exist — unless the frozen weights are genuinely estimated from training data, in which case "fitting" is accurate and should be restored.

FIX (worth-fixing — omission)  Section 14's artifact map names schema.json as the authoritative model-specific telemetry contract, but the models/v0002/ package tree in Section 6 never listed it — an implementer would have to infer an artifact the document's own later section depends on. Added schema.json to the artifact tree.

ADD (small, free improvements)  Three additions with no dependency on the fixes above: (1) COST_BACKTEST is now explicitly named an internal promotion proxy, not an estimate of LPDG's own held-out score — a candidate showing a 10% internal improvement should not be read as implying the official score moves by a comparable amount, since the two are computed against non-comparable ground truths. (2) The P0 test train_then_predict_end_to_end is now explicitly required to assert the specific invariants named under the adjacent P1 entries (feature parity, common-population identity, right-censoring exclusion) inline, not merely confirm the pipeline runs — P1 priority means these don't need separate standalone tests, not that the invariants are optional. (3) A one-line reinforcement in the Operations-Manager Summary: the goal for v0002 is an internally defensible candidate with strong lifecycle and an honest proxy, not a guess at what LPDG's inaccessible hidden scorer will reward.

v23  The "roughly 90 usable cases" figure appearing in the retained v20→v21 changelog above (and echoed once more below, in the Operations-Manager Summary) is historical: it records what v21 asserted at the time. As of v22, that number is treated as preliminary, not settled — see the Section 8 hedge. Wherever this document still states it in body text rather than changelog history, it is now phrased accordingly.

The v20 → v21 changelog (timezone fix, cost-formula fix, and the FAQ-driven additions) is retained below, unchanged, for the full history.

v20 → v21 changelog (retained)

Every entry below is triggered by a specific FAQ statement, not a stylistic preference. Two are corrections to v20 (one is a real bug); the rest are additions that make an already-implicit point explicit and testable.

FIX (bug)  Section 2E said the feature cutoff is "Monday 00:00 IST." FAQ 3.7 states plainly that IST governs only the challenge schedule (deadlines, check-in, hand-in) and "has nothing to do with the data," and that mixing timezones across files is exactly the kind of bug reviewers look for. Corrected to Monday 00:00 UTC, matching baseline_3sigma.py, which the FAQ names as a defensible, citable choice. Applied consistently to every file's cutoff, not just telemetry.

FIX (cost formula)  Sections 8/9 defined promotion cost as wasted_visits × €380 + missed_broken_gateway_weeks × €600, with "wasted visit" meaning only a visit that found nothing. FAQ 5.2 states €380 is charged once per visit dispatched, regardless of outcome — 15 × 8 × €380 = €45,600 for every valid submission, since 15 rows/week are mandatory (FAQ 3.4). The €380 term is therefore a constant across any two valid candidates, not a variable driven by which visits were "wasted." The promotion/rejection comparison now differences only on missed_broken_gateway_weeks × €600 — the only term that can actually move between two top-15 rankings. Wasted-visit count is retained as an operator-facing informational figure, but is explicitly barred from the promotion delta.

ADD  FAQ 4.4 states field_visits.csv gateways are "the ones somebody already suspected... not a random sample of the fleet," with no row for a gateway that was quietly broken and never visited. This is now a named, explicit field (evaluation_scope) rather than an implication inside evidence_quality: any COST_BACKTEST number is precision-oriented on a selection-biased sample, and carries no recall claim across the fleet.

ADD  FAQ 4.1 confirms LPDG's held-out ground truth is separate from field_visits.csv and from Kategorie. Added an explicit, one-time statement (DECISIONS.md + OPERATIONS-MANAGER SUMMARY) that the internal COST_BACKTEST figure is not expected to match LPDG's own published score — a mismatch is expected, not a bug, and this is stated before it can be read as a defect live.

ADD  FAQ 4.2 explicitly asks candidates to state whether they are detecting an already-broken gateway or predicting a future break, and what the other framing would have cost. v20 implicitly chose detection (label is a retrospective weekly state) without saying so. Now stated explicitly, with the cost consequence named: since €600 accrues per week faulty, a pure detection framing forgoes lead-time a genuine early-warning framing would buy, and that gap is recorded as a named limitation for "what another two weeks would fix."

ADD  FAQ 4.6 flags that missing telemetry "has more than one cause" and that the distinction decides whether a gateway should be visited or left alone. v20's NO_TELEMETRY exclusion (2B) treated all missing-telemetry gateways identically. Section 2B now separates zero-telemetry-ever (institutional non-coverage — correctly excluded, e.g. not yet installed) from a previously-reporting gateway that has gone recently and completely silent — the latter is now a named risk feature, not an exclusion, because a 3-sigma-style flagged-hour count structurally under-counts a fully silent window: there is no data in the recent window to compare against baseline, so total silence would otherwise score as calm rather than as the highest-risk case it likely is.

ADD  FAQ 3.4 confirms there is no way to express "only 9 gateways truly need a visit" in predictions.csv — exactly 15 rows are mandatory regardless of model confidence, and padding never changes visit cost, only opportunity cost. Section 9 now states explicitly that predict.py always fills the full top 15 by score, independent of any internal confidence threshold; a below-threshold pick is written to DECISIONS.md narrative, never omitted from the file.

ADD  Section 8's frozen 10% promotion margin previously justified only its type (materiality heuristic, not statistical significance). Added the one-sentence justification for the number itself, written before results exist: 10% is set to avoid promoting on evaluation noise given a label-bearing development sample of roughly 90 usable cases, while remaining achievable for a deliberately small, fixed-weight feature set.

ADD (minor)  FAQ 3.3: rank order is not read by the cost script but is the first thing a human reviewer sees. Added an explicit acceptance rule that within each week, rank must correspond to descending model score, so the list reads sensibly top-to-bottom for an operations manager.

ADD (minor)  FAQ 2.2/2.3: the submission must run fully offline with no runtime network calls, API keys, accounts, or model downloads. Added as an explicit, testable design constraint (not previously stated) — relevant because v0002 must not silently depend on any package that phones home at import or runtime.

ADD (minor)  FAQ 1.2: data/ must never be committed, and repo history must be checked before going public. Added to the delivery checklist explicitly (previously only implied by "keep data out of the public repository").

Everything below this line is v20's content, unchanged except where an inline note marks a v21 edit.

Core thesis

Build the smallest system that can prove one complete loop: label audit → deterministic candidate → evidence gate → promote/reject → structural drift response → rollback → replay proof. If retrospective labels are weak, keep the lifecycle and downgrade the evidence mode instead of fabricating economic certainty.

Operations-manager summary — what this system knows / does not know

This system does not know the network's true failure rate. It ranks gateways using observable telemetry and other supplied evidence, and records whether the evidence supports an economic evaluation or only a proxy. Evidence quality is carried with every prediction/evaluation artifact. This is a reproducible decision aid, not a calibrated failure probability or a claim of complete fleet visibility.

v21  evaluation_scope="precision-oriented, selection-biased sample; not a fleet-wide recall estimate" is now a named field alongside evidence_quality (see FAQ 4.4 above).

v21  Added: the internal COST_BACKTEST figure is expected to differ from LPDG's own held-out score, because that ground truth is independently held and not derived from field_visits.csv or Kategorie (see FAQ 4.1 above). This is stated once here so it is not read as a defect in the live session.

v21  Added: this system frames its task as detecting an already-degraded gateway from retrospective evidence, not predicting a future break. The alternative (a leading-indicator model trained to anticipate onset before persistent evidence accumulates) was considered and rejected for v1 because the available development sample only supports confident retrospective labeling, not onset forecasting (see Section 8 for the evidence-count caveat); the cost of that choice is named explicitly — since €600 accrues per week faulty, detection-after-persistence is worth strictly less than genuine early warning, and closing that gap is the first item under "what another two weeks would buy."

2. Load-bearing prerequisite: define and sanity-check the failure proxy

Before any model comparison, establish whether the supplied files contain enough evidence to construct a defensible weekly gateway-level proxy. This is not "truth"; it is the operational definition used for evaluation. A field-visit event alone is not treated as ground truth.

GO / NO-GO  If label quality is insufficient for COST_BACKTEST, switch to HEURISTIC mode rather than blocking the lifecycle. Outputs must expose evidence_quality=weak and must never present proxy values as observed € savings.

2A. Ingestion correctness: encoding, ID normalization and gateway eligibility

gateway_master.csv is read as cp1252; field_visits.csv encoding is explicitly verified during the audit. Master/visit/review files use colon-separated gateway IDs (for example, 06:39:EA:56:02:C1), while telemetry and meter_read_success use the same IDs without separators (0639EA5602C1). Canonicalize once at ingestion to 12 uppercase hexadecimal characters with separators removed; all downstream joins use only that form. Eligibility is evaluated per scored week: installed_on <= Monday AND (decommissioned_on is null OR decommissioned_on > Monday). The filter is mandatory before feature construction and ranking; it is not inferred from telemetry presence.

2B. Exposure denominator, telemetry coverage audit, and the two kinds of missing telemetry

Inspect meters_expected per gateway over time: distinct-value count, first/last values, min/max and change points. If it changes, use the time-aligned value; if semantics cannot be defended, omit it.

v21 — replaces prior blanket NO_TELEMETRY rule  FAQ 4.6: missing telemetry has more than one cause, and the distinction decides whether to visit or leave alone. Split into two cases. (1) Zero telemetry across the gateway's complete eligible history — institutional non-coverage (e.g. installed after the local data window effectively begins, or a genuine coverage gap). These gateways are excluded from ranking with exclusion_reason="NO_TELEMETRY", counted in run evidence, and never assigned an invented score. (2) A gateway with an established prior reporting history that goes completely silent in its recent trailing window. This is NOT excluded — it is surfaced as an explicit feature, recent_silence_ratio. This distinction matters mechanically: a 3-sigma-style flagged-hour count is computed only over rows that exist, so a fully silent window produces zero flagged hours by construction — the anomaly method would score total backhaul silence as calm, which is very likely the opposite of the truth. Do not invent a failure score for the zero-coverage case; do not silently drop the recently-silent case.

v22 — precise definition  recent_silence_ratio = missing expected hourly telemetry observations in the trailing 7-day window, divided by expected observations in that window per the frozen hourly telemetry grain contract (schema.json) — not by a gateway-specific historical reporting average (installation age, median historical hours, and contractual frequency would each give a different, ambiguous denominator). A separate feature may capture gateway-specific historical reporting behavior later if justified; the two must not be conflated.

v22 — new failure mode this feature creates, and its guard  A per-gateway silence feature alone has a blind spot: a fleet-wide ingestion outage (e.g. a 48-hour pipeline failure affecting many gateways at once) would be read as hundreds of simultaneous gateway failures, and the structural schema monitor would not catch it — columns and dtypes stay valid, the rows are simply absent. Added a source-completeness guard ahead of feature scoring: compute fleet-wide expected-vs-received telemetry coverage by hour/day; if the fleet-wide absence rate exceeds a frozen threshold, the run enters BLOCK_FEATURES rather than silently scoring every affected gateway as high-risk. This is a small guard, not a new monitoring subsystem — P1 unless the data audit reveals a real systemic gap of this kind, in which case it is promoted to P0.

2C. Label sanity tie-break and fallback

Require N=3 clearly interpretable historical gateway-week cases supporting the chosen proxy, plus a small fixture test that proves the label function marks an unambiguous positive case as intended. If fewer than 3 clear cases exist, or outcome interpretation remains materially ambiguous, freeze HEURISTIC mode. Do not stall the build trying to manufacture ground truth.

Label-audit evidence used to define label_spec_v1 is selected only from the pre-holdout development period, ending 2026-01-31. Holdout-period outcomes/reviews may later instantiate labels under that already-frozen specification, but cannot influence label definition, feature selection or parameter selection. N=3 is a minimum interpretability sanity gate, not statistical validation; if fewer than three qualifying development-period cases exist, default to HEURISTIC.

2D. Frozen label contract

Implement one pure deterministic function label_gateway_week(gateway_id, week_start, feature_cutoff, label_observation_window, label_spec_v1) → {BROKEN, NOT_BROKEN, UNKNOWN_RIGHT_CENSORED}. FEATURE_CUTOFF governs features only. LABEL_OBSERVATION_WINDOW may extend beyond the historical prediction week so later recovery evidence can establish the retrospective outcome. If recovery is not observable before the observation window ends, classify the terminal interval as UNKNOWN_RIGHT_CENSORED; do not treat end-of-data as recovery, and exclude that interval from economic exposure calculations that require a recovery endpoint. Any gateway-week labelled UNKNOWN_RIGHT_CENSORED, or otherwise lacking a fully observed terminal outcome, is excluded from both active and candidate economic evaluation; the evaluator reports total_gateway_weeks, evaluated_gateway_weeks, right_censored_gateway_weeks and unknown_gateway_weeks.

v21 — episode semantics made explicit  FAQ 5.2/5.4: €600 accrues once per gateway per week left faulty, and recurs — a fault left four weeks costs €2,400. A visit stops the accrual for that fault episode in the week it lands, inclusive; the same gateway can open a new, separate fault episode later, which must be evaluated independently rather than folded into the first. label_gateway_week and the evaluator now track BROKEN state as episodes (open → visited-or-recovered → closed → may reopen), not as an independent per-week classification. A gateway is not treated as permanently faulty after its first BROKEN week merely because no later NOT_BROKEN evidence has yet appeared for it.

2E. Prediction cutoff and retrospective label window

FEATURE_CUTOFF is the frozen Monday 00:00 UTC boundary for the prediction week; no feature may use information at or after that cutoff. 

v21 — FIX  Corrected from "Monday 00:00 IST" (v20) to Monday 00:00 UTC, matching baseline_3sigma.py. FAQ 3.7: IST governs only the challenge schedule and has nothing to do with the data; a submission that mixes timezones across files is explicitly named as the kind of bug reviewers look for. UTC is applied as the single boundary rule across every file — telemetry, field_visits, meter_read_success, engineer_review — with no exceptions.

LABEL_OBSERVATION_WINDOW is a separate retrospective window and may use later outcome/recovery evidence needed to label the historical gateway-week. Critical invariant: future evidence may be used to construct retrospective labels, but never to construct prediction features. The 15 Feb 2026 engineer review is therefore prohibited from features for earlier cutoffs, but may be used as retrospective outcome evidence only where label_spec_v1 permits it.

A case qualifies as clearly interpretable only when the auditor can identify a specific gateway-week, a specific unambiguous outcome/review statement, and temporally coherent operational evidence sufficient to defend that label. The N=3 qualifying cases must come from the pre-holdout development period and are selected before any holdout performance is inspected. N=3 is an interpretability sanity gate, not statistical validation.

3. Candidate model: real enough to make the gate meaningful, small enough to finish

Version

Role

Frozen definition

v0001

Control / baseline

Package the supplied baseline_3sigma.py without changing its decision logic.

v0002

Candidate

Deterministic weighted multi-signal scorer with a deliberately small frozen feature set. V1 permits baseline anomaly statistics plus only one or two additional signals directly defensible from the supplied data; no stochastic learner, ensemble, hyperparameter search or auto-tuning.

v0003+

Optional

Only after the core lifecycle is passing end-to-end. Never let model experimentation consume the rollback/evidence budget.

Four-hour feature freeze: spend exactly four hours inspecting the Data Dictionary and development-period evidence only — telemetry, meter-read success, field visits and engineer-review records dated on or before 2026-01-31. Record supported candidate features and rationale. At the deadline, freeze features. Reopen only if a discovered data defect makes a selected feature invalid.

v22  Holdout-period evidence, including the 2026-02-15 engineer review, must not be inspected, summarized, or allowed to motivate a feature, weight, or label-design choice during this four-hour window — development leakage (a design choice shaped by holdout evidence) is a distinct risk from runtime leakage (a feature computed from post-cutoff data) and v21 only guarded the second. Holdout-period evidence may only be consumed later, by the already-frozen label specification, strictly where the prediction cutoff in Section 2E permits.

Illustrative feature families — only if supported by actual columns:

anomaly magnitude + persistence (existing baseline signal)

recent meter-read failure / depression relative to the gateway's own baseline

degradation trend

recent_silence_ratio — v21 addition, see 2B

gateway exposure / meter count

supportable historical fault signal

→ fixed weighted risk score → rank → enforce top-15 policy

Score semantics — frozen  score is a deterministic risk-priority index used only for ranking; it is not a calibrated probability and must be documented as such. Higher score means higher visit priority. Scores are serialized to six decimal places; NaN/Inf is invalid. Ordering is non-increasing by score, then canonical gateway_id ascending for ties.

v21  recent_silence_ratio added to the illustrative family list per the 2B correction above. This is the one place a genuinely new feature enters the design; every other addition in this revision is a contract, framing, or evaluator correction.

4. First-version architecture

RAW DATA (./data)

  |

  +-- schema + quality checks ----+

  |                               |

  +-- deterministic feature builder+

                  |

        +---------+----------+

        |                    |

     TRAIN                PREDICT

        |                    |

    train.py             predict.py

        |                    |

  candidate v00n       active version

        |                    |

  evaluate evidence   validate contract

        |                    |

  promote / reject   score + rank + top-15

        |                    |

        +--- filesystem registry ---+

                     |

                 rollback

Repository layout:

resq-mlops/

|-- app/

|   |-- data/        loader.py, schema.py, quality.py

|   |-- features/    build.py, definitions.py

|   |-- model/       train.py, predict.py, evaluate.py

|   |-- registry/    registry.py, promotion.py, rollback.py

|   `-- monitoring/  schema_monitor.py, reports.py

|-- scripts/         train.py, predict.py, make_submission.py, promote.py, rollback.py, check_drift.py

|-- models/          v0001/, v0002/, ...

|-- registry/        active.json, history.jsonl|-- policy.json       frozen retraining + evaluation governance

|-- monitoring/      schema_baseline.json, drift_reports/

|-- runs/            training/, prediction/

|-- tests/           unit/, integration/, regression/

|-- Dockerfile       docker-compose.yml / Makefile / requirements.lock

`-- DECISIONS.md     MLOPS.md     AI-USAGE.md     LIMITATIONS.md     README.md

v21 — new constraint, not a structural change  FAQ 2.2/2.3: the submission must run fully offline at runtime — no network calls, no API keys, no accounts, no model or dependency download at run time. A pre-trained artifact fetched once during development and committed as a versioned file is fine; anything fetched at start-up is not. Added as an explicit, testable constraint: no package used by v0002 or the pipeline may perform network I/O during train.py, predict.py, or make_submission.py.

5. Hard separation: train.py vs predict.py

train.py owns

predict.py owns

Historical data loading + label/proxy construction

Loading the active immutable artifact

Feature construction for training

Validating the artifact-specific input contract

Candidate construction/materialization

Deterministic feature construction using the declared feature version

Evidence/cost evaluation

Scoring, ranking and top-15 enforcement

Creating immutable candidate package

Writing predictions.csv + backlog_report.json + replay evidence

Writing training evidence

Never training, promoting or rolling back

v23  Pseudocode's TRAIN workflow previously said "-> fit ->", left over from before the ownership table's "Candidate fitting" was renamed to "Candidate construction/materialization" — corrected here to match, since v0002 may not involve a fitting procedure at all.

TRAIN

python scripts/train.py --data ./data --candidate v0002

  validate -> label/proxy -> frozen features -> construct/materialize -> evaluate -> package -> evidence

PREDICT

python scripts/predict.py --data ./data --week 2026-03-23

SUBMISSION ASSEMBLY

python scripts/make_submission.py --data ./data --output predictions.csv

  Calls predict.py for the eight required Mondays, concatenates the same

  single-pass scoring outputs, writes exactly 120 rows, and invokes the

  supplied validate_submission.py.

  resolve active -> validate contract -> validate telemetry -> features ->

  score -> rank non-increasing (ties by gateway_id) -> top-15 -> outputs

v21  Rank-ordering made explicit in the predict path per FAQ 3.3 — see Section 9 for the full rationale.

v22  Wording corrected from "rank descending" to "non-increasing, ties broken by canonical gateway_id" — see the Section 9 fix below; "strictly descending" is mathematically incompatible with a deterministic tie-break, since a tie-break only matters when two scores are equal.

HARD RULE  train.py never changes production state. predict.py never trains, promotes, or rolls back.

5A. Single reviewer-facing entry point (P0 delivery contract)

The FAQ states the reviewer clones the repository, drops data into data/, runs one command, and validates the output — and that a repository which does not run on their machine is not scored. train.py, predict.py and make_submission.py are development-facing; none of them alone is the contractually required single command.

make run

   |

   +-- validate environment (data/ present, dependencies locked, offline)

   +-- resolve active model version (predict only — never trains)

   +-- run make_submission.py for all 8 required weeks

   +-- produce predictions.csv

   `-- invoke the supplied validate_submission.py, print PASS/FAIL

Development / demo only (not required of a reviewer):

make train      make predict      make promote      make rollback

v22 — new subsection  Added because v21 defined the pipeline scripts but never named a single canonical entry point, and a Makefile merely existing in the repository tree is not the same as a defined contract. make run (or an equivalent single command) is now the one thing a reviewer needs to know; everything else remains available for development and for the live demo, where individual train/predict/promote/rollback commands are exactly what gets exercised.

6. Immutable model package and determinism contract

v0001 artifact semantics. The supplied baseline_3sigma.py has no fitted parameters to learn; V1 therefore packages its frozen decision constants and implementation contract as the versioned artifact state: BASELINE_DAYS=28, RECENT_DAYS=7, SIGMA=3.0, plus the exact code/contract identity. Training v0001 means creating and validating this immutable package, not pretending a fitted model was produced.

models/v0002/

|-- model.joblib

|-- model_config.json

|-- feature_schema.json

|-- schema.json

|-- manifest.json

|-- metrics.json

`-- scorer_identity.txt

{

  "model_version": "v0002",

  "model_type": "deterministic_weighted_multisignal",

  "feature_version": "features-v1",

  "schema_version": "telemetry-v1",

  "artifact_hash": "sha256:...",

  "evaluation_mode": "cost_backtest | heuristic",

  "evidence_quality": "strong | weak",

  "evaluation_scope": "precision_biased_sample",

  "training_period": ["2025-08-01", "2026-01-31"],

  "feature_selection_frozen_at": "...",

  "software_lock_version": "requirements.lock"

}

v21  evaluation_scope field added to the manifest, carrying the recall-blindness caveat from FAQ 4.4 into every artifact, not just the top-level summary.

v22  schema.json added to the package tree above — Section 14 already named it as the authoritative model-specific telemetry contract, but v21's artifact listing omitted it, leaving an implementer to infer an artifact the document itself depends on later.

v25 — restored artifact identity contract  artifact_hash covers the complete immutable behavior-defining inference package: canonical model.joblib + model_config.json + feature_schema.json + scorer_identity.txt. schema.json is validated as part of the artifact contract but is not duplicated into the hash inputs. scorer_identity.txt records the exact committed scorer-source identity and requires a clean-tree assertion at packaging time. artifact_hash identifies the versioned inference package, not the entire runtime environment.

v25 — restored replay/provenance contract  replay_hash = SHA256(canonical_input_bytes || canonical_predictions_csv_bytes). Canonical input uses fixed column order, deterministic row ordering by week_start/timestamp/canonical gateway_id, UTF-8, LF endings, explicit null tokens and fixed numeric serialization. Canonical predictions use week_start, rank, gateway_id, score, reason in fixed order, UTF-8/LF, score serialized to six decimals and deterministic reason truncation. run.json records run_id, model_version, feature_version, schema_version, Python/runtime identity and requirements.lock version/hash.

7. Telemetry monitoring: structural drift first

The first release catches the data contract breaking. It deliberately does not claim to detect every operational change in the network. Statistical/distribution drift is post-v1.

model schema contract

        |

incoming telemetry -> canonical schema -> compare

        |

PASS  -> continue prediction

BLOCK -> drift_report.json + clear operator message

Check

Example

Action

Required columns

57 -> 56; required feature absent

BLOCK prediction; write drift report

Dtype contract

numeric -> string

BLOCK prediction

Timestamp / grain

gateway-hour irregular or duplicated

BLOCK or quarantine, by severity

Unexpected extra column

new optional telemetry field

WARN; ignore if contract still valid

Basic value sanity

impossible range / null spike

WARN or BLOCK per feature contract

Scope boundary: schema drift catches pipeline/contract breakage. It does not prove that the network itself has changed. Firmware shifts, hardware changes, or regional behavior changes would require statistical drift monitoring in a later version.

7A. Data-quality implementation contract  models/<version>/schema.json is the only authoritative model-specific telemetry contract; monitoring/schema_baseline.json is reporting evidence and cannot override it. Exact duplicate gateway-hour records follow one frozen ingestion rule and are logged. Two different records for the same canonical gateway_id + timestamp are conflicting duplicates and BLOCK prediction/evaluation; the system never silently chooses one. Every CSV audit records verified encoding, loader and read status; gateway_master.csv uses cp1252 and field_visits.csv is explicitly verified. Missing-data reason codes are NO_TELEMETRY, INSUFFICIENT_HISTORY, INSUFFICIENT_FEATURE_DATA, INELIGIBLE_DATE and SCHEMA_INVALID, with no invented score for zero-coverage gateways.

8. Evidence / cost gate: rolling temporal windows plus a grouped holdout, with a frozen rule

v20–v23 used a single temporal holdout, capped there specifically to protect the build schedule. That constraint no longer applies to this choice, so the evaluation is strengthened along both axes the FAQ names as what a skeptic checks (6.12: forward in time, and on cases never seen) — applied here to MLOps's promotion gate, not only to the ML track's own evaluation.

Path

Training / holdout

Evaluation

Audited proxy / COST_BACKTEST — rolling temporal

Window 1: Train Aug–Oct, Holdout Nov 2025; Window 2: Train Aug–Nov, Holdout Dec 2025; Window 3: Train Aug–Dec, Holdout Jan 2026. These are expanding training windows with non-overlapping holdout months. Final Feb 2026 holdout is reserved for final reporting and is not used to select weights, thresholds, or the candidate.

missed_broken_gateway_weeks x EUR600 differential vs active, aggregated across all three rolling windows; EUR45,600 fixed visit cost shown informationally only.

Audited proxy / COST_BACKTEST — grouped

A fixed GROUP_HOLDOUT_IDS set is generated and frozen before feature discovery and configuration/weight selection. Those IDs are excluded from the four-hour EDA and from every candidate-construction/training computation in all rolling windows. They are scored only after v0002 is frozen. This is a true grouped holdout, not merely an alternative label split.

Same missed_broken_gateway_weeks x EUR600 differential, computed only on the held-out gateway subset.

Weak proxy / HEURISTIC

Uses the same expanding temporal + grouped structure and frozen gateway split; no economic interpretation is claimed.

missed_proxy_burden = sum of shared 3-sigma flagged hours over eligible gateway-weeks NOT selected; never converted to claimed observed EUR cost.

v24 — rolling windows replace the single holdout  Restores the multi-window evidence design considered in earlier drafts and deferred purely for schedule reasons. The frozen candidate is evaluated on three expanding development/holdout windows, not merely one period; this is a stronger, more honestly tested claim, and all computation remains offline in train.py and is never touched by predict.py or the rollback demo.

v24 — grouped holdout, implementation-tightened in v25  A fixed GROUP_HOLDOUT_IDS set is frozen before feature discovery and configuration selection. Those gateway IDs are excluded from the four-hour EDA, from every candidate-construction/training computation in all rolling windows, and from any parameter/weight selection. After v0002 is frozen, the grouped subset is scored separately. The group assignment itself is never changed after selection begins. This supplies the "grouped and forward" discipline named in FAQ 6.12 without changing the runtime prediction path.

v21 — FIX (this is the substantive correction)  FAQ 5.2 states €380 is charged once per visit dispatched, whatever it finds, and every valid submission dispatches exactly 15 visits × 8 weeks = 120, so the visit-cost term is €45,600 for any valid candidate — a constant, not a function of how many visits were "wasted." v20's formula (wasted_visits × €380 + missed_broken_gateway_weeks × €600) implied the €380 term varies with model quality; it does not, under the official 15-per-week accounting. Corrected: the promotion/rejection decision now compares only missed_broken_gateway_weeks × €600 between candidate and active — the one term that actually differs between two valid top-15 rankings. The full informational cost figure shown to an operations manager may still display total_cost = €45,600 + missed_broken_gateway_weeks × €600 for readability, and wasted-visit count may still be reported as a separate, non-cost-bearing quality indicator — but neither feeds the promotion delta.

Frozen promotion rule.  For COST_BACKTEST: promote only when the candidate's aggregate missed_broken_gateway_weeks across all three rolling windows is at least 10% lower than active's, AND the candidate is not worse than active in any individual window (no window may regress even if the aggregate improves), AND the grouped holdout shows the same direction of improvement. All three conditions together, not the average alone — a candidate that wins big in one window and loses in another is not promoted just because the sum looks good. For HEURISTIC: the same three-part structure, using missed_proxy_burden on the exact common evaluation population. The 10% rule is a precommitted operational materiality threshold, not statistical significance.

8A. Evaluation population and coverage contract — frozen  Active and candidate evaluations MUST use the exact same common valid gateway-week population: date-eligible gateway-weeks with required telemetry, valid shared feature contract and valid comparable outputs for both models. Record evaluation_population_total, active_valid_count, candidate_valid_count, common_valid_count and excluded_due_to_model_input. Assert active_eval.keys() == candidate_eval.keys() == common_eval.keys() and the common set is non-empty. Promotion additionally requires common_valid_count / max(active_valid_count, candidate_valid_count) >= policy.json minimum_coverage_ratio, frozen at 0.90. Below this threshold, reject with REJECT_COVERAGE; a candidate may not improve its metric by becoming less applicable.

8B. Zero-baseline and evidence-state contract — frozen  If the active evaluation metric is zero, the relative 10% improvement rule cannot demonstrate improvement; return REJECT_ZERO_BASELINE unless a separately defined improvement metric exists (V1 defines none). In HEURISTIC mode, every corresponding count is marked as proxy evidence and no proxy is presented as observed euro savings.

8C. Frozen retraining policy — policy.json is written before evaluation  degradation_metric = current_active_metric / current_reference_metric; degradation_threshold = 1.10; reference = frozen reference artifact evaluated on the current comparable population; zero_reference_rule = if reference == 0, authorize only when current_active_metric > 0, while 0 versus 0 authorizes no retraining; action = authorize candidate creation only; auto_retrain = false. Retraining may be initiated by explicit operator invocation or the documented review run. Drift can block prediction and motivate review, but never changes production state automatically. Authorization never promotes a candidate.

8D. Retraining-worse proof — P0  At least one executable test must create a new retrained/materialized candidate version that is demonstrably worse under the frozen evaluation contract, confirm the appropriate rejection state, and confirm the previously active version remains active. The committed deterministic lifecycle fixture may provide the guaranteed live-demo case; any real worse candidate is additional evidence, not a substitute for the fixture.

v24  Added the two no-regression conditions (no individual window may regress; grouped holdout must agree in direction) on top of the aggregate 10% rule. Without them, a candidate could pass purely on the strength of one favorable window while quietly being worse elsewhere — exactly the kind of result that would not survive being asked to defend it live.

v21  Added justification for the number itself: 10% is set to avoid promoting on evaluation noise given a label-bearing development sample, while remaining achievable for a deliberately small, fixed-weight feature set. Sensitivity (5% / 10% / 20%) is still reported for transparency and is never used to retune the frozen rule after results are seen.

v22 — hedge on an unconfirmed number  v21 stated the development sample has "roughly 90 usable cases." That figure came from exploratory audit work done ahead of this document, not from the frozen label-audit step (2C/2D) itself — asserting it as settled fact inside an architecture freeze risks the same invented-number problem this document warns against elsewhere. Corrected: 10% is a precommitted materiality threshold sized to the expected development evidence volume; preliminary exploration located approximately 90 candidate cases, but the frozen label-audit step re-establishes and reports the exact count before COST_BACKTEST is used, and 10% is not retuned based on that count either way.

v22 — proxy, not an official-score estimate  COST_BACKTEST is an internal promotion proxy for comparing v0002 against v0001, not an estimate of LPDG's own held-out score. A candidate showing, say, a 10% internal cost improvement should not be read as implying the official challenge score improves by a comparable amount — the two are computed against different, non-comparable ground truths (see evaluation_scope, Operations-Manager Summary).

Decision

Rule

Reject

Candidate does not clear the aggregate 10% bar, or regresses in any individual rolling window, or the grouped holdout disagrees in direction, or fails validity/safety checks. Rejection is a successful lifecycle outcome: the gate prevented an unjustified production change and the current version remains active.

Promote

Candidate clears the aggregate 10% bar with no per-window regression, the grouped holdout agrees in direction, and all validity/safety checks pass, before the active pointer changes.

Retrain trigger

Explicit operator invocation or documented review point, subject to policy.json degradation test on the same current common population. Structural drift may block prediction and trigger review, but never auto-deploys. Authorization creates a candidate only; promotion remains separately gated.

Post-promotion

Keep candidate artifact, evidence, audit record and prior production version immutable.

Safety checks are executable, not subjective: any ineligible gateway selected, duplicate gateway/rank, NaN score/reason, rank outside 1..selected_count, selected_count != 15 for a required scored week, or invalid prediction-schema fields is a submission safety violation. A runtime week with fewer than 15 eligible+telemetry-available gateways is a hard data condition: fail clearly with INSUFFICIENT_ELIGIBLE_GATEWAYS; never invent or duplicate gateways.

9. The 15-visit cap: backlog economics as executable evidence

The model ranks all valid candidates. Apply the hard cap of 15 visits: select the top 15 when at least 15 valid candidates exist; otherwise fail clearly with INSUFFICIENT_ELIGIBLE_GATEWAYS rather than fabricate rows. Everything above rank 15 remains visible as deferred backlog evidence.

v21  FAQ 3.4: there is no way to express "only 9 gateways truly need a visit" inside predictions.csv — exactly 15 rows per week are mandatory regardless of model confidence, and this does not cost extra (visit cost is fixed per the Section 8 fix above); it is only a wasted opportunity if ranks 10–15 are not genuinely at risk. predict.py therefore always fills the full top 15 by score, independent of any internal confidence threshold the model may compute. Where the candidate's own threshold logic would flag fewer than 15 as genuinely warranting a visit, that judgment is recorded in DECISIONS.md narrative ("in week N, only K gateways cleared our internal threshold; ranks K+1..15 are the next-highest scores and here is what we would not have sent anyone for") — never expressed by omitting rows from the file.

v21  FAQ 3.3: rank order is not read by the cost script, but is the first thing a human reviewer sees. Added acceptance rule so the emitted list reads sensibly top-to-bottom for an operations manager, not just format-valid.

v22 — FIX (contradiction)  v21 phrased the rule as "rank must correspond to strictly descending model score (deterministic tie-break on gateway_id)" — internally contradictory, since a tie-break only has meaning when scores are allowed to be equal, and "strictly descending" forbids ties by definition. Corrected: rank corresponds to non-increasing model score; equal scores are ordered deterministically by canonical gateway_id.

all eligible gateways

        |

        +-- ranks 1-15  -> field visits

        |

        `-- ranks 16+   -> deferred backlog

                           |

                           `-- backlog_report.json

backlog_report.json — illustrative example only; all values below are computed at runtime and never hard-coded:

{

  "week_start": "2026-03-23",

  "max_visits": 15,

  "selected_count": 15,

  "deferred_high_risk_count": 13,

  "deferred_risk_proxy_score": 4200,

  "exposure_method": "heuristic_proxy",

  "evidence_quality": "weak"

}

9A. Single scoring pass is an integrity constraint. predict.py computes one ranked eligible-candidate object after eligibility filtering and model scoring. That same object feeds predictions.csv and backlog_report.json; neither output recomputes scores, rankings, eligibility or evidence mode independently.

Backlog report must be currency-honest. In COST_BACKTEST mode, an economic field may be named exposure_value_eur only when derived from the audited €380/€600 model. In HEURISTIC mode the field must be deferred_risk_proxy_score and must never be described as observed € savings. The report also records evidence_quality, model_version and evidence_mode.

10. Registry + rollback: optimize for the live session

registry/active.json

{

  "production_version": "v0002",

  "previous_version": "v0001",

  "changed_at": "...",

  "reason": "passed promotion gate"

}

registry/history.jsonl

TRAINED -> EVALUATED -> PROMOTED / REJECTED -> ROLLED_BACK

v23  Renamed from make demo-rollback (v21/v22) to make rollback, matching the single command already named as canonical in Section 5A. The same command is what gets exercised live — there is no separate "demo" variant to keep track of.

make rollback:

1. show active = v0002

2. predict -> record v0002 replay hash

3. validate rollback target artifact + manifest + model-specific schema + smoke prediction

4. only after validation passes, atomically switch active v0002 -> v0001

5. smoke-predict with v0001

6. predict again with v0001

7. assert second v0001 predictions.csv == first v0001 predictions.csv

8. assert active == v0001

10A. Recording evidence: demonstrate rejection, not only success.

Show: evaluate v0002 → REJECT → registry/active.json remains on v0001 → predict → v0001 is still served. This demonstrates that the lifecycle prevents an unproven or worse candidate from silently replacing the active version.

Reserve a short recording segment for an intentionally rejected candidate. Use a committed demo fixture/configuration that makes the candidate fail the frozen promotion gate; do not mutate production artifacts or falsify the real evaluation record. The rollback demonstration requires a legitimate previously promoted version: promote real v0002 only if it passes the frozen gate before the demo. Independently retain a committed deterministic lifecycle fixture where the same promotion policy legitimately passes, so rollback mechanics are not hostage to the real candidate result and the fixture is never presented as production performance.

v21 — no design change, confirmation only  FAQ 6.14 confirms rollback is graded purely on mechanism (real versioned artifact, a rehearsed swap not an improvisation, same input+version reproduces same output, an audit trail) with no ground truth given to prove it "worked better," and states plainly: "a rollback you first attempt in front of us will not work — practise it." This validates the rollback design exactly as built. The only action item is operational: rehearse it before hand-in, more than once.

v24 — see Section 19 for the optional second rejection case  The guaranteed fixture above remains mandatory and unconditional. Section 19 describes an optional, additional real rejection (a genuinely different v0002 variant, correctly rejected on its own merits) — a second, earned data point that the gate discriminates, not a replacement for the guaranteed demo.

11. Minimum test matrix

P0 — load-bearing, all of these must pass before anything else is added:

Test

What it proves

same_input_same_version_same_output

Deterministic replay of the inference contract.

rollback_restores_previous_prediction

Validated rollback target becomes active and reproduces prior prediction content.

candidate_worse_is_rejected

Frozen promotion gate rejects a genuinely worse candidate and leaves active unchanged.

top_15_hard_limit

Hard cap, 15 distinct IDs, deterministic rank/tie rules, insufficient-candidate failure.

validate_submission_actual

The actual supplied validator returns PASS for the generated 8-week submission.

leakage_cutoff_fixture

Post-cutoff data (incl. the 15-Feb engineer review) cannot alter earlier prediction features.

gateway_eligibility_by_week

Install/decommission filtering and canonical ID joins are correct.

train_then_predict_end_to_end

Core lifecycle works end-to-end, no production mutation, AND inline-asserts feature parity between train and predict, identical candidate/active evaluation population, and correct right-censoring exclusion (see v22 note below).

unseen_month_prediction

An arbitrary unseen month/week runs without challenge-week hardcoding, including a never-before-seen gateway ID and a previously-reporting gateway gone recently silent (see v22 note below).

clean_environment_smoke

make run — the single reviewer-facing entry point (Section 5A) — succeeds on a fresh clone with only data/ populated, and produces a validator-passing predictions.csv. Moved here from P1 in v23 (see note below).

fleet_wide_absence_blocks_features

A fixture simulating a fleet-wide ingestion gap (many gateways simultaneously silent) trips the Section 2B source-completeness guard into BLOCK_FEATURES, rather than scoring every affected gateway as high-risk via recent_silence_ratio. Added in v23 (see note below).

rolling_window_aggregation_correct

The three expanding training windows and non-overlapping holdout months are bounded correctly and aggregate correctly; a synthetic candidate that wins in aggregate but regresses in one window is REJECT_WINDOW_REGRESSION.

grouped_holdout_never_leaks_into_selection

GROUP_HOLDOUT_IDS are frozen before selection and never enter EDA, feature/weight selection, or any candidate-construction/training computation; they are scored only after the candidate is frozen.

evaluation_common_population_and_coverage

Active/candidate key sets are identical and non-empty; 0.90 minimum coverage is enforced and REJECT_COVERAGE fires below it.

retrained_candidate_worse_is_rejected

A newly retrained/materialized candidate can be worse and is rejected under the frozen gate; the current active model remains unchanged.

v22  train_then_predict_end_to_end is now required to assert, inline, the specific invariants named under the P1 entries train_predict_feature_parity, candidate_active_population_identical and right_censoring_label — not merely confirm the pipeline runs without error. P1 priority means these don't need separate standalone tests, not that the invariants themselves are optional; without this note the P1 label risks reading as "nice to have."

v22  unseen_month_prediction now explicitly requires two fixture cases the FAQ (6.11) names directly: a gateway ID the model has never seen, and a gateway with an established reporting history that has gone completely silent in the test month. Both are cheap to add since eligibility filtering and recent_silence_ratio already implement the underlying logic — this only adds the test fixtures that exercise them.

v23 — severity correction  clean_environment_smoke previously sat in P1, but Section 5A names make run a "P0 delivery contract" and the FAQ states plainly that a repository which does not run on the reviewer's machine is not scored at all — the test proving that exact thing cannot itself be optional. Promoted to P0.

v23 — new P0 test, closing a real gap  v22 added the Section 2B source-completeness guard specifically to stop a fleet-wide outage from being misread as hundreds of individual gateway failures, but no test verified the guard actually fires. Without this test, the guard is a described behavior, not a proven one — added fleet_wide_absence_blocks_features as P0 alongside it.

v24 — tests for the strengthened evaluation  rolling_window_aggregation_correct and grouped_holdout_never_leaks_into_selection are added as P0 because the Section 8 upgrade is only as trustworthy as its own arithmetic and isolation guarantees — a rolling-window evaluator with a boundary bug, or a grouped holdout that accidentally leaks into training, would silently invalidate the entire strengthened evidence story.

P1 — real, but not load-bearing; write only after every P0 passes and the live-demo path is rehearsed end to end. If time is short, this list is the first thing to trim, not the P0 list:

label_definition_sanity, known_bug_regression, train_predict_feature_parity, candidate_active_population_identical

baseline_cold_start_policy, reason_limit_and_serialization, replay_canonicalization, promotion_zero_baseline

atomic_promotion_boundary, rollback_validation_failure_preserves_active, predict_no_side_effects, train_no_production_mutation

submission_wrapper_no_side_effects, eight_week_order_and_count, corrupted_artifact_rejected

immutable_artifact_after_registration, rollback_retains_candidate, right_censoring_label, promotion_idempotency

rollback_idempotency, stale_active_pointer_rejected

12. Deliberate shortcuts — and what they cost

Shortcut

Why V1 takes it

Risk / follow-up

Rolling + grouped holdout (v24)

Time and gateway-generalization evidence together, deliberately upgraded once schedule was no longer the limiting factor.

More evaluator complexity than a single holdout; mitigated by keeping the evaluator itself simple arithmetic over precomputed per-window costs, not a new modeling technique.

Schema drift only

Directly satisfies the shape-monitoring requirement.

Misses statistical network drift; add later.

Filesystem registry

Transparent, offline and trivial to demo.

Not for concurrent production writers; fine here.

Two runtime hashes

artifact_hash + replay_hash are sufficient for identity and replay proof.

Less provenance granularity; acceptable.

No auto-deploy on drift

Prevents a noisy signal from changing production state.

Requires explicit promotion; intentional.

ID canonicalization

One canonicalizer at ingestion prevents silent join failures.

Keep exactly one implementation.

NO_TELEMETRY exclusion (zero-coverage case only, see 2B)

A date-eligible gateway with genuinely no telemetry cannot be scored honestly.

Recently-silent gateways are now a feature, not excluded — see v21 fix.

Small v0002

Keeps Track F focused on lifecycle mechanics, not model novelty.

Less modeling sophistication; acceptable for this track.

13. State machine reference

Area

State

Meaning / action

Prediction

PASS

Prediction completed and output contract is valid.

Prediction

NO_ACTIVE_MODEL

active.json missing/unreadable; never infer latest.

Prediction

BLOCK_SCHEMA

Required contract violated; write drift_report.json.

Prediction

BLOCK_FEATURES

Feature contract cannot be satisfied.

Prediction

BLOCK_ARTIFACT

Active artifact missing, corrupt, or integrity check fails; active pointer unchanged.

Prediction

INSUFFICIENT_ELIGIBLE_GATEWAYS

Fewer than 15 eligible + telemetry-backed gateways; do not fabricate rows.

Evaluation

REJECT_NOT_BETTER

Candidate fails the aggregate 10% rule.

Evaluation

REJECT_WINDOW_REGRESSION

Candidate regresses in an individual rolling window despite the aggregate improving (v24).

Evaluation

REJECT_GROUPED_DISAGREEMENT

Grouped held-out-gateway holdout disagrees in direction with the temporal result (v24).

Evaluation

REJECT_INVALID

Candidate fails validity/safety checks.

Evaluation

RETRAIN_AUTHORIZED

Frozen policy conditions authorize candidate creation only; no production change.

Evaluation

REJECT_ZERO_BASELINE

Relative improvement cannot be shown from zero.

Evaluation

REJECT_COVERAGE

Common evaluation coverage below frozen minimum; candidate cannot become active.

Registry

PROMOTED

Atomic active-pointer switch completed.

Registry

ROLLED_BACK

Validated prior artifact became active.

14. Evidence and artifact map

Artifact

Authoritative for

Must not be used for

manifest.json

Model identity, contract versions, provenance

Does not determine active version

schema.json

Model-specific telemetry contract

Not a global mutable default

feature_schema.json / model_config.json

Feature implementation + frozen v0002 config

Not a post-hoc tuning store

metrics.json

Evaluation and promotion evidence

Does not change production state

run.json

One execution context

Not mutable registry state

history.jsonl

Lifecycle audit evidence

Not authoritative active state

active.json

Authoritative active model pointer

Not historical audit source

drift_report.json

Structural incoming-contract result

Never auto-deploys

backlog_report.json

Deferred ranks and evidence-qualified exposure/proxy

Never independently recomputes scores

predictions.csv

Challenge submission output

Not registry state

AI-USAGE.md

AI usage disclosure + one caught error

Not runtime logic

LIMITATIONS.md

Part 1 "what it cannot do"

Not runtime control logic

policy.json

Frozen evaluation coverage + retraining governance

Not post-hoc tuned from observed results

15. Delivery checklist

Before hand-in: run the full test suite, run the actual supplied validate_submission.py, verify AI-USAGE.md is present and honest, record a normal multi-commit history, scrub secrets from history, complete the 6–8 minute screen recording, and keep challenge data out of the public repository. These are delivery gates, not architecture features.

v21 — added, from the FAQ, not previously listed  Put data/ in .gitignore on day one, before the first commit, not as a pre-publish cleanup step (FAQ 1.2). Making a repository public makes its entire history public — a data file or a key committed and later removed is still visible in history; check the full commit log, not just the current tree, before flipping the repository public. Link the recording in the README, or commit it directly if small (FAQ 1.3).

Output-count edge case. If fewer than 15 gateways are both date-eligible and telemetry-available for a scored submission week, predict.py must fail clearly with INSUFFICIENT_ELIGIBLE_GATEWAYS rather than fabricate rows or silently pass a short file. The data audit must establish that the eight required scored weeks have enough eligible, telemetry-backed gateways for the mandatory 15-row submission.

16. DECISIONS.md starter set

Decision

Chosen

Alternative rejected

Reason

Track selection

MLOps (F).

ML as primary track.

The challenge defines F around lifecycle controls, so model novelty stays deliberately secondary.

Evidence mode + label framing

COST_BACKTEST when N=3 development-period sanity evidence passes; otherwise HEURISTIC. Detect an already-degraded gateway from retrospective evidence.

Treat ambiguous visit text as ground truth, or make future-onset prediction the primary task.

Preserves lifecycle evidence without fabricating economic certainty; the forgone lead-time of retrospective detection is recorded as a limitation.

Model + scope

v0001 = supplied 3-sigma; v0002 = small fixed weighted scorer; four-hour feature freeze; rolling + grouped evidence are offline-only.

Large stochastic model or open-ended EDA.

Keeps the candidate explainable and deterministic while using stronger validation without complicating the runtime path.

Promotion + retraining + rollback

Frozen 10% gate with common-population/0.90 coverage and no-regression checks; policy.json authorizes candidate creation only; rollback validates target, atomically switches pointer, then proves prediction equality.

Post-hoc threshold tuning, auto-deploy on drift, or retraining as a rollback mechanism.

Makes production change evidence-gated and reversible; a worse retrained candidate can be rejected and the prior artifact restored.

Data correctness

cp1252 loader contract, verified visit-file encoding, canonical IDs, UTC cutoff on every file, date eligibility, source-completeness guard, single scoring pass.

Rely on implicit joins, treat silence as calm, or mix Berlin/IST/data timezones.

Prevents silent correctness failures and protects the decision pipeline from missing-data and timezone errors.

17. Recording storyline (restored, updated for v24)

The 6–8 minute recording is a required Part 1 deliverable and 15% of the mark is explicitly for whether the explanation would convince an operations manager. A rehearsed structure is not optional polish — it is the difference between demonstrating the lifecycle and merely narrating code on screen.

Time

Show

0:00

The problem in one sentence, and why MLOps (not model novelty) is the right boundary for this submission.

1:00

Repository structure and the single reviewer-facing entry point: make run, end to end, on a clean clone.

2:15

The v0001/v0002 model artifacts — manifest, schema, hashes — and what makes them immutable and versioned.

3:15

predict.py: deterministic replay (same input + version, same output hash) and the schema drift guard firing on a broken fixture.

4:15

The evidence gate: rolling-window + grouped-holdout results, and the guaranteed REJECT fixture — active model stays active.

5:15

Backlog exposure: predictions.csv plus backlog_report.json, and one sentence on what's being accepted by the 15-visit cap.

6:15

Live rollback: v0002 -> v0001, prediction equality asserted, active pointer confirmed.

7:15

One named limitation (from LIMITATIONS.md) and what another two weeks would buy — closing on judgement, not on a feature list.

Keep the pacing loose — this is a target shape, not a script to read verbatim. The two minutes that matter most under time pressure are the rejection demo and the rollback: everything else can compress before those do.

18. Translating technical evidence into operations-manager language

The FAQ specifies this register directly, more than once: the reason field, DECISIONS.md, and the recording are written for someone who has to act on the answer, not for the reviewer. Every technical field this system produces should have a one-sentence plain-language translation ready — for the recording, for DECISIONS.md, and for live-session follow-up questions.

Technical field / concept

What an operations manager should actually hear

evidence_quality=weak / evaluation_scope=precision_biased_sample

"We're confident about gateways that were already suspected; we can't yet promise the same about ones nobody's looked at."

missed_broken_gateway_weeks (COST_BACKTEST differential)

"On the weeks we can check honestly, this version would have left fewer gateways broken and unvisited than what we're running today."

REJECT_WINDOW_REGRESSION

"This update looked better on average, but it would have been worse in at least one real month — so we didn't ship it."

recent_silence_ratio flag

"This gateway used to report in regularly and has now gone completely quiet — that's usually worse than an odd reading, not better."

backlog_report.json deferred_high_risk_count

"We can only send 15 people a week. Here's how many more looked risky and what we're accepting by not sending anyone."

Rollback demo

"If a change goes wrong, we can undo it in minutes and prove the old version is really back — this isn't a manual, improvised fix."

This table is a starting point for DECISIONS.md and the recording script, not a substitute for writing both in full sentences once real numbers exist.

19. Optional judgement-strengthening enhancements (not required for Part 1 or the F bullet points)

Both items below are genuine, defensible upgrades to the judgement (25%) score. Neither is required by Part 1, by the F track's own bullet points, or by the FAQ. Both are explicitly bounded so they cannot turn into the "clever parts" the live session punishes — if either starts growing past its stated scope, cut it, not the P0 list.

19A. A second, earned rejection.  The guaranteed fixture in Section 10A stays mandatory regardless. Optionally, also attempt one genuinely different v0002 variant — a defensible but ultimately weaker feature weighting, reached honestly, not deliberately sabotaged — and let the real frozen gate reject it using the actual Section 8 evaluation. Record the evidence (which window(s) it failed, or whether the grouped holdout disagreed) alongside the guaranteed fixture. Two independent proofs that the gate discriminates — one guaranteed to work, one earned on its own merits — is a stronger judgement story than either alone, and it costs nothing at the live session since it's a recorded, offline result, not something re-run live.

19B. A tightly-scoped value-distribution check.  Bounded explicitly to only the 2–3 features v0002 actually uses — not a PSI/KS sweep across all 57 telemetry columns, which would be exactly the kind of unscoped statistics project this document has repeatedly cut for schedule and focus reasons and which the F bullet points don't ask for. A simple trailing quantile-band check (is this week's feature distribution inside the range seen during training, for the handful of features that matter) is enough to demonstrate awareness that "what happens when the network changes" is a real question, without building a second monitoring subsystem. If scoping this to 2–3 features starts to feel restrictive, that feeling is the signal to stop, not to widen it.

20. Definition of done — real numbers before freeze

Every illustrative JSON value and current-body placeholder figure in this document exists to describe a report shape, not a result. Before hand-in, replace current illustrative values in manifest.json, metrics.json and backlog_report.json with actual computed values from the real run; record the frozen label-audit count; report the rolling-window and grouped-holdout results exactly as produced by the evaluator; and populate LIMITATIONS.md with the measured telemetry-coverage blind spot and the concrete change another two weeks would enable. Do not retune the 10% governance threshold from the observed count. Historical changelog text is retained as history and must not be mistaken for current evidence.