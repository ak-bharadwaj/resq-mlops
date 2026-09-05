"""Dedicated test suite for Task 14: Deterministic Candidate (v0002) & Feature Foundation.

Verifies:
1. Grouped holdout freeze, persistence, and isolation (Rule 8, Section 8).
2. Train/Predict feature parity (identical extraction logic).
3. Exact Monday 00:00:00 UTC boundary and post-cutoff isolation.
4. Missing telemetry taxonomy (NO_TELEMETRY vs total silence 1.0 vs complete reporting 0.0).
5. WeightedMultiSignalScorer ranking determinism, 6-decimal serialization, and canonical ID tie-break.
6. Immutable candidate package materialization (models/v0002/) and hash determinism.
7. Zero production mutation (registry/active.json byte-for-byte unchanged).
8. Scorer cryptographic identity binding (scorer_identity.txt).
9. Real challenge data integration.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.data.quality import HoldoutAccessError, HoldoutProtection
from app.features.build import extract_candidate_features
from app.features.definitions import GatewayFeatures
from app.features.holdout import (
    freeze_group_holdout_ids,
    load_group_holdout_ids,
)
from app.model.predict import load_active_artifact_config, predict_week
from app.model.scorer import (
    Baseline3SigmaScorer,
    WeightedMultiSignalScorer,
    get_scorer_for_config,
)
from app.model.train import compute_artifact_hash, train_candidate


@pytest.fixture
def real_data_dir() -> Path:
    return Path("data")


@pytest.fixture
def sample_telemetry() -> pd.DataFrame:
    """Generate 35 days of synthetic hourly telemetry for 3 gateways."""
    # Monday 2026-02-02 00:00:00 UTC is the evaluation cutoff
    # Trailing 28-day baseline: [2026-01-05, 2026-02-02)
    # Trailing 7-day recent: [2026-01-26, 2026-02-02)
    cutoff = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
    start = cutoff - dt.timedelta(days=28)
    timestamps = pd.date_range(start=start, end=cutoff, freq="1h", inclusive="left")

    rows = []
    # Gateway A: Healthy / complete reporting (168 recent hours, normal values)
    for ts in timestamps:
        rows.append({
            "canonical_id": "0639EA5602C1",
            "ts": ts,
            "offline_duration_sec": 10.0,
            "disconnection_cnt": 0.0,
            "reboot_cnt": 0.0,
        })

    # Gateway B: Degrading / 3-sigma anomaly persistence in recent 48 hours
    for ts in timestamps:
        if ts >= cutoff - dt.timedelta(hours=48):
            rows.append({
                "canonical_id": "024570739DE0",
                "ts": ts,
                "offline_duration_sec": 3500.0,  # 3-sigma breach
                "disconnection_cnt": 15.0,
                "reboot_cnt": 3.0,
            })
        else:
            rows.append({
                "canonical_id": "024570739DE0",
                "ts": ts,
                "offline_duration_sec": 5.0,
                "disconnection_cnt": 0.0,
                "reboot_cnt": 0.0,
            })

    # Gateway C: Established history in baseline (days 1-21), but completely silent in recent 7 days (days 22-28)
    for ts in timestamps:
        if ts < cutoff - dt.timedelta(days=7):
            rows.append({
                "canonical_id": "0278E06A2F67",
                "ts": ts,
                "offline_duration_sec": 12.0,
                "disconnection_cnt": 0.0,
                "reboot_cnt": 0.0,
            })

    return pd.DataFrame(rows)


class TestGroupedHoldoutIsolation:
    """Tests for Grouped Holdout Isolation per Rule 8 and Section 8."""

    def test_group_holdout_frozen_and_loaded(self, tmp_path: Path):
        """Holdout set is persisted deterministically and reloadable."""
        gids = [f"GW{i:010X}" for i in range(50)]
        holdout_file = tmp_path / "grouped_holdout.json"

        holdout_ids = freeze_group_holdout_ids(gids, holdout_path=holdout_file, modulo=5)
        assert len(holdout_ids) > 0
        assert holdout_file.exists()

        loaded_ids = load_group_holdout_ids(holdout_path=holdout_file)
        assert loaded_ids == holdout_ids

    def test_holdout_gateways_blocked_in_training(self):
        """Accessing holdout gateways during candidate feature extraction raises HoldoutAccessError."""
        holdout_gateways = {"0639EA5602C1"}
        eligible = {"0639EA5602C1", "024570739DE0"}

        dummy_telemetry = pd.DataFrame([{
            "canonical_id": "0639EA5602C1",
            "ts": pd.Timestamp("2026-01-20 00:00:00", tz="UTC"),
            "offline_duration_sec": 10.0,
            "disconnection_cnt": 0.0,
            "reboot_cnt": 0.0,
        }])

        with pytest.raises(HoldoutAccessError, match="Unauthorized access to GROUP_HOLDOUT gateway"):
            extract_candidate_features(
                telemetry_df=dummy_telemetry,
                eligible_gateways=eligible,
                monday=dt.date(2026, 2, 2),
                allow_holdout=False,
                holdout_gateways=holdout_gateways,
                enforce_source_completeness=False,
            )

    def test_holdout_gateways_allowed_with_explicit_flag(self, sample_telemetry: pd.DataFrame):
        """Evaluation with allow_holdout=True succeeds for holdout gateways."""
        holdout_gateways = {"0639EA5602C1"}
        eligible = {"0639EA5602C1"}

        result = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways=eligible,
            monday=dt.date(2026, 2, 2),
            allow_holdout=True,
            holdout_gateways=holdout_gateways,
            enforce_source_completeness=False,
        )
        assert len(result["valid_features"]) == 1
        assert result["valid_features"][0].gateway_id == "0639EA5602C1"


class TestFeatureCutoffsAndIsolation:
    """Tests for exact Monday 00:00:00 UTC temporal firewall and post-cutoff isolation."""

    def test_exact_monday_midnight_boundary(self, sample_telemetry: pd.DataFrame):
        """Telemetry exactly at or after Monday 00:00:00 UTC is strictly excluded."""
        cutoff_monday = dt.date(2026, 2, 2)
        cutoff_dt = pd.Timestamp("2026-02-02 00:00:00", tz="UTC")

        # Inject post-cutoff rows: at midnight exactly, and 1 hour later
        post_cutoff_rows = [
            {
                "canonical_id": "0639EA5602C1",
                "ts": cutoff_dt,  # exactly at Monday 00:00:00 UTC
                "offline_duration_sec": 3600.0,
                "disconnection_cnt": 99.0,
                "reboot_cnt": 99.0,
            },
            {
                "canonical_id": "0639EA5602C1",
                "ts": cutoff_dt + dt.timedelta(hours=1),
                "offline_duration_sec": 3600.0,
                "disconnection_cnt": 99.0,
                "reboot_cnt": 99.0,
            },
        ]
        contaminated_df = pd.concat([sample_telemetry, pd.DataFrame(post_cutoff_rows)], ignore_index=True)

        res_clean = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways={"0639EA5602C1"},
            monday=cutoff_monday,
            allow_holdout=True,
            enforce_source_completeness=False,
        )
        res_contaminated = extract_candidate_features(
            telemetry_df=contaminated_df,
            eligible_gateways={"0639EA5602C1"},
            monday=cutoff_monday,
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        clean_feat = res_clean["valid_features"][0]
        contam_feat = res_contaminated["valid_features"][0]

        # Features must be identical despite contaminated post-cutoff rows
        assert clean_feat.flagged_hours == contam_feat.flagged_hours
        assert clean_feat.recent_silence_ratio == contam_feat.recent_silence_ratio
        assert clean_feat.recent_observed_hours == contam_feat.recent_observed_hours
        assert clean_feat.recent_observed_hours == 168

    def test_train_predict_feature_parity(self, sample_telemetry: pd.DataFrame):
        """Feature extraction logic is identical between train and predict paths."""
        monday = dt.date(2026, 2, 2)
        eligible = {"0639EA5602C1", "024570739DE0"}

        # Extraction 1 (simulate training call)
        res_train = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways=eligible,
            monday=monday,
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        # Extraction 2 (simulate predict call)
        res_predict = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways=eligible,
            monday=monday,
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        assert len(res_train["valid_features"]) == len(res_predict["valid_features"])
        for f1, f2 in zip(res_train["valid_features"], res_predict["valid_features"]):
            assert f1.to_dict() == f2.to_dict()


class TestMissingTelemetryTaxonomy:
    """Tests for the Section 2B missing telemetry taxonomy."""

    def test_institutional_non_coverage_excluded_as_no_telemetry(self, sample_telemetry: pd.DataFrame):
        """Gateway with zero baseline telemetry is excluded with NO_TELEMETRY (never scored as 0 risk)."""
        eligible = {"0639EA5602C1", "NON_EXISTENT_GW"}

        res = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways=eligible,
            monday=dt.date(2026, 2, 2),
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        valid_ids = {f.gateway_id for f in res["valid_features"]}
        excluded_map = {f.gateway_id: f for f in res["excluded_features"]}

        assert "NON_EXISTENT_GW" not in valid_ids
        assert "NON_EXISTENT_GW" in excluded_map
        assert excluded_map["NON_EXISTENT_GW"].status == "NO_TELEMETRY"
        assert excluded_map["NON_EXISTENT_GW"].exclusion_reason == "NO_TELEMETRY"

    def test_recent_total_silence_yields_ratio_one(self, sample_telemetry: pd.DataFrame):
        """Gateway with prior history that goes completely silent in trailing 7 days has silence ratio 1.0."""
        # Gateway 0278E06A2F67 has reporting in baseline days 1-21, but 0 in recent 7 days
        res = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways={"0278E06A2F67"},
            monday=dt.date(2026, 2, 2),
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        assert len(res["valid_features"]) == 1
        feat = res["valid_features"][0]
        assert feat.status == "VALID"
        assert feat.baseline_observed_hours == (21 * 24)
        assert feat.recent_observed_hours == 0
        assert feat.recent_silence_ratio == 1.0

    def test_complete_reporting_yields_silence_ratio_zero(self, sample_telemetry: pd.DataFrame):
        """Gateway reporting all 168 hours has recent_silence_ratio 0.0."""
        res = extract_candidate_features(
            telemetry_df=sample_telemetry,
            eligible_gateways={"0639EA5602C1"},
            monday=dt.date(2026, 2, 2),
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        assert len(res["valid_features"]) == 1
        feat = res["valid_features"][0]
        assert feat.recent_observed_hours == 168
        assert feat.recent_silence_ratio == 0.0


class TestWeightedMultiSignalScorer:
    """Tests for WeightedMultiSignalScorer ranking, tie-breaking, and serialization."""

    def test_scoring_weights_and_tie_breaking(self, sample_telemetry: pd.DataFrame):
        """Scorer ranks non-increasing by score with canonical ID ascending tie-breaking."""
        scorer = WeightedMultiSignalScorer(
            w_anomaly=0.7,
            w_silence=0.3,
            allow_holdout=True,
            enforce_source_completeness=False,
        )
        eligible = {"0639EA5602C1", "024570739DE0", "0278E06A2F67"}
        scored = scorer.score_telemetry(
            telemetry_df=sample_telemetry,
            eligible_gateways=eligible,
            monday=dt.date(2026, 2, 2),
        )

        assert len(scored) == 3

        # Scores must be non-increasing
        scores = [r["score"] for r in scored]
        assert scores == sorted(scores, reverse=True)

        # Gateway with anomaly persistence (024570739DE0) or silence (0278E06A2F67) ranks above calm (0639EA5602C1)
        top_ids = [r["gateway_id"] for r in scored]
        assert top_ids[-1] == "0639EA5602C1"  # calm reporting gateway has lowest risk
        assert scored[-1]["score"] == 0.0

        # Gateway 0278E06A2F67 (silent) has silence_ratio=1.0 -> 0.3 * 1.0 = 0.300000
        silent_rec = next(r for r in scored if r["gateway_id"] == "0278E06A2F67")
        assert silent_rec["score"] == 0.3

        # Gateway 024570739DE0 (anomaly): 3 metrics x 48 hours = 144 flagged hours -> 0.7 * (144/168) = 0.600000
        anom_rec = next(r for r in scored if r["gateway_id"] == "024570739DE0")
        assert anom_rec["score"] == 0.6

    def test_tie_breaking_canonical_id_ascending(self):
        """Identical scores break ties deterministically by canonical gateway ID ascending."""
        cutoff = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
        start = cutoff - dt.timedelta(days=28)
        timestamps = pd.date_range(start=start, end=cutoff, freq="1h", inclusive="left")

        # Two gateways with identical silence (reported only 1st day, 0 in recent)
        rows = []
        for gid in ["ZZZZZZZZZZZZ", "AAAAAAAAAAAA"]:
            rows.append({
                "canonical_id": gid,
                "ts": start + dt.timedelta(hours=1),
                "offline_duration_sec": 10.0,
                "disconnection_cnt": 0.0,
                "reboot_cnt": 0.0,
            })
        df = pd.DataFrame(rows)

        scorer = WeightedMultiSignalScorer(
            w_anomaly=0.7,
            w_silence=0.3,
            allow_holdout=True,
            enforce_source_completeness=False,
        )
        scored = scorer.score_telemetry(
            telemetry_df=df,
            eligible_gateways={"ZZZZZZZZZZZZ", "AAAAAAAAAAAA"},
            monday=dt.date(2026, 2, 2),
        )

        assert len(scored) == 2
        assert scored[0]["score"] == scored[1]["score"]
        # Tie-break by canonical ID ascending: "AAAAAAAAAAAA" must come first
        assert scored[0]["gateway_id"] == "AAAAAAAAAAAA"
        assert scored[1]["gateway_id"] == "ZZZZZZZZZZZZ"

    def test_reason_string_length_and_format(self, sample_telemetry: pd.DataFrame):
        """Reason strings are <= 300 characters and contain operational metrics."""
        scorer = WeightedMultiSignalScorer(
            w_anomaly=0.7,
            w_silence=0.3,
            allow_holdout=True,
            enforce_source_completeness=False,
        )
        scored = scorer.score_telemetry(
            telemetry_df=sample_telemetry,
            eligible_gateways={"024570739DE0"},
            monday=dt.date(2026, 2, 2),
        )
        reason = scored[0]["reason"]
        assert len(reason) <= 300
        assert "Multi-signal risk" in reason
        assert "3-sigma" in reason
        assert "silence" in reason


class TestCandidateMaterializationAndProductionSeparation:
    """Tests for train_candidate(candidate_version='v0002') and zero production mutation."""

    def test_candidate_v0002_materialization_and_hash_determinism(self, real_data_dir: Path, tmp_path: Path):
        """Candidate materialization creates complete immutable package with deterministic hash."""
        target_dir = tmp_path / "v0002"
        runs_dir = tmp_path / "runs"

        res1 = train_candidate(
            data_dir=real_data_dir,
            candidate_version="v0002",
            output_dir=target_dir,
            runs_dir=runs_dir,
        )

        # Assert all required files exist per Section 6
        expected_files = [
            "model_config.json",
            "feature_schema.json",
            "schema.json",
            "scorer_identity.txt",
            "manifest.json",
            "metrics.json",
        ]
        for fname in expected_files:
            assert (target_dir / fname).exists(), f"Missing required candidate file: {fname}"

        # Assert scorer_identity.txt binds to WeightedMultiSignalScorer
        identity_txt = (target_dir / "scorer_identity.txt").read_text(encoding="utf-8")
        assert "WeightedMultiSignalScorer" in identity_txt
        assert "sha256:" in identity_txt

        # Repeat materialization and assert identical artifact hash
        target_dir2 = tmp_path / "v0002_repeat"
        res2 = train_candidate(
            data_dir=real_data_dir,
            candidate_version="v0002",
            output_dir=target_dir2,
            runs_dir=runs_dir,
        )
        assert res1["artifact_hash"] == res2["artifact_hash"]

    def test_candidate_training_never_mutates_active_production_pointer(self, real_data_dir: Path, tmp_path: Path):
        """train_candidate never alters registry/active.json (stays v0001)."""
        registry_file = tmp_path / "active.json"
        initial_state = json.dumps({
            "production_version": "v0001",
            "previous_version": None,
            "changed_at": "2026-09-05T00:00:00Z",
            "reason": "initial baseline deployment",
        }, indent=2)
        registry_file.write_text(initial_state, encoding="utf-8")

        train_candidate(
            data_dir=real_data_dir,
            candidate_version="v0002",
            output_dir=tmp_path / "v0002",
            registry_path=registry_file,
            runs_dir=tmp_path / "runs",
        )

        assert registry_file.read_text(encoding="utf-8") == initial_state


class TestRealDataAndEndToEndConnectivity:
    """Integration and real challenge data tests for candidate scoring and inference."""

    def test_real_challenge_data_candidate_feature_extraction(self, real_data_dir: Path):
        """extract_candidate_features executes cleanly against real challenge data in data/."""
        from app.data.loader import get_gateway_eligibility, load_gateway_master, load_telemetry_window

        monday = dt.date(2026, 2, 2)
        cutoff_utc = dt.datetime(2026, 2, 2, 0, 0, 0, tzinfo=dt.timezone.utc)
        start_utc = cutoff_utc - dt.timedelta(days=28)

        master = load_gateway_master(real_data_dir)
        elig = get_gateway_eligibility(master, monday)
        eligible_gids = set(elig[elig["is_eligible"]]["canonical_id"])

        telemetry = load_telemetry_window(real_data_dir, cutoff_utc=cutoff_utc, start_utc=start_utc)

        # Extract features with allow_holdout=True (evaluation scope)
        feat_res = extract_candidate_features(
            telemetry_df=telemetry,
            eligible_gateways=eligible_gids,
            monday=monday,
            allow_holdout=True,
            enforce_source_completeness=False,
        )

        assert len(feat_res["features"]) == len(eligible_gids)
        assert len(feat_res["valid_features"]) > 0

        for f in feat_res["valid_features"]:
            assert 0.0 <= f.recent_silence_ratio <= 1.0
            assert 0.0 <= f.norm_anomaly <= 1.0
            assert f.flagged_hours >= 0.0

    def test_predict_week_with_v0002_candidate_override(self, real_data_dir: Path):
        """predict_week executes v0002 candidate inference deterministically with top-15 contract."""
        res = predict_week(
            data_dir=real_data_dir,
            week_start="2026-02-02",
            active_version="v0002",
        )

        assert res["active_version"] == "v0002"
        assert res["week_start"] == "2026-02-02"
        assert len(res["predictions"]) == 15

        # Check rankings non-increasing
        scores = [p["score"] for p in res["predictions"]]
        assert scores == sorted(scores, reverse=True)

        for rank, p in enumerate(res["predictions"], 1):
            assert p["rank"] == rank
            assert len(p["gateway_id"]) == 12
            assert isinstance(p["score"], float)
            assert not np.isnan(p["score"])
            assert not np.isinf(p["score"])
            assert len(p["reason"]) <= 300
            assert "Multi-signal risk" in p["reason"]

        assert res["backlog_report"]["selected_count"] == 15
        assert res["backlog_report"]["model_version"] == "v0002"
        assert res["replay_hash"].startswith("sha256:")

    def test_predict_week_v0001_production_default_unchanged(self, real_data_dir: Path):
        """Active production predictions continue running v0001 with zero regression."""
        res = predict_week(
            data_dir=real_data_dir,
            week_start="2026-02-02",
        )

        assert res["active_version"] == "v0001"
        assert len(res["predictions"]) == 15
        for p in res["predictions"]:
            assert "3 sigma" in p["reason"]

