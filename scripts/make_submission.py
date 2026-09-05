#!/usr/bin/env python3
"""Canonical submission entry point foundation."""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.data.loader import get_gateway_eligibility, load_gateway_master

SCORED_WEEKS = [dt.date(2026, 2, 2) + dt.timedelta(days=7 * i) for i in range(8)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 8-week challenge submission foundation")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=pathlib.Path("data"),
        help="Path to data directory (default: ./data)",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("predictions.csv"),
        help="Output CSV path (default: predictions.csv)",
    )
    args = parser.parse_args()

    # Propagate args.data into actual data loader
    master_df = load_gateway_master(args.data)
    print(f"[Phase 1 Foundation] Loaded {len(master_df)} master gateways from {args.data}")

    for monday in SCORED_WEEKS:
        elig_df = get_gateway_eligibility(master_df, monday)
        n_eligible = int(elig_df["is_eligible"].sum())
        if n_eligible < 15:
            print(f"ERROR: Insufficient eligible gateways for {monday}: {n_eligible} < 15", file=sys.stderr)
            sys.exit(1)

    print(f"[Phase 1 Foundation] Data contracts verified across all {len(SCORED_WEEKS)} challenge weeks.")
    print("[Task 1 Notice] Model scoring logic (v0001/v0002) is unproven/not yet implemented in Task 1.")


if __name__ == "__main__":
    main()
