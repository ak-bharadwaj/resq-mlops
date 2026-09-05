#!/usr/bin/env python3
"""Run candidate model training / materialization with --data contract."""
from __future__ import annotations

import argparse
import pathlib
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate training / materialization entry point")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=pathlib.Path("data"),
        help="Path to data directory (default: ./data)",
    )
    args = parser.parse_args()

    # Task 11: Validate data directory exists
    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    raise NotImplementedError("Phase gating: Candidate training and materialization belongs to later tasks.")


if __name__ == "__main__":
    main()
