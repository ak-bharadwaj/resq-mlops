"""Promotion policy engine and production state management.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 8, 8A, 8B, 8C, 8D, 10, 10A, 11
- Policy File: policy.json
- Registry State: registry/active.json, registry/history.jsonl

Strict Invariants:
1. Pure Policy Evaluation: evaluate_promotion_policy is completely side-effect free and
   MUST NEVER mutate registry/active.json.
2. Atomic State Mutation: promote_candidate updates registry/active.json atomically via os.replace,
   and ONLY when decision == 'PROMOTE'.
3. Zero Production Mutation on Rejection: Rejection leaves registry/active.json byte-for-byte untouched.
4. Monotonic Time Authority: Zero system clock calls. Deterministic timestamps.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class PromotionDecision(BaseModel):
    """Authoritative promotion gate decision contract."""
    decision: str = Field(description="'PROMOTE' or 'REJECT'")
    reason_code: str = Field(
        description="Authoritative reason code (PROMOTE, REJECT_NOT_BETTER, REJECT_WINDOW_REGRESSION, "
                    "REJECT_GROUPED_DISAGREEMENT, REJECT_COVERAGE, REJECT_ZERO_BASELINE, REJECT_INVALID)"
    )
    explanation: str = Field(description="Plain English operational narrative for operations manager")
    active_version: str
    candidate_version: str
    evaluation_mode: str = "cost_backtest"
    aggregate_active_missed: int
    aggregate_candidate_missed: int
    aggregate_differential: int
    aggregate_improvement_percent: float
    window_results: Dict[str, Dict[str, Any]]
    grouped_holdout_result: Dict[str, Any]
    coverage_ratio: float
    cost_differential_eur: float
    fixed_visit_cost_eur: float = 45600.0
    total_active_cost_eur: float
    total_candidate_cost_eur: float
    timestamp_utc: str = "2026-09-05T00:00:00Z"

    model_config = {
        "frozen": True,
    }


def load_policy(policy_path: pathlib.Path = pathlib.Path("policy.json")) -> dict[str, Any]:
    """Load and validate policy.json."""
    if not policy_path.exists():
        raise FileNotFoundError(f"Promotion policy file missing: {policy_path}")
    return json.loads(policy_path.read_text(encoding="utf-8"))


def evaluate_promotion_policy(
    eval_report: Any,
    policy_path: pathlib.Path = pathlib.Path("policy.json"),
) -> PromotionDecision:
    """Evaluate promotion policy against a multi-window evaluation report.

    Pure deterministic policy function. Zero side effects. Zero registry mutation.

    Rules:
    1. Coverage ratio >= policy.coverage_contract.minimum_coverage_ratio (0.90) -> else REJECT_COVERAGE
    2. Active baseline aggregate missed > 0 -> else REJECT_ZERO_BASELINE
    3. Individual window regression: candidate_missed <= active_missed in every window -> else REJECT_WINDOW_REGRESSION
    4. Grouped holdout directional agreement: candidate_holdout_missed <= active_holdout_missed -> else REJECT_GROUPED_DISAGREEMENT
    5. Aggregate improvement >= policy.promotion_rule.cost_differential_threshold_percent (10.0%) -> else REJECT_NOT_BETTER
    """
    # Normalize report to dict if it is a Pydantic model
    if hasattr(eval_report, "model_dump"):
        report = eval_report.model_dump()
    elif isinstance(eval_report, dict):
        report = eval_report
    else:
        raise TypeError(f"eval_report must be MultiWindowEvaluationReport or dict, got {type(eval_report)}")

    policy = load_policy(policy_path)
    promo_rule = policy.get("promotion_rule", {})
    cov_rule = policy.get("coverage_contract", {})

    threshold_pct = float(promo_rule.get("cost_differential_threshold_percent", 10.0))
    min_coverage = float(cov_rule.get("minimum_coverage_ratio", 0.90))
    allow_window_regression = bool(promo_rule.get("allow_individual_window_regression", False))
    require_grouped_agreement = bool(promo_rule.get("grouped_holdout_directional_agreement_required", True))
    fault_cost = float(promo_rule.get("missed_broken_gateway_week_cost_eur", 600.0))
    fixed_cost = float(promo_rule.get("fixed_visit_cost_eur", 45600.0))

    active_ver = str(report.get("active_version", "v0001"))
    cand_ver = str(report.get("candidate_version", "v0002"))
    eval_mode = str(report.get("evaluation_mode", promo_rule.get("evaluation_mode", "cost_backtest")))

    windows = report.get("windows", {})
    grouped = report.get("grouped_holdout", {})
    cov = report.get("coverage", {})

    # Authoritative derivation of coverage ratio from fundamental counts (Finding 1 & 2)
    common_cnt = int(cov.get("common_valid_count", 0))
    act_valid_cnt = int(cov.get("active_valid_count", 0))
    cand_valid_cnt = int(cov.get("candidate_valid_count", 0))
    max_valid = max(act_valid_cnt, cand_valid_cnt)
    cov_ratio = (common_cnt / max_valid) if max_valid > 0 else 0.0

    # Authoritative derivation of aggregate missed counts from windows (Finding 2)
    act_agg_missed = sum(int(w.get("active_missed_broken_weeks", 0)) for w in windows.values())
    cand_agg_missed = sum(int(w.get("candidate_missed_broken_weeks", 0)) for w in windows.values())
    diff_agg = act_agg_missed - cand_agg_missed
    imp_pct = (diff_agg / act_agg_missed * 100.0) if act_agg_missed > 0 else 0.0

    cost_differential_eur = diff_agg * fault_cost
    total_act_cost = fixed_cost + (act_agg_missed * fault_cost)
    total_cand_cost = fixed_cost + (cand_agg_missed * fault_cost)

    # Base kwargs for PromotionDecision with authoritatively derived values
    base_kwargs = {
        "active_version": active_ver,
        "candidate_version": cand_ver,
        "evaluation_mode": eval_mode,
        "aggregate_active_missed": act_agg_missed,
        "aggregate_candidate_missed": cand_agg_missed,
        "aggregate_differential": diff_agg,
        "aggregate_improvement_percent": round(imp_pct, 2),
        "window_results": windows,
        "grouped_holdout_result": grouped,
        "coverage_ratio": round(cov_ratio, 4),
        "cost_differential_eur": cost_differential_eur,
        "fixed_visit_cost_eur": fixed_cost,
        "total_active_cost_eur": total_act_cost,
        "total_candidate_cost_eur": total_cand_cost,
        "timestamp_utc": "2026-09-05T00:00:00Z",
    }

    # 1. Coverage Contract Check (Section 8A) - uses authoritatively derived cov_ratio
    if cov_ratio < min_coverage:
        return PromotionDecision(
            decision="REJECT",
            reason_code="REJECT_COVERAGE",
            explanation=(
                f"Candidate coverage ratio ({cov_ratio:.2%}) is below minimum required "
                f"threshold ({min_coverage:.2%}). Model cannot improve metric by reducing applicability."
            ),
            **base_kwargs,
        )

    # 2. Zero-Baseline Contract Check (Section 8B)
    if act_agg_missed <= 0:
        return PromotionDecision(
            decision="REJECT",
            reason_code="REJECT_ZERO_BASELINE",
            explanation="Active model baseline missed broken gateway weeks is zero; relative improvement cannot be demonstrated.",
            **base_kwargs,
        )

    # 3. Individual Window Regression Check (Section 8 / v24)
    if not allow_window_regression:
        for w_id, w_res in windows.items():
            w_name = w_res.get("name", w_id)
            w_act = int(w_res.get("active_missed_broken_weeks", 0))
            w_cand = int(w_res.get("candidate_missed_broken_weeks", 0))
            if w_cand > w_act:
                return PromotionDecision(
                    decision="REJECT",
                    reason_code="REJECT_WINDOW_REGRESSION",
                    explanation=(
                        f"Candidate regressed in rolling window '{w_name}': candidate missed {w_cand} "
                        f"broken weeks vs active {w_act}. Per-window regressions are strictly forbidden."
                    ),
                    **base_kwargs,
                )

    # 4. Grouped Holdout Directional Agreement (Section 8 / v24)
    if require_grouped_agreement:
        h_act = int(grouped.get("active_missed_broken_weeks", 0))
        h_cand = int(grouped.get("candidate_missed_broken_weeks", 0))
        # Direction of improvement requires candidate to not be worse on holdout
        if h_cand > h_act:
            return PromotionDecision(
                decision="REJECT",
                reason_code="REJECT_GROUPED_DISAGREEMENT",
                explanation=(
                    f"Grouped holdout on unseen hardware disagreed with temporal backtest: "
                    f"candidate missed {h_cand} broken weeks vs active {h_act} (+{h_cand - h_act} regression)."
                ),
                **base_kwargs,
            )

    # 5. Aggregate 10% Improvement Rule (Section 8)
    if imp_pct < threshold_pct:
        return PromotionDecision(
            decision="REJECT",
            reason_code="REJECT_NOT_BETTER",
            explanation=(
                f"Candidate aggregate improvement ({imp_pct:.2f}%) did not clear the "
                f"mandatory {threshold_pct:.2f}% threshold ({diff_agg} weeks reduction)."
            ),
            **base_kwargs,
        )

    # 6. All criteria passed -> PROMOTE
    return PromotionDecision(
        decision="PROMOTE",
        reason_code="PROMOTE",
        explanation=(
            f"Candidate cleared the aggregate {threshold_pct:.1f}% improvement bar "
            f"({imp_pct:.2f}% reduction, saving €{cost_differential_eur:,.2f}), "
            f"had zero per-window regressions, and holdout agreed in direction."
        ),
        **base_kwargs,
    )


def promote_candidate(
    candidate_version: str,
    decision: PromotionDecision,
    registry_path: pathlib.Path = pathlib.Path("registry/active.json"),
    history_path: pathlib.Path = pathlib.Path("registry/history.jsonl"),
    timestamp_utc: str = "2026-09-05T00:00:00Z",
) -> dict[str, Any]:
    """Atomically update registry/active.json and record to history.jsonl.

    Safety:
    - Raises RuntimeError if decision.decision != 'PROMOTE'.
    - Validates candidate and active version identity between decision and registry.
    - Fails closed on unreadable or corrupt registry/active.json.
    - Transactional: if writing to history.jsonl fails, executes compensating rollback
      reverting registry/active.json to its prior state.
    """
    if decision.decision != "PROMOTE":
        raise RuntimeError(
            f"Safety Guard: Cannot promote candidate {candidate_version} when decision is {decision.decision} "
            f"({decision.reason_code}): {decision.explanation}"
        )

    if decision.candidate_version != candidate_version:
        raise ValueError(
            f"Decision candidate_version '{decision.candidate_version}' does not match "
            f"requested candidate_version '{candidate_version}'"
        )

    if not registry_path.parent.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)

    previous_version: Optional[str] = None
    orig_active_bytes: Optional[bytes] = None
    if registry_path.exists():
        try:
            orig_active_bytes = registry_path.read_bytes()
            curr_data = json.loads(orig_active_bytes.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"Active registry at '{registry_path}' is corrupt or unreadable: {exc}. Promotion blocked."
            ) from exc

        if not isinstance(curr_data, dict) or not curr_data.get("production_version"):
            raise RuntimeError(
                f"Active registry at '{registry_path}' lacks required 'production_version' field: {curr_data}. Promotion blocked."
            )
        previous_version = str(curr_data["production_version"])

        if decision.active_version != previous_version:
            raise ValueError(
                f"Decision active_version '{decision.active_version}' does not match "
                f"current active production version '{previous_version}' in {registry_path}"
            )

    reason_text = (
        f"staged demonstration fixture: {decision.reason_code}"
        if decision.reason_code == "DEMO_FIXTURE_STAGED"
        else f"passed promotion gate: {decision.reason_code}"
    )

    new_active_payload = {
        "production_version": candidate_version,
        "previous_version": previous_version,
        "changed_at": timestamp_utc,
        "reason": reason_text,
    }

    # Atomic write
    tmp_path = registry_path.parent / f"{registry_path.name}.tmp"
    tmp_path.write_text(json.dumps(new_active_payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, registry_path)

    # Append to history.jsonl with compensating transaction on failure
    history_entry = {
        "event": "PROMOTED",
        "version": candidate_version,
        "candidate": candidate_version,
        "previous_version": previous_version,
        "timestamp": timestamp_utc,
        "reason": reason_text,
        "reason_code": decision.reason_code,
    }
    try:
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history_entry) + "\n")
    except Exception as exc:
        # Compensating transaction: revert active pointer to previous state
        if orig_active_bytes is not None:
            revert_tmp = registry_path.parent / f"{registry_path.name}.revert.tmp"
            revert_tmp.write_bytes(orig_active_bytes)
            os.replace(revert_tmp, registry_path)
        elif registry_path.exists():
            registry_path.unlink()
        raise RuntimeError(
            f"Failed to record PROMOTED event in audit history at '{history_path}': {exc}. "
            f"Compensating transaction executed: active registry reverted to '{previous_version}'."
        ) from exc

    return new_active_payload
