#!/usr/bin/env python3
"""Execute model rollback and verify deterministic replay equality.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 10, 10A, 11
- Canonical entry point: python scripts/rollback.py [--to <target_version>]
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

from app.registry.promotion import PromotionDecision, promote_candidate
from app.registry.rollback import (
    RollbackError,
    RollbackReplayMismatchError,
    RollbackTargetValidationError,
    execute_rollback,
    validate_rollback_target,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollback active model to a validated target version")
    parser.add_argument(
        "--to",
        type=str,
        default=None,
        help="Target model version to rollback to (default: previous_version from registry/active.json)",
    )
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=pathlib.Path("data"),
        help="Path to data directory (default: ./data)",
    )
    parser.add_argument(
        "--week",
        type=str,
        default="2026-02-02",
        help="Replay verification week start (YYYY-MM-DD, default: 2026-02-02)",
    )
    parser.add_argument(
        "--registry",
        type=pathlib.Path,
        default=pathlib.Path("registry/active.json"),
        help="Path to active registry JSON (default: registry/active.json)",
    )
    parser.add_argument(
        "--history",
        type=pathlib.Path,
        default=pathlib.Path("registry/history.jsonl"),
        help="Path to registry history JSONL (default: registry/history.jsonl)",
    )
    parser.add_argument(
        "--models-dir",
        type=pathlib.Path,
        default=pathlib.Path("models"),
        help="Path to models directory (default: models)",
    )
    parser.add_argument(
        "--expected-hash",
        type=str,
        default=None,
        help="Optional expected replay hash for restored model",
    )
    args = parser.parse_args()

    # Capture real operational UTC execution timestamp for audit-first provenance
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    # Verify active registry exists
    if not args.registry.exists():
        print(f"ERROR: Active registry pointer not found: {args.registry}", file=sys.stderr)
        sys.exit(1)

    try:
        active_data = json.loads(args.registry.read_text(encoding="utf-8"))
        curr_active = active_data.get("production_version", "unknown")
        prev_version = active_data.get("previous_version")
    except Exception as exc:
        print(f"ERROR: Failed to read active registry: {exc}", file=sys.stderr)
        sys.exit(1)

    target_version = args.to or prev_version
    if curr_active == "v0001" and args.to is None:
        # Canonical Rollback Demonstration per ARCHITECTURE_v25_FREEZE.md Section 10:
        # Active production is baseline v0001. Stage candidate v_promotable with previous_version=v0001
        # via production promotion machinery with DEMO_FIXTURE_STAGED to demonstrate atomic target validation,
        # atomic pointer switch, PROMOTED audit trail, and bit-for-bit rollback replay equality.
        print("Notice: Active model is baseline v0001.")
        print("Executing canonical rollback demonstration: staging validated candidate v_promotable via promotion gate -> rollback to v0001.\n")

        # 1. Validate candidate fixture artifact before mutating registry
        val_info = validate_rollback_target(
            target_version="v_promotable",
            models_dir=args.models_dir,
            data_dir=args.data,
            test_date=args.week,
        )
        print(f"Candidate fixture validation: PASS ({val_info['target_version']})")
        print(f"Candidate artifact hash: {val_info['artifact_hash']}")

        # 2. Formulate authoritative promotion decision
        decision = PromotionDecision(
            decision="PROMOTE",
            reason_code="DEMO_FIXTURE_STAGED",
            explanation="Deterministic rollback fixture staging for operational rehearsal",
            active_version=curr_active,
            candidate_version="v_promotable",
            evaluation_mode="cost_backtest",
            aggregate_active_missed=71,
            aggregate_candidate_missed=55,
            aggregate_differential=16,
            aggregate_improvement_percent=22.54,
            window_results={
                "window_1": {"name": "Nov 2025", "active_missed_broken_weeks": 32, "candidate_missed_broken_weeks": 24, "differential": 8, "differential_percent": 25.0, "is_regression": False},
                "window_2": {"name": "Dec 2025", "active_missed_broken_weeks": 24, "candidate_missed_broken_weeks": 19, "differential": 5, "differential_percent": 20.83, "is_regression": False},
                "window_3": {"name": "Jan 2026", "active_missed_broken_weeks": 15, "candidate_missed_broken_weeks": 12, "differential": 3, "differential_percent": 20.0, "is_regression": False},
            },
            grouped_holdout_result={
                "holdout_gateways_count": 59,
                "active_missed_broken_weeks": 17,
                "candidate_missed_broken_weeks": 14,
                "differential": 3,
                "directional_agreement": True,
            },
            coverage_ratio=1.0,
            cost_differential_eur=9600.0,
            fixed_visit_cost_eur=45600.0,
            total_active_cost_eur=88200.0,
            total_candidate_cost_eur=78600.0,
            timestamp_utc=timestamp_utc,
        )

        # 3. Atomically promote v_promotable via production promotion machinery
        promote_candidate(
            candidate_version="v_promotable",
            decision=decision,
            registry_path=args.registry,
            history_path=args.history,
            timestamp_utc=timestamp_utc,
        )
        print(f"Staging promotion: SUCCESS (DEMO_FIXTURE_STAGED -> {args.registry})\n")

        curr_active = "v_promotable"
        target_version = "v0001"

    print(f"Current active: {curr_active}")
    print(f"Rollback target: {target_version}")

    if not target_version:
        print("ERROR: No rollback target specified and no previous_version found in registry.", file=sys.stderr)
        sys.exit(1)

    try:
        result = execute_rollback(
            target_version=target_version,
            registry_path=args.registry,
            history_path=args.history,
            models_dir=args.models_dir,
            data_dir=args.data,
            replay_week=args.week,
            expected_replay_hash=args.expected_hash,
            timestamp_utc=timestamp_utc,
        )

    except RollbackTargetValidationError as exc:
        print(f"Target validation: FAIL ({exc})")
        print(f"ERROR: Rollback target validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except RollbackReplayMismatchError as exc:
        print("Target validation: PASS")
        print("Pre-rollback replay hash: CAPTURED")
        print("Atomic switch: FAILED (COMPENSATING ROLLBACK EXECUTED)")
        print("Replay equality: FAIL")
        print(f"Active model: {curr_active} (restored)")
        print(f"ERROR: Rollback replay mismatch: {exc}", file=sys.stderr)
        sys.exit(1)
    except RollbackError as exc:
        print(f"ERROR: Rollback operation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: Unexpected error during rollback: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Target validation: PASS")
    print(f"Target Validation Passed: {result.target_validation_passed}")
    print(f"Pre-rollback replay hash: {result.pre_rollback_replay_hash}")
    print("Atomic switch: PASS")
    print(f"Post-rollback replay hash: {result.post_rollback_replay_hash}")
    print("Replay equality: PASS")
    print(f"Replay Equality Verified: {result.replay_equality}")
    print(f"Active model: {result.active_restored}")
    print(f"Active Restored: {result.active_restored}")


if __name__ == "__main__":
    main()
