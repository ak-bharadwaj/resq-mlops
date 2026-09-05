"""Tests for Task 13: Label audit, evaluation target, and failure proxy definition.

Frozen Architecture References:
- docs/ARCHITECTURE_v25_FREEZE.md: Sections 2, 2C, 2D, 2E, 8.
- GEMINI.md: Rules 1, 2, 3, 4, 5, 8.
"""
import ast
import datetime as dt
from pathlib import Path
import pandas as pd
import pytest

from app.data.loader import (
    load_field_visits,
    load_gateway_master,
    load_engineer_review,
    get_gateway_eligibility,
)
from app.data.quality import (
    HoldoutProtection,
    HoldoutAccessError,
    DevelopmentFirewallError,
)
from app.model.evaluate import (
    GatewayWeekLabel,
    EvidenceQuality,
    EvaluationMode,
    LabelSpecV1,
    CohortLabelSummary,
    label_gateway_week,
    label_cohort,
)


@pytest.fixture
def real_data_dir() -> Path:
    return Path("data")


@pytest.fixture
def default_label_spec() -> LabelSpecV1:
    return LabelSpecV1()


class TestLabelContractBasics:
    """Test pure deterministic function signature and outputs."""

    def test_pure_deterministic_outputs(self, default_label_spec: LabelSpecV1):
        """label_gateway_week must be pure, deterministic, and return only valid enum members."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2025, 10, 1),
                "visited_on": dt.date(2025, 10, 15),
                "outcome": "Fehler behoben",
            }
        ])

        week_start = dt.date(2025, 10, 6)
        f_cutoff = dt.datetime(2025, 10, 6, 0, 0, 0, tzinfo=dt.timezone.utc)
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        res1 = label_gateway_week("0123456789AB", week_start, f_cutoff, obs_win, default_label_spec, visits_df)
        res2 = label_gateway_week("0123456789AB", week_start, f_cutoff, obs_win, default_label_spec, visits_df)

        assert res1 == GatewayWeekLabel.BROKEN
        assert res2 == GatewayWeekLabel.BROKEN
        assert isinstance(res1, GatewayWeekLabel)

    def test_strict_feature_cutoff_invariant(self, default_label_spec: LabelSpecV1):
        """feature_cutoff must strictly match Monday 00:00:00 UTC."""
        visits_df = pd.DataFrame()
        week_start = dt.date(2025, 10, 6)
        # Invalid time: 00:01:00 UTC instead of 00:00:00
        bad_f_cutoff = dt.datetime(2025, 10, 6, 0, 1, 0, tzinfo=dt.timezone.utc)
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        with pytest.raises(ValueError, match="feature_cutoff must be exactly Monday 00:00:00 UTC"):
            label_gateway_week("0123456789AB", week_start, bad_f_cutoff, obs_win, default_label_spec, visits_df)


class TestEpisodeSemantics:
    """Test episode mechanics: open -> visited/repaired -> closed -> may reopen."""

    def test_multi_week_fault_episode(self, default_label_spec: LabelSpecV1):
        """A fault requested in Week 1 and resolved in Week 3 is BROKEN in Weeks 1, 2, and 3, then NOT_BROKEN in Week 4."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2025, 9, 3),  # Wednesday of week 2025-09-01
                "visited_on": dt.date(2025, 9, 17),   # Wednesday of week 2025-09-15
                "outcome": "Fehler behoben",
            }
        ])
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        # Week 1: 2025-09-01 (requested mid-week, active)
        w1_cutoff = dt.datetime(2025, 9, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl1 = label_gateway_week("0123456789AB", dt.date(2025, 9, 1), w1_cutoff, obs_win, default_label_spec, visits_df)
        assert lbl1 == GatewayWeekLabel.BROKEN

        # Week 2: 2025-09-08 (unvisited, persistently faulty)
        w2_cutoff = dt.datetime(2025, 9, 8, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl2 = label_gateway_week("0123456789AB", dt.date(2025, 9, 8), w2_cutoff, obs_win, default_label_spec, visits_df)
        assert lbl2 == GatewayWeekLabel.BROKEN

        # Week 3: 2025-09-15 (visited mid-week, closing episode)
        w3_cutoff = dt.datetime(2025, 9, 15, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl3 = label_gateway_week("0123456789AB", dt.date(2025, 9, 15), w3_cutoff, obs_win, default_label_spec, visits_df)
        assert lbl3 == GatewayWeekLabel.BROKEN

        # Week 4: 2025-09-22 (episode closed)
        w4_cutoff = dt.datetime(2025, 9, 22, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl4 = label_gateway_week("0123456789AB", dt.date(2025, 9, 22), w4_cutoff, obs_win, default_label_spec, visits_df)
        assert lbl4 == GatewayWeekLabel.NOT_BROKEN

    def test_episode_reopens_on_subsequent_fault(self, default_label_spec: LabelSpecV1):
        """After an episode closes, a subsequent fault creates a new independent episode."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2025, 9, 1),
                "visited_on": dt.date(2025, 9, 3),
                "outcome": "Fehler behoben",
            },
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2025, 10, 6),
                "visited_on": dt.date(2025, 10, 8),
                "outcome": "Fehler behoben",
            },
        ])
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        # Intermediate healthy week: 2025-09-15
        f_cutoff_healthy = dt.datetime(2025, 9, 15, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl_healthy = label_gateway_week("0123456789AB", dt.date(2025, 9, 15), f_cutoff_healthy, obs_win, default_label_spec, visits_df)
        assert lbl_healthy == GatewayWeekLabel.NOT_BROKEN

        # Reopened episode: 2025-10-06
        f_cutoff_reopen = dt.datetime(2025, 10, 6, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl_reopen = label_gateway_week("0123456789AB", dt.date(2025, 10, 6), f_cutoff_reopen, obs_win, default_label_spec, visits_df)
        assert lbl_reopen == GatewayWeekLabel.BROKEN

    def test_benign_visit_false_alarm_not_broken(self, default_label_spec: LabelSpecV1):
        """A visit with 'Kein Fehler gefunden' or 'Kein Zugang' does not produce BROKEN."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2025, 10, 1),
                "visited_on": dt.date(2025, 10, 8),
                "outcome": "Kein Fehler gefunden",
            }
        ])
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        f_cutoff = dt.datetime(2025, 10, 6, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl = label_gateway_week("0123456789AB", dt.date(2025, 10, 6), f_cutoff, obs_win, default_label_spec, visits_df)
        assert lbl == GatewayWeekLabel.NOT_BROKEN

    def test_right_censoring_at_observation_window_boundary(self, default_label_spec: LabelSpecV1):
        """Unobserved terminal recovery beyond observation window is UNKNOWN_RIGHT_CENSORED."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2026, 1, 28),
                "visited_on": None,  # Not yet visited before observation window ends
                "outcome": None,
            }
        ])
        # Observation window ends on 2026-01-31
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        # Prior week 2026-01-19 (requested after week end)
        f_cutoff_prior = dt.datetime(2026, 1, 19, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl_prior = label_gateway_week("0123456789AB", dt.date(2026, 1, 19), f_cutoff_prior, obs_win, default_label_spec, visits_df)
        assert lbl_prior == GatewayWeekLabel.NOT_BROKEN

        # Week 2026-01-26 (fault requested mid-week, but unobserved recovery)
        f_cutoff_censored = dt.datetime(2026, 1, 26, 0, 0, 0, tzinfo=dt.timezone.utc)
        lbl_censored = label_gateway_week("0123456789AB", dt.date(2026, 1, 26), f_cutoff_censored, obs_win, default_label_spec, visits_df)
        assert lbl_censored == GatewayWeekLabel.UNKNOWN_RIGHT_CENSORED


class TestAuditedHistoricalCases:
    """Verify >= 3 clearly interpretable cases on actual supplied development data."""

    def test_three_audited_historical_cases(self, real_data_dir: Path, default_label_spec: LabelSpecV1):
        """Assert Cases 1, 2, and 3 produce exact audited labels on real data."""
        visits = load_field_visits(real_data_dir)
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        # Case 1: 0E61D34F9993 (WO-2025-00465: requested 2025-10-20, visited 2025-11-05, Netzteil replaced)
        c1_id = "0E61D34F9993"
        c1_broken_weeks = [dt.date(2025, 10, 20), dt.date(2025, 10, 27), dt.date(2025, 11, 3)]
        for w in c1_broken_weeks:
            fc = dt.datetime(w.year, w.month, w.day, 0, 0, 0, tzinfo=dt.timezone.utc)
            assert label_gateway_week(c1_id, w, fc, obs_win, default_label_spec, visits) == GatewayWeekLabel.BROKEN
        # Post-repair week
        c1_healthy = dt.date(2025, 11, 10)
        fc1_h = dt.datetime(c1_healthy.year, c1_healthy.month, c1_healthy.day, 0, 0, 0, tzinfo=dt.timezone.utc)
        assert label_gateway_week(c1_id, c1_healthy, fc1_h, obs_win, default_label_spec, visits) == GatewayWeekLabel.NOT_BROKEN

        # Case 2: 0ED0849FD6D8 (WO-2025-00470: requested 2025-10-21, visited 2025-11-01, Antenne replaced)
        c2_id = "0ED0849FD6D8"
        c2_broken_weeks = [dt.date(2025, 10, 20), dt.date(2025, 10, 27)]
        for w in c2_broken_weeks:
            fc = dt.datetime(w.year, w.month, w.day, 0, 0, 0, tzinfo=dt.timezone.utc)
            assert label_gateway_week(c2_id, w, fc, obs_win, default_label_spec, visits) == GatewayWeekLabel.BROKEN
        c2_healthy = dt.date(2025, 11, 3)
        fc2_h = dt.datetime(c2_healthy.year, c2_healthy.month, c2_healthy.day, 0, 0, 0, tzinfo=dt.timezone.utc)
        assert label_gateway_week(c2_id, c2_healthy, fc2_h, obs_win, default_label_spec, visits) == GatewayWeekLabel.NOT_BROKEN

        # Case 3: 0A68A2032450 (WO-2025-00520: requested 2025-11-20, visited 2025-12-03, Gateway getauscht)
        c3_id = "0A68A2032450"
        c3_broken_weeks = [dt.date(2025, 11, 17), dt.date(2025, 11, 24), dt.date(2025, 12, 1)]
        for w in c3_broken_weeks:
            fc = dt.datetime(w.year, w.month, w.day, 0, 0, 0, tzinfo=dt.timezone.utc)
            assert label_gateway_week(c3_id, w, fc, obs_win, default_label_spec, visits) == GatewayWeekLabel.BROKEN
        c3_healthy = dt.date(2025, 12, 8)
        fc3_h = dt.datetime(c3_healthy.year, c3_healthy.month, c3_healthy.day, 0, 0, 0, tzinfo=dt.timezone.utc)
        assert label_gateway_week(c3_id, c3_healthy, fc3_h, obs_win, default_label_spec, visits) == GatewayWeekLabel.NOT_BROKEN

    def test_rolling_evaluation_windows_broken_count(self, real_data_dir: Path, default_label_spec: LabelSpecV1):
        """Assert exact broken gateway-week count across 13 rolling evaluation Mondays."""
        master = load_gateway_master(real_data_dir)
        visits = load_field_visits(real_data_dir)
        obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        eval_mondays = [
            # Window 1: Nov 2025
            dt.date(2025, 11, 3), dt.date(2025, 11, 10), dt.date(2025, 11, 17), dt.date(2025, 11, 24),
            # Window 2: Dec 2025
            dt.date(2025, 12, 1), dt.date(2025, 12, 8), dt.date(2025, 12, 15), dt.date(2025, 12, 22), dt.date(2025, 12, 29),
            # Window 3: Jan 2026
            dt.date(2026, 1, 5), dt.date(2026, 1, 12), dt.date(2026, 1, 19), dt.date(2026, 1, 26),
        ]

        total_broken = 0
        for monday in eval_mondays:
            elig = get_gateway_eligibility(master, monday)
            eligible_ids = elig[elig["is_eligible"]]["canonical_id"].tolist()
            fc = dt.datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=dt.timezone.utc)
            labels, summary = label_cohort(eligible_ids, monday, fc, obs_win, default_label_spec, visits)
            total_broken += summary.broken_gateway_weeks

        # Exactly 137 broken gateway-weeks confirmed across the 13 evaluation weeks
        assert total_broken == 137
        assert total_broken >= default_label_spec.min_interpretable_cases


class TestDevelopmentFirewallAndHoldoutProtection:
    """Verify development firewall and holdout protection guards (Rule 8 & Section 2C)."""

    def test_late_january_fault_resolved_in_february_retrospective_window(self, default_label_spec: LabelSpecV1):
        """A late-January fault repaired in February is BROKEN when observation window extends to Feb 14."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2026, 1, 25),
                "visited_on": dt.date(2026, 2, 3),  # Repaired in February
                "outcome": "Fehler behoben",
            }
        ])
        week_start = dt.date(2026, 1, 26)
        fc = dt.datetime(2026, 1, 26, 0, 0, 0, tzinfo=dt.timezone.utc)
        feb_obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 2, 14, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        lbl = label_gateway_week("0123456789AB", week_start, fc, feb_obs_win, default_label_spec, visits_df)
        assert lbl == GatewayWeekLabel.BROKEN

    def test_late_january_fault_unresolved_with_capped_observation_window(self, default_label_spec: LabelSpecV1):
        """The same late-January fault is UNKNOWN_RIGHT_CENSORED when observation window ends Jan 31."""
        visits_df = pd.DataFrame([
            {
                "canonical_id": "0123456789AB",
                "requested_on": dt.date(2026, 1, 25),
                "visited_on": dt.date(2026, 2, 3),  # Repair occurs after observation cutoff
                "outcome": "Fehler behoben",
            }
        ])
        week_start = dt.date(2026, 1, 26)
        fc = dt.datetime(2026, 1, 26, 0, 0, 0, tzinfo=dt.timezone.utc)
        jan_obs_win = (
            dt.datetime(2025, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 1, 31, 23, 59, 59, tzinfo=dt.timezone.utc),
        )

        lbl = label_gateway_week("0123456789AB", week_start, fc, jan_obs_win, default_label_spec, visits_df)
        assert lbl == GatewayWeekLabel.UNKNOWN_RIGHT_CENSORED

    def test_development_firewall_date_guard_direct(self):
        """HoldoutProtection.check_date_access raises DevelopmentFirewallError for dates > 2026-01-31."""
        with pytest.raises(DevelopmentFirewallError, match="exceeds frozen development cutoff"):
            HoldoutProtection.check_date_access(dt.date(2026, 2, 1), allow_holdout=False)

        # Authorized call succeeds
        HoldoutProtection.check_date_access(dt.date(2026, 2, 1), allow_holdout=True)

    def test_load_engineer_review_blocked_in_dev_mode(self, real_data_dir: Path):
        """load_engineer_review without allow_holdout=True trips HoldoutAccessError."""
        with pytest.raises(HoldoutAccessError, match="Unauthorized access to post-cutoff holdout file"):
            load_engineer_review(real_data_dir, allow_holdout=False)

    def test_group_holdout_guard(self):
        """Accessing a gateway in the holdout group without authorization trips HoldoutAccessError."""
        holdout_set = {"0639EA5602C1", "0E5DFCF65AD4"}
        with pytest.raises(HoldoutAccessError, match="Unauthorized access to GROUP_HOLDOUT gateway"):
            HoldoutProtection.check_gateway_access("0639EA5602C1", holdout_set, allow_holdout=False)

        # Authorized access succeeds
        HoldoutProtection.check_gateway_access("0639EA5602C1", holdout_set, allow_holdout=True)


