#!/usr/bin/env python3
"""Run inference with the active model."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

def main() -> None:
    parser = argparse.ArgumentParser(description="Run active model prediction")
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("data"), help="Path to data directory")
    parser.add_argument("--week", type=str, default="2026-02-02", help="Scored week start (YYYY-MM-DD)")
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path("predictions_week.csv"), help="Output CSV")
    args = parser.parse_args()

    with open("registry/active.json", encoding="utf-8") as f:
        active = json.load(f)
    print(f"Active model version: {active.get('production_version')}")
    print(f"Predicting for week {args.week} using data at {args.data}...")

if __name__ == "__main__":
    main()
