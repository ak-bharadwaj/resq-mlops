#!/usr/bin/env python3
"""Promotion gate CLI entry point per frozen architecture contracts.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 8, 8A, 8B, 8C, 8D, 10, 10A, 11
- Makefile target: make promote
- Strict Phase Invariants: Evaluates candidate against active across 3 rolling windows
  and grouped holdout. If PROMOTE, atomically updates registry/active.json.
  If REJECT, leaves registry/active.json byte-for-byte untouched (v0001 remains active).
- Operational Timestamp Authority: CLI captures real UTC execution time and injects
  it into the deterministic core state-transition functions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import pathlib
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.model.evaluate import evaluate_candidate_against_active
from app.model.predict import resolve_active_model_version
from app.registry.promotion import evaluate_promotion_policy, promote_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Promotion gate evaluation CLI")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=pathlib.Path("data"),
        help="Path to data directory (default: ./data)",
    )
    parser.add_argument(
        "--candidate",
        type=str,
        default="v0002",
        help="Candidate model version identifier (default: v0002)",
    )
    parser.add_argument(
        "--active",
        type=str,
        default=None,
        help="Active model version override (default: resolved from registry/active.json)",
    )
    parser.add_argument(
        "--policy",
        type=pathlib.Path,
        default=pathlib.Path("policy.json"),
        help="Path to policy configuration (default: policy.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute evaluation and policy check without mutating active registry",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=pathlib.Path("runs/promotion"),
        help="Directory to save promotion decision record (default: runs/promotion)",
    )
    args = parser.parse_args()

    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    registry_path = pathlib.Path("registry/active.json")
    active_version = args.active or resolve_active_model_version(registry_path)

    # 1. Multi-Window Rolling Temporal + Grouped Holdout Evaluation
    print(f"Starting multi-window evaluation: candidate={args.candidate} vs active={active_version}")
    report = evaluate_candidate_against_active(
        data_dir=args.data,
        candidate_version=args.candidate,
        active_version=active_version,
        registry_path=registry_path,
    )

    # 2. Pure Promotion Policy Evaluation
    decision = evaluate_promotion_policy(report, policy_path=args.policy)

    # 3. Operations-Manager Narrative Output
    print("\n" + "=" * 80)
    print(f"PROMOTION GATE EVALUATION: {args.candidate} vs {active_version}")
    print("=" * 80)
    print(f"Decision:     {decision.decision}")
    print(f"Reason Code:  {decision.reason_code}")
    print(f"Explanation:  {decision.explanation}")
    print(f"Coverage:     {decision.coverage_ratio:.2%} (min required: 90.00%)")

    print("\n--- Temporal Rolling Windows (Development Fleet) ---")
    for w_id, w_res in decision.window_results.items():
        w_name = w_res.get("name", w_id)
        w_act = w_res.get("active_missed_broken_weeks", 0)
        w_cand = w_res.get("candidate_missed_broken_weeks", 0)
        diff = w_res.get("differential", 0)
        pct = w_res.get("differential_percent", 0.0)
        reg = "YES (REGRESSION)" if w_res.get("is_regression") else "NO (OK)"
        print(f"{w_name}: active missed {w_act}, candidate missed {w_cand} | diff={diff:+d} ({pct:+.2f}%) | regressed={reg}")

    print(f"Aggregate Missed Broken Weeks: active {decision.aggregate_active_missed}, candidate {decision.aggregate_candidate_missed}")
    print(f"Aggregate Improvement:         {decision.aggregate_improvement_percent:.2f}% (differential: {decision.aggregate_differential:+d} weeks)")

    print("\n--- Grouped Holdout (Unseen Hardware Fleet) ---")
    gh = decision.grouped_holdout_result
    h_act = gh.get("active_missed_broken_weeks", 0)
    h_cand = gh.get("candidate_missed_broken_weeks", 0)
    h_diff = gh.get("differential", 0)
    h_agree = "AGREED" if gh.get("directional_agreement") else "DISAGREED (REGRESSION)"
    print(f"Held-out Gateways: {gh.get('holdout_gateways_count', 0)}")
    print(f"Holdout Missed:    active {h_act}, candidate {h_cand} | diff={h_diff:+d} | agreement={h_agree}")

    print("\n--- Operations-Manager Economics ---")
    print(f"Technician Dispatch Cost: €{decision.fixed_visit_cost_eur:,.2f} fixed (120 visits × €380, constant across valid models)")
    print(f"Active Model Fault Cost:   €{decision.total_active_cost_eur:,.2f} (€45,600 + {decision.aggregate_active_missed} × €600)")
    print(f"Candidate Fault Cost:      €{decision.total_candidate_cost_eur:,.2f} (€45,600 + {decision.aggregate_candidate_missed} × €600)")
    print(f"Economic Penalty Delta:    €{decision.cost_differential_eur:+,.2f} (missed-fault penalty differential)")
    print("=" * 80 + "\n")

    # 4. Record Decision Artifact
    args.output_dir.mkdir(parents=True, exist_ok=True)
    decision_file = args.output_dir / f"promotion_decision_{args.candidate}.json"
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    decision_record = {
        "candidate_version": args.candidate,
        "active_version": active_version,
        "decision": decision.decision,
        "reason_code": decision.reason_code,
        "explanation": decision.explanation,
        "aggregate_improvement_percent": decision.aggregate_improvement_percent,
        "cost_differential_eur": decision.cost_differential_eur,
        "fixed_visit_cost_eur": decision.fixed_visit_cost_eur,
        "total_active_cost_eur": decision.total_active_cost_eur,
        "total_candidate_cost_eur": decision.total_candidate_cost_eur,
        "coverage_ratio": decision.coverage_ratio,
        "window_results": decision.window_results,
        "grouped_holdout_result": decision.grouped_holdout_result,
        "timestamp_utc": timestamp_utc,
        "promoted_to_production": False,
    }

    # 5. Handle State Mutation
    if decision.decision == "PROMOTE":
        if not args.dry_run:
            promote_candidate(
                candidate_version=args.candidate,
                decision=decision,
                registry_path=registry_path,
                timestamp_utc=timestamp_utc,
            )
            decision_record["promoted_to_production"] = True
            print(f"PROMOTION SUCCESS: Atomically promoted {args.candidate} to production in {registry_path}.")
        else:
            print(f"DRY RUN: {args.candidate} passed promotion gate, but production state was not updated (--dry-run).")
    else:
        print(f"REJECTION ENFORCED: Candidate {args.candidate} was REJECTED ({decision.reason_code}).")
        print(f"Production safety guard active: {registry_path} remains strictly on {active_version}.")

    decision_file.write_text(json.dumps(decision_record, indent=2), encoding="utf-8")
    print(f"Promotion decision record written to: {decision_file}")


if __name__ == "__main__":
    main()
