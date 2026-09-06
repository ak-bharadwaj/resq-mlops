#!/usr/bin/env python3
"""Run active model inference per frozen architecture contracts."""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.model.predict import (
    InsufficientEligibleGatewaysError,
    ModelArtifactError,
    predict_week,
    resolve_active_model_version,
    write_run_record,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run active model prediction pipeline")
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
    parser.add_argument(
        "--backlog-report",
        type=pathlib.Path,
        default=pathlib.Path("backlog_report.json"),
        help="Output backlog economics JSON report",
    )
    parser.add_argument(
        "--run-record",
        type=pathlib.Path,
        default=pathlib.Path("runs/prediction/run.json"),
        help="Output run provenance JSON record",
    )
    args = parser.parse_args()

    # Task 11: Validate data directory exists
    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    active_path = pathlib.Path("registry/active.json")
    try:
        active_version = resolve_active_model_version(active_path)
    except Exception as exc:
        print(f"ERROR: Failed to resolve active model from registry: {exc}", file=sys.stderr)
        sys.exit(1)

    # Load master and compute eligibility status for operational reporting
    from app.data.loader import get_gateway_eligibility, load_gateway_master
    import datetime as dt

    master_df = load_gateway_master(args.data)
    week_date = dt.date.fromisoformat(args.week)
    eligibility_df = get_gateway_eligibility(master_df, week_date)
    eligible_count = int(eligibility_df["is_eligible"].sum())

    print(f"Data source: {args.data.resolve()}")
    print(f"Active model: {active_version} | Week: {args.week} | Eligible gateways: {eligible_count} of {len(master_df)}")

    has_telemetry = (
        (args.data / "telemetry").exists()
        or (args.data / "telemetry.parquet").exists()
        or (args.data.is_file() and args.data.suffix == ".parquet")
    )
    if not has_telemetry:
        print(f"ERROR: No telemetry partitions found in data directory: {args.data.resolve()}; failing closed.", file=sys.stderr)
        sys.exit(1)

    try:
        result = predict_week(data_dir=args.data, week_start=args.week)
    except (ModelArtifactError, InsufficientEligibleGatewaysError, FileNotFoundError, Exception) as exc:
        print(f"ERROR: Inference failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Write predictions.csv with strictly 6-decimal float formatting and LF line endings
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["week_start", "rank", "gateway_id", "score", "reason"])
        for p in result["predictions"]:
            writer.writerow([
                p["week_start"],
                p["rank"],
                p["gateway_id"],
                f"{p['score']:.6f}",
                p["reason"],
            ])

    # Write backlog report
    args.backlog_report.parent.mkdir(parents=True, exist_ok=True)
    import json
    args.backlog_report.write_text(
        json.dumps(result["backlog_report"], indent=2), encoding="utf-8"
    )

    # Write run record per v25 Section 6 and Section 14
    import hashlib
    pred_bytes = args.output.read_bytes()
    pred_file_hash = f"sha256:{hashlib.sha256(pred_bytes).hexdigest()}"
    timestamp_utc = f"{args.week}T00:00:00Z"

    write_run_record(
        run_path=args.run_record,
        model_version=result["active_version"],
        replay_hash=result["replay_hash"],
        predictions_file_hash=pred_file_hash,
        output_file=str(args.output),
        backlog_file=str(args.backlog_report),
        data_dir=str(args.data),
        week_start=result["week_start"],
        execution_timestamp_utc=timestamp_utc,
    )

    print(f"Active model: {result['active_version']}")
    print(f"Data source: {args.data.resolve()}")
    print(f"Week: {args.week} | Eligible gateways: {result['backlog_report']['selected_count']} selected, {result['backlog_report']['deferred_count']} deferred")
    print(f"Predictions written to {args.output}")
    print(f"Backlog report written to {args.backlog_report}")
    print(f"Replay hash: {result['replay_hash']}")


if __name__ == "__main__":
    main()
