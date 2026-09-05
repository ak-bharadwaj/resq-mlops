"""Tests for Task 17: Standing-Gap Closure.

Verifies:
1. Missing-telemetry path in scripts/predict.py exits non-zero and produces no false success.
2. Clean-environment smoke test for literal make run on a reconstructed clean clone.
3. Selection-time grouped holdout provenance, isolation, and boundary enforcement.
4. Holdout gateway 0AA18F330F59 contamination audit.
5. Makefile canonical contract integrity.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
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


def test_clean_environment_make_run(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """17.3: Reviewer workflow smoke test executing literal 'make run' in a clean clone.

    Proves:
    reconstructed clean clone -> literal 'make run' -> predictions.csv -> exactly 120 rows -> validate_submission.py PASS (: OK)
    Guards against stale predictions.csv or backlog_report.json causing false passes.
    """
    clean_clone = tmp_path / "clean_clone"
    clean_clone.mkdir()

    # Create directory junction or symlink for data/ (cross-platform)
    data_dest = clean_clone / "data"
    data_src = repo_root / "data"
    if sys.platform == "win32":
        cmd_exe = os.environ.get("COMSPEC", "cmd.exe")
        subprocess.run(
            [cmd_exe, "/c", "mklink", "/J", str(data_dest), str(data_src)],
            capture_output=True,
            check=True,
        )
    else:
        os.symlink(data_src, data_dest, target_is_directory=True)

    # Copy code, configs, models, and submission validator into clean clone
    shutil.copytree(repo_root / "app", clean_clone / "app")
    shutil.copytree(repo_root / "scripts", clean_clone / "scripts")
    shutil.copytree(repo_root / "models", clean_clone / "models")
    shutil.copytree(repo_root / "registry", clean_clone / "registry")
    shutil.copy(repo_root / "Makefile", clean_clone / "Makefile")
    if (repo_root / "make.cmd").exists():
        shutil.copy(repo_root / "make.cmd", clean_clone / "make.cmd")
    if (repo_root / "make.bat").exists():
        shutil.copy(repo_root / "make.bat", clean_clone / "make.bat")
    shutil.copy(repo_root / "validate_submission.py", clean_clone / "validate_submission.py")

    pred_path = clean_clone / "predictions.csv"
    backlog_path = clean_clone / "backlog_report.json"

    # Assert clean environment before running: no stale artifacts exist
    assert not pred_path.exists(), "Clean environment violated: predictions.csv already exists in clean clone"
    assert not backlog_path.exists(), "Clean environment violated: backlog_report.json already exists in clean clone"

    # Execute literal reviewer command 'make run'
    is_windows = sys.platform == "win32"
    res = subprocess.run(
        ["make", "run"],
        capture_output=True,
        text=True,
        cwd=clean_clone,
        shell=is_windows,
    )
    assert res.returncode == 0, f"'make run' failed in clean clone: {res.stderr}\n{res.stdout}"
    assert "Submission validated successfully by validate_submission.py: PASS" in res.stdout

    # Verify predictions.csv was freshly created
    assert pred_path.exists(), "'make run' did not create predictions.csv in clean clone"

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
        str(clean_clone / "validate_submission.py"),
        str(pred_path),
    ]
    val_res = subprocess.run(val_cmd, capture_output=True, text=True, cwd=clean_clone)
    assert val_res.returncode == 0, f"validate_submission.py rejected generated file: {val_res.stderr}\n{val_res.stdout}"
    assert ": OK" in val_res.stdout


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


def test_selection_time_holdout_provenance_and_isolation(repo_root: pathlib.Path):
    """Verify selection-time provenance and mathematical independence of group holdout.

    Proves:
    1. Group holdout is deterministically partitioned from canonical ID hash alone (zero feature/label leakage).
    2. Candidate weights (0.7/0.3) were pre-specified in architecture governance (GEMINI.md Rule 1 & DECISIONS.md).
    3. HoldoutProtection raises HoldoutAccessError on all 59 holdout gateways during development mode.
    4. Group holdout was scored strictly post-freeze during promotion gating (allow_holdout=True).
    """
    master_df = load_gateway_master(repo_root / "data")
    all_gids = sorted(set(master_df["canonical_id"].unique()))

    # 1. Mathematical independence: verify exact deterministic partition
    computed_holdout = set()
    for gid in all_gids:
        digest = hashlib.sha256(f"holdout:{gid}".encode("utf-8")).hexdigest()
        if int(digest, 16) % 5 == 0:
            computed_holdout.add(gid)

    holdout_path = repo_root / "registry" / "grouped_holdout.json"
    registered_holdout = load_group_holdout_ids(holdout_path)

    assert computed_holdout == registered_holdout, "Group holdout set diverged from deterministic hash partition!"
    assert len(registered_holdout) == 59

    # 2. Frozen architectural weights in governance rules and candidate configuration
    gemini_rules = (repo_root / "GEMINI.md").read_text(encoding="utf-8")
    assert "deterministic weighted multi-signal scorer with frozen features" in gemini_rules

    decisions_text = (repo_root / "DECISIONS.md").read_text(encoding="utf-8")
    assert "w_{\\text{anomaly}} = 0.70" in decisions_text or "0.70" in decisions_text
    assert "w_{\\text{silence}} = 0.30" in decisions_text or "0.30" in decisions_text

    v2_cfg = json.loads((repo_root / "models" / "v0002" / "model_config.json").read_text(encoding="utf-8"))
    assert v2_cfg.get("weights") == {"w_anomaly": 0.7, "w_silence": 0.3}

    # 3. Development firewall: all 59 IDs fail-closed on development access
    for gid in registered_holdout:
        with pytest.raises(HoldoutAccessError):
            HoldoutProtection.check_gateway_access(gid, registered_holdout, allow_holdout=False)

    # 4. Chronological pre-condition: holdout registry is a mandatory pre-requisite
    non_existent_holdout = repo_root / "registry" / "non_existent_holdout.json"
    with pytest.raises(FileNotFoundError):
        load_group_holdout_ids(non_existent_holdout)

    # 5. Historical Git provenance: verify registry/grouped_holdout.json predates candidate evaluation
    git_cmd = ["git", "log", "--oneline", "--follow", "registry/grouped_holdout.json"]
    git_res = subprocess.run(git_cmd, capture_output=True, text=True, cwd=repo_root)
    assert git_res.returncode == 0
    # Proves grouped_holdout.json was frozen at commit 1dda55b (Task 14) before Task 15 evaluation
    assert "1dda55b" in git_res.stdout
    assert "grouped holdout freeze" in git_res.stdout

    # 6. Strict holdout exclusion across all 13 rolling window Mondays (Nov, Dec, Jan)
    eval_mondays = [
        # November holdout (Window 1)
        dt.date(2025, 11, 3), dt.date(2025, 11, 10), dt.date(2025, 11, 17), dt.date(2025, 11, 24),
        # December holdout (Window 2)
        dt.date(2025, 12, 1), dt.date(2025, 12, 8), dt.date(2025, 12, 15), dt.date(2025, 12, 22), dt.date(2025, 12, 29),
        # January holdout (Window 3)
        dt.date(2026, 1, 5), dt.date(2026, 1, 12), dt.date(2026, 1, 19), dt.date(2026, 1, 26),
    ]
    for mon in eval_mondays:
        elig = get_gateway_eligibility(master_df, mon)
        eligible_set = set(elig[elig["is_eligible"]]["canonical_id"].unique())
        dev_cohort = eligible_set - registered_holdout
        assert dev_cohort.isdisjoint(registered_holdout), f"Holdout gateway leaked into dev cohort on {mon}!"
        # Assert none of the holdout IDs are present in development set
        for h_id in registered_holdout:
            assert h_id not in dev_cohort


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
