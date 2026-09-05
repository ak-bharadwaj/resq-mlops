#!/usr/bin/env python3
"""Run candidate model training and materialization per frozen architecture contracts."""
from __future__ import annotations

import argparse
import pathlib
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.model.train import TrainingError, train_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate training / materialization entry point")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=pathlib.Path("data"),
        help="Path to data directory (default: ./data)",
    )
    parser.add_argument(
        "--candidate",
        type=str,
        default="v0001",
        help="Candidate model version identifier (default: v0001)",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=None,
        help="Optional custom output directory (default: models/<candidate>)",
    )
    args = parser.parse_args()

    # Task 11: Validate data directory exists
    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    try:
        result = train_candidate(
            data_dir=args.data,
            candidate_version=args.candidate,
            output_dir=args.output_dir,
        )
    except (TrainingError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: Candidate materialization failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Materialized candidate model: {result['candidate_version']}")
    print(f"Artifact directory: {result['artifact_dir']}")
    print(f"Artifact hash: {result['artifact_hash']}")
    print(f"Training evidence: {result['evidence_file']}")


if __name__ == "__main__":
    main()
