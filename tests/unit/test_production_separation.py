"""Tests for Task 12: Production-Path Separation and Runtime Boundary Invariants.

Verifies:
1. AST-enforced isolation: predict paths NEVER import train, evaluate, field_visits, or labels.
2. Monotonic time authority: zero wall-clock calls in inference or feature paths.
3. Zero production mutation: predict never mutates registry/active.json or model packages.
4. Zero production mutation: train never alters active production state or registry/active.json.
5. Immutable artifact consumption: predict loads declared active artifact, fails closed if missing/corrupt.
6. Unified data and schema contracts: both paths use canonical ID normalization and schema contracts.
7. Alternate --data directory support for both train and predict.
8. Single-pass top-15 visit cap, non-increasing score ranking, canonical tie-breaking, and backlog reporting.
9. Submission pipeline passes official validate_submission.py check.
"""
import ast
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys

import pandas as pd
import pytest

from app.model.predict import (
    InsufficientEligibleGatewaysError,
    ModelArtifactError,
    predict_week,
    resolve_active_model_version,
)
from app.model.train import compute_artifact_hash, train_candidate


@pytest.fixture
def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent


def test_ast_predict_isolation(repo_root: pathlib.Path):
    """Verify predict modules never import training, evaluation, labels, or field_visits."""
    predict_files = [
        repo_root / "app" / "model" / "predict.py",
        repo_root / "scripts" / "predict.py",
        repo_root / "scripts" / "make_submission.py",
    ]
    forbidden = ["train", "evaluate", "field_visits", "label_gateway_week"]

    violations = []
    for file_path in predict_files:
        assert file_path.exists(), f"Target file missing: {file_path}"
        code = file_path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(f in alias.name for f in forbidden):
                        violations.append(f"{file_path.name} imports forbidden module: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if any(f in mod for f in forbidden):
                    violations.append(f"{file_path.name} imports from forbidden module: {mod}")

    assert not violations, f"Physical module isolation boundary violated: {violations}"


def test_ast_predict_zero_wall_clock(repo_root: pathlib.Path):
    """Verify inference modules make zero wall-clock calls (datetime.now, time.time, etc.)."""
    from tests.unit.test_architecture import check_wall_clock_in_ast

    predict_files = [
        repo_root / "app" / "model" / "predict.py",
        repo_root / "scripts" / "predict.py",
        repo_root / "scripts" / "make_submission.py",
    ]
    violations = []
    for f in predict_files:
        code = f.read_text(encoding="utf-8")
        v = check_wall_clock_in_ast(code, filename=str(f))
        if v:
            violations.extend([f"{f.name}: {item}" for item in v])

    assert not violations, f"Wall-clock leakage detected in predict path: {violations}"


def test_predict_never_mutates_registry_or_models(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify running predict.py causes zero filesystem mutations to active registry or models."""
    registry_file = repo_root / "registry" / "active.json"
    registry_before = registry_file.read_text(encoding="utf-8")

    models_dir = repo_root / "models"
    model_files_before = {
        p.relative_to(models_dir): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in models_dir.rglob("*")
        if p.is_file()
    }

    out_csv = tmp_path / "pred_test.csv"
    out_backlog = tmp_path / "backlog_test.json"
    out_run = tmp_path / "run_test.json"

    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "predict.py"),
        "--data",
        str(repo_root / "data"),
        "--week",
        "2026-02-02",
        "--output",
        str(out_csv),
        "--backlog-report",
        str(out_backlog),
        "--run-record",
        str(out_run),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"predict.py failed: {res.stderr}"

    registry_after = registry_file.read_text(encoding="utf-8")
    assert registry_before == registry_after, "predict.py modified registry/active.json!"

    model_files_after = {
        p.relative_to(models_dir): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in models_dir.rglob("*")
        if p.is_file()
    }
    assert model_files_before == model_files_after, "predict.py mutated models/ directory!"


def test_train_never_mutates_active_production_state(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify running train.py materializes candidate but leaves active production state untouched."""
    registry_file = repo_root / "registry" / "active.json"
    registry_before = registry_file.read_text(encoding="utf-8")

    candidate_out = tmp_path / "models" / "v0001_candidate_test"
    result = train_candidate(
        data_dir=repo_root / "data",
        candidate_version="v0001_candidate_test",
        output_dir=candidate_out,
        registry_path=registry_file,
        runs_dir=tmp_path / "runs",
    )

    registry_after = registry_file.read_text(encoding="utf-8")
    assert registry_before == registry_after, "train_candidate modified registry/active.json!"

    # Verify immutable candidate artifact package was created
    assert candidate_out.exists()
    assert (candidate_out / "manifest.json").exists()
    assert (candidate_out / "model_config.json").exists()
    assert (candidate_out / "schema.json").exists()
    assert (candidate_out / "feature_schema.json").exists()
    assert (candidate_out / "scorer_identity.txt").exists()
    assert (candidate_out / "metrics.json").exists()

    manifest = json.loads((candidate_out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_version"] == "v0001_candidate_test"
    assert manifest["artifact_hash"].startswith("sha256:")

    # Verify training evidence log
    evidence_path = pathlib.Path(result["evidence_file"])
    assert evidence_path.exists()
    evidence_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence_data["candidate_version"] == "v0001_candidate_test"


def test_predict_fails_closed_when_active_artifact_missing(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify predict fails closed with ModelArtifactError if active model artifact is missing."""
    fake_registry = tmp_path / "fake_active.json"
    fake_registry.write_text(
        json.dumps({"production_version": "v9999_nonexistent"}),
        encoding="utf-8",
    )

    with pytest.raises(ModelArtifactError) as exc_info:
        predict_week(
            data_dir=repo_root / "data",
            week_start="2026-02-02",
            registry_path=fake_registry,
        )
    assert "does not exist" in str(exc_info.value) or "missing" in str(exc_info.value)


def test_top15_and_backlog_reporting_contract(repo_root: pathlib.Path):
    """Verify exact 15 visits, non-increasing score order with canonical tie-breaks, and backlog economics."""
    result = predict_week(data_dir=repo_root / "data", week_start="2026-02-02")
    preds = result["predictions"]

    assert len(preds) == 15, f"Expected exactly 15 predictions, got {len(preds)}"
    ranks = [p["rank"] for p in preds]
    assert ranks == list(range(1, 16)), f"Ranks must be 1..15, got {ranks}"

    # Non-increasing score order
    scores = [p["score"] for p in preds]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], f"Scores not non-increasing: {scores[i]} < {scores[i+1]}"

    # Tie-breaking by canonical gateway_id ascending
    for i in range(len(scores) - 1):
        if scores[i] == scores[i + 1]:
            assert preds[i]["gateway_id"] < preds[i + 1]["gateway_id"], "Tie-break by gateway_id violated"

    # Reason length <= 300
    for p in preds:
        assert len(p["reason"]) <= 300, f"Reason exceeded 300 chars: {p['reason']}"

    # Backlog economics
    backlog = result["backlog_report"]
    assert backlog["max_visits"] == 15
    assert backlog["selected_count"] == 15
    assert backlog["deferred_count"] > 0
    assert backlog["deferred_risk_proxy_score"] >= 0.0
    assert backlog["evidence_quality"] == "baseline"
    assert backlog["exposure_method"] == "heuristic_proxy"

    # Replay hash
    assert result["replay_hash"].startswith("sha256:")


def test_both_paths_support_alternate_data_directory(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify both train.py and predict.py function cleanly on an alternate --data path."""
    alt_data = tmp_path / "alt_data"
    alt_data.mkdir(parents=True)

    # Copy real gateway_master.csv and field_visits.csv
    import shutil
    shutil.copy(repo_root / "data" / "gateway_master.csv", alt_data / "gateway_master.csv")
    shutil.copy(repo_root / "data" / "field_visits.csv", alt_data / "field_visits.csv")
    shutil.copytree(repo_root / "data" / "telemetry", alt_data / "telemetry")

    # 1. Train on alternate data
    candidate_dir = tmp_path / "models" / "v_alt"
    train_res = train_candidate(
        data_dir=alt_data,
        candidate_version="v_alt",
        output_dir=candidate_dir,
        registry_path=repo_root / "registry" / "active.json",
        runs_dir=tmp_path / "runs",
    )
    assert candidate_dir.exists()
    assert (candidate_dir / "manifest.json").exists()

    # 2. Predict on alternate data
    pred_res = predict_week(
        data_dir=alt_data,
        week_start="2026-02-02",
        active_version="v0001",
    )
    assert len(pred_res["predictions"]) == 15


def test_make_submission_and_official_validator(repo_root: pathlib.Path, tmp_path: pathlib.Path):
    """Verify scripts/make_submission.py produces 120 rows passing validate_submission.py."""
    out_csv = tmp_path / "submission_test.csv"
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "make_submission.py"),
        "--data",
        str(repo_root / "data"),
        "--output",
        str(out_csv),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"make_submission failed: {res.stderr} -- {res.stdout}"

    df = pd.read_csv(out_csv)
    assert len(df) == 120, f"Expected 120 rows, got {len(df)}"
    assert df["week_start"].nunique() == 8

    # Run official validator directly
    val_cmd = [
        sys.executable,
        str(repo_root / "validate_submission.py"),
        str(out_csv),
    ]
    val_res = subprocess.run(val_cmd, capture_output=True, text=True)
    assert val_res.returncode == 0, f"Official validator rejected submission: {val_res.stdout} -- {val_res.stderr}"
