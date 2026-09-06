#!/usr/bin/env python3
"""Execute structural schema drift and source completeness monitoring.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 2B, 14, 15, line 25
- Challenge Brief Track F: "Something watching the incoming data that would notice if it changed shape."
- Canonical entry point: python scripts/check_drift.py [--data ./data]
"""
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

from app.data.loader import get_gateway_eligibility, load_gateway_master, load_telemetry_window
from app.data.quality import check_source_completeness
from app.data.schema import TelemetrySchemaContract
from app.model.predict import resolve_active_model_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Run structural schema drift check")
    parser.add_argument(
        "--data",
        type=pathlib.Path,
        default=pathlib.Path("data"),
        help="Path to data directory (default: ./data)",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("monitoring/drift_reports/schema_check.json"),
        help="Path to output drift report JSON (default: monitoring/drift_reports/schema_check.json)",
    )
    parser.add_argument(
        "--week",
        type=str,
        default="2026-02-02",
        help="Reference evaluation Monday (YYYY-MM-DD, default: 2026-02-02)",
    )
    parser.add_argument(
        "--registry",
        type=pathlib.Path,
        default=pathlib.Path("registry/active.json"),
        help="Path to active registry JSON (default: registry/active.json)",
    )
    parser.add_argument(
        "--models-dir",
        type=pathlib.Path,
        default=pathlib.Path("models"),
        help="Path to models directory (default: models)",
    )
    args = parser.parse_args()

    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    active_version = resolve_active_model_version(args.registry)
    schema_contract = TelemetrySchemaContract.load_active_schema(
        models_dir=args.models_dir,
        registry_path=args.registry,
    )

    monday = dt.date.fromisoformat(args.week)
    cutoff_utc = dt.datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=dt.timezone.utc)
    start_utc = cutoff_utc - dt.timedelta(days=28)

    # 1. Load incoming telemetry window
    try:
        telemetry_df = load_telemetry_window(
            args.data,
            cutoff_utc=cutoff_utc,
            start_utc=start_utc,
        )
    except Exception as exc:
        print(f"ERROR: Failed to load incoming telemetry window: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Structural Schema Contract Validation
    valid, errors = schema_contract.validate_dataframe(telemetry_df)

    # 3. Source Completeness Guard Check
    master_df = load_gateway_master(args.data)
    eligibility_df = get_gateway_eligibility(master_df, monday)
    eligible_gateways = set(eligibility_df[eligibility_df["is_eligible"]]["canonical_id"])

    completeness = check_source_completeness(
        telemetry_df,
        eligible_gateways=eligible_gateways,
        start_utc=start_utc,
        cutoff_utc=cutoff_utc,
    )

    status = "PASS" if (valid and completeness.is_safe) else "FAIL"
    if not completeness.is_safe:
        errors.append(
            f"Source completeness guard tripped: fleet absence rate {completeness.absence_rate:.2%} "
            f"exceeds 50.00% threshold"
        )

    # 4. Assemble Monitoring Report
    report = {
        "status": status,
        "active_model_version": active_version,
        "week_checked": args.week,
        "timestamp_utc": "2026-09-05T00:00:00Z",
        "rows_checked": len(telemetry_df),
        "unique_reporting_gateways": int(telemetry_df["canonical_id"].nunique()) if "canonical_id" in telemetry_df.columns else 0,
        "eligible_gateways_count": len(eligible_gateways),
        "fleet_absence_rate": round(float(completeness.absence_rate), 4),
        "source_completeness_safe": bool(completeness.is_safe),
        "schema_validation_passed": bool(valid),
        "required_columns": schema_contract.required_columns,
        "time_grain": schema_contract.time_grain,
        "errors": errors,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # 5. Operations-Manager Summary Output
    print("\n" + "=" * 80)
    print(f"STRUCTURAL SCHEMA MONITORING: ACTIVE MODEL {active_version}")
    print("=" * 80)
    print(f"Data Directory:         {args.data.resolve()}")
    print(f"Reference Monday:       {args.week} (Cutoff: {cutoff_utc.isoformat()})")
    print(f"Required Columns:       {schema_contract.required_columns}")
    print(f"Time Grain:             {schema_contract.time_grain} (strict UTC timezone-aware)")
    print(f"Rows Inspected:         {len(telemetry_df):,}")
    print(f"Reporting Gateways:     {report['unique_reporting_gateways']} of {len(eligible_gateways)} eligible")
    print(f"Fleet Absence Rate:     {completeness.absence_rate:.2%} (Threshold: 50.00%)")
    print(f"Source Completeness:    {'SAFE (OK)' if completeness.is_safe else 'TRIPPED (BLOCK_FEATURES)'}")
    print(f"Structural Schema:      {'PASS' if valid else 'FAIL'}")
    if errors:
        print("\nErrors Detected:")
        for err in errors:
            print(f"  - {err}")
    print(f"Monitoring Report:      {args.output}")
    print("=" * 80 + "\n")

    if status != "PASS":
        print(f"DRIFT ALERT: Incoming data shape validation failed with {len(errors)} error(s).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

