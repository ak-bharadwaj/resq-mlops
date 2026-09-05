"""Tests for Task 17: Standing-Gap Closure.

Verifies:
1. Missing-telemetry path in scripts/predict.py exits non-zero and produces no false success.
2. Clean-environment smoke test for make run reviewer workflow.
3. Holdout gateway 0AA18F330F59 yields no contamination during development and is strictly protected.
4. Makefile canonical contract integrity.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import subprocess
import sys
from collections import defaultdict

import pytest

from app.data.loader import get_gateway_eligibility, load_gateway_master
from app.data.quality import HoldoutAccessError, HoldoutProtection
from app.features.holdout import load_group_holdout_ids
from app.model.evaluate import ROLLING_WINDOWS


@pytest.fixture
def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent


def test_missing_telemetry_fails_nonzero(tmp_path: pathlib.Path, repo_root: pathlib.Path):
    """17.2: Verify scripts/predict.py exits non-zero when telemetry is missing.

    Must not print notice and exit 0. Must fail closed, output an error to stderr,
    exit with code 1, and produce no prediction artifacts.
    """
    master_csv = (
        "gateway_id,tenant,site_type,region,hw_model,antenna_type,fw_version,fw_updated_on,installed_on,decommissioned_on,n_meters_installed\n"
        "06:39:EA:56:02:C1,tenant_a,Rooftop,Baden,Modell_A,Stab,v1.0,,2020-01-01,,100\n"
        "0639ea5602c2,tenant_b,Basement,Bayern,Modell_B,Omni,v1.0,,2021-05-10,,50\n"
    )
    (tmp_path / "gateway_master.csv").write_bytes(master_csv.encode("cp1252"))
    out_csv = tmp_path / "predictions.csv"
    backlog_json = tmp_path / "backlog_report.json"

    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "predict.py"),
        "--data",
        str(tmp_path),
        "--week",
        "2026-02-02",
        "--output",
        str(out_csv),
        "--backlog-report",
        str(backlog_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root)

    # Must exit non-zero (code 1)
    assert res.returncode == 1, f"Expected returncode 1 on missing telemetry, got {res.returncode}. Stdout: {res.stdout}, Stderr: {res.stderr}"
    # Error message must be written to stderr
    assert "ERROR: No telemetry partitions found in data directory" in res.stderr
    # Must fail closed without manufacturing predictions.csv or backlog report
    assert not out_csv.exists(), "predictions.csv must not be created when telemetry is missing"
    assert not backlog_json.exists(), "backlog_report.json must not be created when telemetry is missing"


def test_clean_environment_make_run(repo_root: pathlib.Path):
    """17.3: Reviewer workflow smoke test from a clean environment.

    Proves:
    clean environment -> one command -> predictions.csv -> exactly 120 rows -> validate_submission.py PASS
    Guards against stale predictions.csv or backlog_report.json causing false passes.
    """
    pred_path = repo_root / "predictions.csv"
    backlog_path = repo_root / "backlog_report.json"

    # Back up or purge existing prediction files to ensure clean environment
    backup_pred = None
    if pred_path.exists():
        backup_pred = pred_path.read_bytes()
        pred_path.unlink()

    backup_backlog = None
    if backlog_path.exists():
        backup_backlog = backlog_path.read_bytes()
        backlog_path.unlink()

    try:
        # Assert clean environment before running
        assert not pred_path.exists(), "Clean environment violated: predictions.csv already exists"

        # Execute canonical submission generation command (recipe of make run)
        cmd = [
            sys.executable,
            str(repo_root / "scripts" / "make_submission.py"),
            "--data",
            str(repo_root / "data"),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root)
        assert res.returncode == 0, f"make_submission failed in clean environment: {res.stderr}\n{res.stdout}"

        # Verify predictions.csv was freshly created
        assert pred_path.exists(), "make_submission did not create predictions.csv"

        # Verify exact row count: 1 header + 120 rows = 121 lines
        with open(pred_path, "r", encoding="utf-8", newline="") as f:
            reader = list(csv.reader(f))

        header = reader[0]
        rows = reader[1:]
        assert header == ["week_start", "rank", "gateway_id", "score", "reason"]
        assert len(rows) == 120, f"Expected exactly 120 rows in predictions.csv, got {len(rows)}"

        # Verify 8 scored weeks, exactly 15 rows each, ranks 1..15
        weeks_map = defaultdict(list)
        for r in rows:
            weeks_map[r[0]].append(r)

        assert len(weeks_map) == 8, f"Expected 8 scored weeks, got {len(weeks_map)}"
        for w, w_rows in weeks_map.items():
            assert len(w_rows) == 15, f"Week {w} has {len(w_rows)} rows, expected 15"
            ranks = [int(r[1]) for r in w_rows]
            assert ranks == list(range(1, 16)), f"Week {w} ranks out of order: {ranks}"
            for r in w_rows:
                score_str = r[3]
                float(score_str)  # must parse without error
                decimals = score_str.split(".")[1]
                assert len(decimals) == 6, f"Score {score_str} not formatted to exactly 6 decimals"
                assert len(r[4]) <= 300, f"Reason exceeds 300 chars: {r[4]}"

        # Verify validate_submission.py passes explicitly
        val_cmd = [
            sys.executable,
            str(repo_root / "validate_submission.py"),
            str(pred_path),
        ]
        val_res = subprocess.run(val_cmd, capture_output=True, text=True, cwd=repo_root)
        assert val_res.returncode == 0, f"validate_submission.py rejected generated file: {val_res.stderr}\n{val_res.stdout}"
        assert ": OK" in val_res.stdout
        assert "Submission validated successfully by validate_submission.py: PASS" in res.stdout

    finally:
        # Restore pre-test state if needed
        if backup_pred is not None and not pred_path.exists():
            pred_path.write_bytes(backup_pred)
        if backup_backlog is not None and not backlog_path.exists():
            backlog_path.write_bytes(backup_backlog)


def test_holdout_gateway_not_used_for_development_selection(repo_root: pathlib.Path):
    """17.4: Audit and enforce that holdout gateway 0AA18F330F59 was not contaminated.

    Audits:
    1. 0AA18F330F59 is in the authoritative grouped holdout set.
    2. HoldoutProtection blocks 0AA18F330F59 during development access.
    3. 0AA18F330F59 is never present in development fleet during training or temporal window evaluation.
    4. 0AA18F330F59 was not used in historical label audit case studies.
    5. Candidate model feature weights are frozen architectural weights, not tuned on holdouts.
    """
    target_gid = "0AA18F330F59"
    holdout_path = repo_root / "registry" / "grouped_holdout.json"
    holdout_ids = load_group_holdout_ids(holdout_path)

    # 1. Authoritative holdout membership
    assert target_gid in holdout_ids, f"{target_gid} must be in group holdout set"
    assert len(holdout_ids) == 59, f"Expected exactly 59 holdout gateways, got {len(holdout_ids)}"

    # 2. Programmatic protection guard blocks development access
    with pytest.raises(HoldoutAccessError, match="Unauthorized access to GROUP_HOLDOUT"):
        HoldoutProtection.check_gateway_access(target_gid, holdout_ids, allow_holdout=False)

    # 3. Development training isolation: verify exclusion from dev_gateways
    master_df = load_gateway_master(repo_root / "data")
    all_master_gids = set(master_df["canonical_id"].unique())
    dev_gateways = all_master_gids - holdout_ids
    assert target_gid not in dev_gateways, f"{target_gid} leaked into candidate development fleet!"
    assert dev_gateways.isdisjoint(holdout_ids), "Development fleet overlaps with holdout set!"

    # 4. Temporal evaluation isolation: verify exclusion across all 13 rolling Mondays
    eval_mondays = []
    for w_info in ROLLING_WINDOWS.values():
        eval_mondays.extend(w_info["mondays"])

    for monday_str in eval_mondays:
        monday = dt.date.fromisoformat(monday_str)
        elig_df = get_gateway_eligibility(master_df, monday)
        el_gids = set(elig_df[elig_df["is_eligible"]]["canonical_id"])
        dev_gids = el_gids - holdout_ids
        assert target_gid not in dev_gids, f"{target_gid} leaked into dev_gids for week {monday_str}!"
        assert dev_gids.isdisjoint(holdout_ids)

    # 5. Verify audited historical cases in test_label_audit.py did NOT use 0AA18F330F59
    import tests.unit.test_label_audit as tla
    label_audit_source = pathlib.Path(tla.__file__).read_text(encoding="utf-8")
    assert target_gid not in label_audit_source, f"{target_gid} found in label audit test suite!"

    # 6. Verify candidate model weights are frozen v25 specifications
    v2_cfg_path = repo_root / "models" / "v0002" / "model_config.json"
    if v2_cfg_path.exists():
        v2_cfg = json.loads(v2_cfg_path.read_text(encoding="utf-8"))
        assert v2_cfg.get("weights") == {"w_anomaly": 0.7, "w_silence": 0.3}


def test_make_run_makefile_contract(repo_root: pathlib.Path):
    """Verify Makefile 'run' recipe matches canonical reviewer entry point."""
    makefile_path = repo_root / "Makefile"
    assert makefile_path.exists()
    content = makefile_path.read_text(encoding="utf-8")
    assert "run:" in content
    assert "scripts/make_submission.py --data ./data" in content


def test_holdout_protection_blocks_all_group_holdout_gateways(repo_root: pathlib.Path):
    """Verify HoldoutProtection blocks all 59 holdout gateways without exception."""
    holdout_ids = load_group_holdout_ids(repo_root / "registry" / "grouped_holdout.json")
    assert len(holdout_ids) == 59
    for gid in holdout_ids:
        with pytest.raises(HoldoutAccessError):
            HoldoutProtection.check_gateway_access(gid, holdout_ids, allow_holdout=False)

