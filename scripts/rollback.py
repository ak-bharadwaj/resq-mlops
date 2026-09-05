#!/usr/bin/env python3
"""Execute model rollback and verify deterministic replay equality.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 10, 10A, 11
- Canonical entry point: python scripts/rollback.py [--to <target_version>]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.registry.rollback import (
    RollbackError,
    RollbackReplayMismatchError,
    RollbackTargetValidationError,
    execute_rollback,
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
        )
    except RollbackTargetValidationError as exc:
        print(f"Target validation: FAIL ({exc})")
        print(f"ERROR: Rollback target validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except RollbackReplayMismatchError as exc:
        print("Target validation: PASS")
        print("Pre-rollback replay hash: CAPTURED")
        print("Atomic switch: PASS")
        print("Replay equality: FAIL")
        print(f"ERROR: Rollback replay mismatch: {exc}", file=sys.stderr)
        sys.exit(1)
    except RollbackError as exc:
        print(f"ERROR: Rollback operation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: Unexpected error during rollback: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Target validation: PASS")
    print(f"Pre-rollback replay hash: {result.pre_rollback_replay_hash}")
    print("Atomic switch: PASS")
    print(f"Post-rollback replay hash: {result.post_rollback_replay_hash}")
    print("Replay equality: PASS")
    print(f"Active model: {result.active_restored}")


if __name__ == "__main__":
    main()
