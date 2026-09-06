#!/usr/bin/env python3
"""Canonical submission assembly entry point."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import pathlib
import subprocess
import sys

# Ensure repository root is on sys.path
root_dir = pathlib.Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.model.predict import (
    InsufficientEligibleGatewaysError,
    ModelArtifactError,
    build_canonical_predictions_bytes,
    compute_v25_replay_hash,
    predict_week,
    resolve_active_model_version,
    write_run_record,
)

SCORED_WEEKS = [dt.date(2026, 2, 2) + dt.timedelta(days=7 * i) for i in range(8)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 8-week challenge submission")
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
    parser.add_argument(
        "--backlog-report",
        type=pathlib.Path,
        default=pathlib.Path("backlog_report.json"),
        help="Output backlog economics JSON report (default: backlog_report.json)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip automatic validate_submission.py invocation",
    )
    parser.add_argument(
        "--run-record",
        type=pathlib.Path,
        default=pathlib.Path("runs/prediction/run.json"),
        help="Output run provenance JSON record (default: runs/prediction/run.json)",
    )
    args = parser.parse_args()

    # Task 11: Validate data directory exists
    if not args.data.exists() or not args.data.is_dir():
        print(f"ERROR: Specified data directory does not exist: {args.data}", file=sys.stderr)
        sys.exit(1)

    all_predictions: list[dict[str, str | int | float]] = []
    all_canonical_inputs: list[bytes] = []
    first_week_backlog = None

    for monday in SCORED_WEEKS:
        try:
            result = predict_week(data_dir=args.data, week_start=monday)
        except (ModelArtifactError, InsufficientEligibleGatewaysError, FileNotFoundError) as exc:
            print(f"ERROR: Inference failed for week {monday}: {exc}", file=sys.stderr)
            sys.exit(1)

        if first_week_backlog is None and "backlog_report" in result:
            first_week_backlog = result["backlog_report"]

        preds = result["predictions"]
        if len(preds) != 15:
            print(f"ERROR: Week {monday} produced {len(preds)} predictions, expected exactly 15", file=sys.stderr)
            sys.exit(1)
        all_predictions.extend(preds)
        all_canonical_inputs.append(result["canonical_input_bytes"])

    output_tmp = args.output.parent / f"{args.output.name}.tmp"
    backlog_tmp = args.backlog_report.parent / f"{args.backlog_report.name}.tmp"
    run_record_tmp = args.run_record.parent / f"{args.run_record.name}.tmp"

    try:
        # 1. Write predictions to temporary staging file
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(output_tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["week_start", "rank", "gateway_id", "score", "reason"])
            for p in all_predictions:
                writer.writerow([
                    p["week_start"],
                    p["rank"],
                    p["gateway_id"],
                    f"{float(p['score']):.6f}",
                    p["reason"],
                ])

        # 2. Run official validator against staged predictions prior to publication
        validator_path = root_dir / "validate_submission.py"
        if not args.skip_validation and validator_path.exists():
            val_res = subprocess.run(
                [sys.executable, str(validator_path), str(output_tmp)],
                capture_output=True,
                text=True,
            )
            if val_res.returncode != 0:
                print(f"ERROR: validate_submission.py rejected staged predictions:", file=sys.stderr)
                print(val_res.stdout, file=sys.stderr)
                print(val_res.stderr, file=sys.stderr)
                if output_tmp.exists():
                    output_tmp.unlink()
                sys.exit(val_res.returncode)
            print("Submission validated successfully by validate_submission.py: PASS")

        # 3. Write backlog report to temporary staging file
        if first_week_backlog is not None:
            import json
            args.backlog_report.parent.mkdir(parents=True, exist_ok=True)
            backlog_tmp.write_text(
                json.dumps(first_week_backlog, indent=2) + "\n", encoding="utf-8"
            )

        # 4. Write run provenance record to temporary staging file
        import datetime as dt
        import hashlib
        pred_bytes = output_tmp.read_bytes()
        predictions_file_hash = f"sha256:{hashlib.sha256(pred_bytes).hexdigest()}"

        all_input_bytes = b"".join(all_canonical_inputs)
        canonical_pred_bytes = build_canonical_predictions_bytes(all_predictions)
        submission_replay_hash = compute_v25_replay_hash(all_input_bytes, canonical_pred_bytes)

        active_ver = resolve_active_model_version()
        timestamp_utc = dt.datetime.now(dt.timezone.utc).isoformat()

        args.run_record.parent.mkdir(parents=True, exist_ok=True)
        write_run_record(
            run_path=run_record_tmp,
            model_version=active_ver,
            replay_hash=submission_replay_hash,
            predictions_file_hash=predictions_file_hash,
            output_file=str(args.output),
            backlog_file=str(args.backlog_report) if first_week_backlog is not None else None,
            data_dir=str(args.data),
            execution_timestamp_utc=timestamp_utc,
        )

        # 5. Atomic Publication: all stages passed, commit staging files into place
        os.replace(output_tmp, args.output)
        print(f"Wrote {args.output} - {len(all_predictions)} rows over {len(SCORED_WEEKS)} weeks")

        if first_week_backlog is not None:
            os.replace(backlog_tmp, args.backlog_report)
            print(f"Backlog report written to {args.backlog_report}")

        os.replace(run_record_tmp, args.run_record)
        if args.run_record.name == "run.json":
            latest_path = args.run_record.parent / "run_latest.json"
            latest_path.write_bytes(args.run_record.read_bytes())
        print(f"Run provenance record written to {args.run_record}")

    except Exception:
        # Clean up any remaining temporary files on failure
        for p in [output_tmp, backlog_tmp, run_record_tmp]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        raise


if __name__ == "__main__":
    main()
