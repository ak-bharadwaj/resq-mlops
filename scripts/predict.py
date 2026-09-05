#!/usr/bin/env python3
"""Run inference foundation with active model and --data propagation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.data.loader import get_gateway_eligibility, load_gateway_master
from app.data.schema import TelemetrySchemaContract


def main() -> None:
    parser = argparse.ArgumentParser(description="Run active model prediction foundation")
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
        help="Scored week start (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("predictions_week.csv"),
        help="Output CSV path",
    )
    args = parser.parse_args()

    # Verify active model configuration exists
    active_path = pathlib.Path("registry/active.json")
    if not active_path.exists():
        print("ERROR: registry/active.json missing", file=sys.stderr)
        sys.exit(1)

    with open(active_path, encoding="utf-8") as f:
        active = json.load(f)
    active_version = active.get("production_version", "v0001")

    # Task 11: Validate data directory exists
    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    # Propagate args.data into actual data-loading foundation
    master_df = load_gateway_master(args.data)
    week_date = dt.date.fromisoformat(args.week)
    eligibility_df = get_gateway_eligibility(master_df, week_date)
    eligible_count = int(eligibility_df["is_eligible"].sum())

    print(f"Active model: {active_version}")
    print(f"Data source: {args.data.resolve()}")
    print(f"Week: {args.week} | Eligible gateways: {eligible_count} of {len(master_df)}")


if __name__ == "__main__":
    main()