class TestAntiLeakageProductionBoundary:
    """Anti-leakage and AST-enforced production path boundaries."""

    def test_predict_does_not_import_evaluation_or_field_visits(self):
        """predict.py must NEVER import evaluation modules or field_visits (Operating Rule 4)."""
        predict_files = [
            Path("app/model/predict.py"),
            Path("scripts/predict.py"),
        ]

        prohibited_imports = {"evaluate", "app.model.evaluate", "field_visits"}

        for p_file in predict_files:
            source = p_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(p_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in prohibited_imports, (
                            f"{p_file} imports prohibited module '{alias.name}'"
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert mod not in prohibited_imports, (
                        f"{p_file} imports from prohibited module '{mod}'"
                    )
                    assert not mod.endswith("evaluate"), (
                        f"{p_file} imports from prohibited evaluate module '{mod}'"
                    )
                    for alias in node.names:
                        assert alias.name not in prohibited_imports, (
                            f"{p_file} imports prohibited symbol '{alias.name}' from '{mod}'"
                        )

    def test_feature_temporal_isolation_firewall(self, tmp_path: Path):
        """Future observations after Monday 00:00 UTC must never leak into feature window."""
        from app.data.loader import load_telemetry_window

        # Create two datasets: one base, one with future observations injected
        cutoff_utc = dt.datetime(2025, 10, 6, 0, 0, 0, tzinfo=dt.timezone.utc)
        base_records = [
            {
                "gateway_id": "0639EA5602C1",
                "ts_utc": "2025-10-05T22:00:00Z",
                "reboot_cnt": 0,
                "disconnection_cnt": 1,
                "offline_duration_sec": 60.0,
            },
            {
                "gateway_id": "0639EA5602C1",
                "ts_utc": "2025-10-05T23:00:00Z",
                "reboot_cnt": 0,
                "disconnection_cnt": 0,
                "offline_duration_sec": 0.0,
            },
        ]
        future_records = base_records + [
            # Future records at and after cutoff
            {
                "gateway_id": "0639EA5602C1",
                "ts_utc": "2025-10-06T00:00:00Z",  # Exactly at cutoff (must be excluded)
                "reboot_cnt": 5,
                "disconnection_cnt": 10,
                "offline_duration_sec": 3600.0,
            },
            {
                "gateway_id": "0639EA5602C1",
                "ts_utc": "2025-10-07T12:00:00Z",  # Future day
                "reboot_cnt": 10,
                "disconnection_cnt": 20,
                "offline_duration_sec": 7200.0,
            },
        ]

        dir_base = tmp_path / "base"
        dir_future = tmp_path / "future"
        dir_base.mkdir()
        dir_future.mkdir()

        pd.DataFrame(base_records).to_parquet(dir_base / "telemetry.parquet")
        pd.DataFrame(future_records).to_parquet(dir_future / "telemetry.parquet")

        loaded_base = load_telemetry_window(dir_base, cutoff_utc=cutoff_utc)
        loaded_future = load_telemetry_window(dir_future, cutoff_utc=cutoff_utc)

        # Future records must have ZERO effect on loaded feature data
        assert len(loaded_base) == 2
        assert len(loaded_future) == 2
        pd.testing.assert_frame_equal(
            loaded_base[["canonical_id", "ts", "reboot_cnt", "disconnection_cnt", "offline_duration_sec"]],
            loaded_future[["canonical_id", "ts", "reboot_cnt", "disconnection_cnt", "offline_duration_sec"]],
        )
