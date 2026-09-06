"""Unit tests for RESQ Operations Console frontend shell (Frontend Task 1).

Validates:
1. Static file completeness (index.html, styles.css, app.js, README.md).
2. Wireframe DOM elements (all 5 core sections and required KPI/governance elements).
3. Server artifact loaders (load_json_artifact, load_predictions_artifact).
4. Truthful nullability / UNAVAILABLE fallback when files are missing or corrupt.
5. Handler endpoint responses (/api/health, /api/summary, /api/predictions).
6. Makefile and make.cmd frontend target contracts.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from frontend.server import (
    load_json_artifact,
    load_predictions_artifact,
    ConsoleRequestHandler,
)


class TestFrontendShell(unittest.TestCase):
    """Test suite for the frontend shell assets and read-only server logic."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
        cls.frontend_dir = cls.repo_root / "frontend"
        cls.static_dir = cls.frontend_dir / "static"

    def test_static_assets_exist(self):
        """Verify all required frontend files exist in the repository."""
        self.assertTrue((self.frontend_dir / "server.py").exists(), "server.py must exist")
        self.assertTrue((self.frontend_dir / "README.md").exists(), "frontend/README.md must exist")
        self.assertTrue((self.static_dir / "index.html").exists(), "static/index.html must exist")
        self.assertTrue((self.static_dir / "styles.css").exists(), "static/styles.css must exist")
        self.assertTrue((self.static_dir / "app.js").exists(), "static/app.js must exist")

    def test_html_wireframe_structure(self):
        """Verify index.html contains the 5 required wireframe sections and element IDs."""
        html_content = (self.static_dir / "index.html").read_text(encoding="utf-8")

        # 1. Header & Active Model Badge
        self.assertIn("RESQ Operations Console", html_content)
        self.assertIn('id="active-model-badge"', html_content)

        # 2. KPI Summary Strip
        self.assertIn('id="kpi-week"', html_content)
        self.assertIn('id="kpi-fleet"', html_content)
        self.assertIn('id="kpi-capacity"', html_content)
        self.assertIn('id="kpi-health"', html_content)

        # 3. Dispatch Priority Table & Week Selector
        self.assertIn('id="week-select"', html_content)
        self.assertIn('id="dispatch-tbody"', html_content)
        self.assertIn("Dispatch Priority", html_content)

        # 4. Split Panels: Governance & Data Health
        self.assertIn('id="gov-verdict-banner"', html_content)
        self.assertIn('id="gov-verdict-pill"', html_content)
        self.assertIn('id="gov-verdict-code"', html_content)
        self.assertIn('id="gov-verdict-summary"', html_content)
        self.assertIn('id="gov-active"', html_content)
        self.assertIn('id="gov-candidate"', html_content)
        self.assertIn('id="gov-improvement"', html_content)
        self.assertIn('id="gov-holdout"', html_content)

        # Task 2: Upgraded Governance Centerpiece Elements
        self.assertIn('id="gov-explainer-text"', html_content)
        self.assertIn('id="gov-explainer-code"', html_content)
        self.assertIn('id="dev-evidence-tbody"', html_content)
        self.assertIn('id="dev-evidence-aggregate"', html_content)
        self.assertIn('id="holdout-gateways"', html_content)
        self.assertIn('id="holdout-active-missed"', html_content)
        self.assertIn('id="holdout-cand-missed"', html_content)
        self.assertIn('id="holdout-status-badge"', html_content)
        self.assertIn('id="final-gate-deployment"', html_content)
        self.assertIn('id="final-gate-protection"', html_content)

        # Task 2: Interactive Evidence Review Modal & Fail-Closed Drawer
        self.assertIn('id="open-evidence-btn"', html_content)
        self.assertIn('id="evidence-modal"', html_content)
        self.assertIn('id="close-evidence-btn"', html_content)
        self.assertIn('id="modal-candidate"', html_content)
        self.assertIn('id="modal-active"', html_content)
        self.assertIn('id="modal-aggregate-counts"', html_content)
        self.assertIn('id="modal-improvement"', html_content)
        self.assertIn('id="final-decision-badge"', html_content)
        self.assertIn('id="final-decision-code"', html_content)
        self.assertIn('id="modal-final-deployment"', html_content)
        self.assertIn('id="modal-final-protection"', html_content)
        self.assertIn('id="fail-closed-drawer"', html_content)

        # Task 2: Evidence-Quality Indicators
        self.assertIn('id="quality-dev-windows"', html_content)
        self.assertIn('id="quality-holdout"', html_content)
        self.assertIn('id="quality-fleet-truth"', html_content)

        self.assertIn('id="health-schema"', html_content)
        self.assertIn('id="health-completeness"', html_content)
        self.assertIn('id="health-absence"', html_content)
        self.assertIn('id="health-reporting"', html_content)

        # 5. Backlog Strip
        self.assertIn('id="backlog-deferred"', html_content)
        self.assertIn('id="backlog-high-risk"', html_content)
        self.assertIn('id="backlog-proxy-hours"', html_content)

        # 6. Lifecycle & Rollback Strip
        self.assertIn('id="lifecycle-timeline"', html_content)
        self.assertIn('id="flow-candidate"', html_content)
        self.assertIn('id="flow-gate"', html_content)
        self.assertIn('id="flow-restored"', html_content)
        self.assertIn('id="rollback-panel"', html_content)
        self.assertIn('id="rollback-status-badge"', html_content)
        self.assertIn('id="rollback-target-val"', html_content)
        self.assertIn('id="rollback-atomic-switch"', html_content)
        self.assertIn('id="rollback-replay-eq"', html_content)
        self.assertIn('id="rollback-restored-ver"', html_content)
        self.assertIn('id="rollback-reason"', html_content)
        self.assertIn('id="lifecycle-replay"', html_content)

    def test_real_promotion_artifact_three_windows_rendered(self):
        """Verify real promotion decision contains 3 distinct development rolling windows with valid counts."""
        res = load_json_artifact("runs/promotion/promotion_decision_v0002.json")
        self.assertEqual(res.get("status"), "AVAILABLE")
        data = res.get("data", {})
        window_results = data.get("window_results", {})
        self.assertEqual(len(window_results), 3, "Must have exactly 3 development rolling windows")
        
        expected_windows = ["window_1", "window_2", "window_3"]
        for wid in expected_windows:
            self.assertIn(wid, window_results)
            w = window_results[wid]
            self.assertIn("active_missed_broken_weeks", w)
            self.assertIn("candidate_missed_broken_weeks", w)
            self.assertIsInstance(w["active_missed_broken_weeks"], int)
            self.assertIsInstance(w["candidate_missed_broken_weeks"], int)
            self.assertFalse(w.get("is_regression", True), "All dev windows must pass without regression")

    def test_real_promotion_artifact_71_vs_60_derived(self):
        """Verify dynamic derivation of aggregate 71 vs 60 missed broken weeks and 15.49% improvement."""
        res = load_json_artifact("runs/promotion/promotion_decision_v0002.json")
        self.assertEqual(res.get("status"), "AVAILABLE")
        data = res.get("data", {})
        self.assertEqual(data.get("total_active_missed"), 71)
        self.assertEqual(data.get("total_candidate_missed"), 60)
        self.assertEqual(data.get("aggregate_improvement_percent"), 15.49)

    def test_real_promotion_artifact_17_vs_18_holdout_derived(self):
        """Verify grouped holdout on 59 unseen gateways derives 17 vs 18 missed weeks (regression)."""
        res = load_json_artifact("runs/promotion/promotion_decision_v0002.json")
        self.assertEqual(res.get("status"), "AVAILABLE")
        data = res.get("data", {})
        holdout = data.get("grouped_holdout_result", {})
        self.assertEqual(holdout.get("holdout_gateways_count"), 59)
        self.assertEqual(holdout.get("active_missed_broken_weeks"), 17)
        self.assertEqual(holdout.get("candidate_missed_broken_weeks"), 18)
        self.assertEqual(holdout.get("differential"), -1)
        self.assertFalse(holdout.get("directional_agreement"), "Holdout must report directional disagreement")

    def test_missing_promotion_artifact_entire_evidence_unavailable(self):
        """Verify that when promotion artifact is missing, server returns explicit UNAVAILABLE without fabricating."""
        res = load_json_artifact("runs/promotion/nonexistent_artifact.json")
        self.assertEqual(res.get("status"), "UNAVAILABLE")
        self.assertIn("not found on disk", res.get("reason", ""))
        self.assertNotIn("total_active_missed", res.get("data", {}))

    def test_missing_one_window_field_renders_unavailable_never_zero(self):
        """Verify load_json_artifact sets totals to None rather than 0 when any window count is incomplete."""
        fixture_data = {
            "window_results": {
                "window_1": {"active_missed_broken_weeks": 10},  # candidate_missed_broken_weeks missing
                "window_2": {"candidate_missed_broken_weeks": 5}  # active_missed_broken_weeks missing
            }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=self.repo_root) as tf:
            json.dump(fixture_data, tf)
            temp_path = pathlib.Path(tf.name)

        try:
            rel_path = str(temp_path.relative_to(self.repo_root))
            res = load_json_artifact(rel_path)
            self.assertEqual(res.get("status"), "AVAILABLE")
            self.assertIsNone(res["data"]["total_active_missed"])
            self.assertIsNone(res["data"]["total_candidate_missed"])
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_missing_holdout_field_renders_unavailable(self):
        """Verify that missing holdout fields are preserved as absent without default values."""
        fixture_data = {
            "candidate_version": "v0002",
            "decision": "REJECT"
            # grouped_holdout_result entirely missing
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=self.repo_root) as tf:
            json.dump(fixture_data, tf)
            temp_path = pathlib.Path(tf.name)

        try:
            rel_path = str(temp_path.relative_to(self.repo_root))
            res = load_json_artifact(rel_path)
            self.assertEqual(res.get("status"), "AVAILABLE")
            self.assertNotIn("grouped_holdout_result", res["data"])
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_wrong_or_incomplete_decision_no_fabricated_verdict(self):
        """Verify that an incomplete promotion artifact does not fabricate a decision verdict."""
        fixture_data = {
            "candidate_version": "v0002"
            # decision and reason_code missing
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=self.repo_root) as tf:
            json.dump(fixture_data, tf)
            temp_path = pathlib.Path(tf.name)

        try:
            rel_path = str(temp_path.relative_to(self.repo_root))
            res = load_json_artifact(rel_path)
            self.assertEqual(res.get("status"), "AVAILABLE")
            self.assertIsNone(res["data"].get("decision"))
            self.assertIsNone(res["data"].get("reason_code"))
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_replay_provenance_truthful_nullability(self):
        """Verify replay provenance fails closed to UNAVAILABLE when proof is absent."""
        from frontend.server import check_replay_provenance
        # Baseline state without rollback report should be UNAVAILABLE
        res = check_replay_provenance()
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertIn("not substantiated", res["reason"])
        self.assertEqual(res["target_validation"], "UNAVAILABLE")
        self.assertEqual(res["atomic_switch"], "UNAVAILABLE")
        self.assertEqual(res["replay_equality"], "UNAVAILABLE")
        self.assertEqual(res["restored_version"], "UNAVAILABLE")

    def test_replay_provenance_substantiated_with_rollback_event(self):
        """Verify replay provenance returns VERIFIED and properties when rollback is substantiated."""
        from frontend.server import check_replay_provenance
        simulated_history = [
            '{"event": "INITIALIZED", "version": "v0001", "timestamp": "2026-09-05T00:00:00Z"}\n',
            '{"event": "ROLLED_BACK", "version": "v0001", "previous_version": "v0002", "timestamp": "2026-09-05T01:00:00Z", "reason": "rollback to v0001"}\n'
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, dir=self.repo_root) as tf:
            tf.writelines(simulated_history)
            temp_path = pathlib.Path(tf.name)

        try:
            with patch("frontend.server.REPO_ROOT", temp_path.parent):
                with patch.object(pathlib.Path, "exists", return_value=True):
                    with patch.object(pathlib.Path, "read_text", return_value="".join(simulated_history)):
                        res = check_replay_provenance()
                        self.assertEqual(res["status"], "VERIFIED")
                        self.assertEqual(res["target_validation"], "VERIFIED")
                        self.assertEqual(res["atomic_switch"], "VERIFIED")
                        self.assertEqual(res["replay_equality"], "VERIFIED")
                        self.assertEqual(res["restored_version"], "v0001")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_no_hardcoded_metrics_in_javascript(self):
        """Anti-fabrication test: assert app.js contains zero hard-coded numbers for governance metrics."""
        import re
        app_js_text = (self.static_dir / "app.js").read_text(encoding="utf-8")

        # Specific metrics that must NEVER be hard-coded literals in JS
        forbidden_patterns = [
            r"\b71\b",          # active missed aggregate
            r"\b60\b",          # candidate missed aggregate
            r"\b15\.49\b",      # aggregate improvement percent
            r"\b59\b",          # holdout gateway count
            r"\b17\b",          # holdout active missed
            r"\b18\b",          # holdout candidate missed
        ]
        for pat in forbidden_patterns:
            matches = re.findall(pat, app_js_text)
            self.assertEqual(
                len(matches),
                0,
                f"Found hardcoded forbidden metric pattern '{pat}' in app.js! All metrics must be dynamically derived."
            )

    def test_load_json_artifact_existing(self):
        """Verify load_json_artifact loads real existing artifacts accurately."""
        res = load_json_artifact("registry/active.json")
        self.assertEqual(res.get("status"), "AVAILABLE")
        self.assertIn("production_version", res.get("data", {}))
        self.assertEqual(res["data"]["production_version"], "v0001")

    def test_load_json_artifact_missing_returns_unavailable(self):
        """Verify load_json_artifact returns explicit UNAVAILABLE structure when file is missing."""
        res = load_json_artifact("non_existent_file_xyz.json")
        self.assertEqual(res.get("status"), "UNAVAILABLE")
        self.assertIn("not found on disk", res.get("reason", ""))
        self.assertEqual(res.get("file"), "non_existent_file_xyz.json")

    def test_load_json_artifact_corrupt_returns_unavailable(self):
        """Verify load_json_artifact handles invalid JSON safely with UNAVAILABLE."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=self.repo_root) as tf:
            tf.write("{ this is invalid json }")
            temp_path = pathlib.Path(tf.name)

        try:
            rel_path = str(temp_path.relative_to(self.repo_root))
            res = load_json_artifact(rel_path)
            self.assertEqual(res.get("status"), "UNAVAILABLE")
            self.assertIn("Failed to parse", res.get("reason", ""))
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_load_predictions_artifact_existing(self):
        """Verify load_predictions_artifact loads predictions.csv with 15 rows per week."""
        res = load_predictions_artifact()
        self.assertEqual(res.get("status"), "AVAILABLE")
        self.assertIn("available_weeks", res)
        self.assertEqual(len(res["available_weeks"]), 8)
        self.assertEqual(res.get("week_rows_count"), 15)
        self.assertEqual(len(res.get("predictions", [])), 15)

        # Check required columns on first prediction
        first_row = res["predictions"][0]
        self.assertIn("rank", first_row)
        self.assertIn("gateway_id", first_row)
        self.assertIn("score", first_row)
        self.assertIn("reason", first_row)
        self.assertEqual(first_row["rank"], "1")

    def test_load_predictions_artifact_week_filter(self):
        """Verify load_predictions_artifact filters by specific challenge week."""
        target_week = "2026-02-16"
        res = load_predictions_artifact(target_week)
        self.assertEqual(res.get("status"), "AVAILABLE")
        self.assertEqual(res.get("selected_week"), target_week)
        self.assertEqual(len(res.get("predictions", [])), 15)
        for row in res["predictions"]:
            self.assertEqual(row["week_start"], target_week)

    def test_load_predictions_missing_returns_unavailable(self):
        """Verify load_predictions_artifact returns UNAVAILABLE if predictions.csv is missing."""
        with patch("frontend.server.REPO_ROOT", pathlib.Path("/tmp/nonexistent_repo_dir")):
            res = load_predictions_artifact()
            self.assertEqual(res.get("status"), "UNAVAILABLE")
            self.assertIn("predictions.csv not found", res.get("reason", ""))

    def test_makefile_and_make_cmd_contracts(self):
        """Verify Makefile and make.cmd contain the 'frontend' target."""
        makefile_content = (self.repo_root / "Makefile").read_text(encoding="utf-8")
        self.assertIn("frontend:", makefile_content)
        self.assertIn("frontend/server.py", makefile_content)

        make_cmd_content = (self.repo_root / "make.cmd").read_text(encoding="utf-8")
        self.assertIn('"%1"=="frontend"', make_cmd_content)
        self.assertIn("frontend/server.py", make_cmd_content)

    def test_initial_html_contains_no_hardcoded_factual_states(self):
        """Assert that index.html contains no hardcoded factual states or narrative defaults."""
        html_content = (self.static_dir / "index.html").read_text(encoding="utf-8")

        forbidden_factual_phrases = [
            "Why wasn't v0002 deployed?",
            "59 unseen gateways",
            "59 unseen",
            "+1 missed broken week",
            "+1 missed",
            "REJECT_GROUPED_DISAGREEMENT",
            "GATE: REJECTED",
            "Candidate NOT deployed",
            "Active v0001 remains protected",
            "17 missed",
            "18 missed",
            "15.49%",
            "71 → 60",
            "71 -> 60",
            "v0002 CANDIDATE",
            "v0001 ACTIVE",
        ]

        for phrase in forbidden_factual_phrases:
            self.assertNotIn(
                phrase,
                html_content,
                f"Found hardcoded factual phrase '{phrase}' in index.html! Initial HTML must use neutral placeholders."
            )

    def test_javascript_contains_no_factual_fallback_strings(self):
        """Assert that app.js contains zero hardcoded model version literals or fallbacks."""
        import re
        app_js_text = (self.static_dir / "app.js").read_text(encoding="utf-8")

        # Must not contain hardcoded model version literals
        version_matches = re.findall(r"\bv000[12]\b", app_js_text)
        self.assertEqual(
            len(version_matches),
            0,
            f"Found hardcoded version strings {version_matches} in app.js! All versions must be dynamic."
        )

        # Must not have fallback assignments to specific version strings
        forbidden_patterns = [
            r'\|\|\s*["\']v0001["\']',
            r'\|\|\s*["\']v0002["\']',
            r'\?\?\s*["\']v0001["\']',
            r'\?\?\s*["\']v0002["\']',
        ]
        for pat in forbidden_patterns:
            matches = re.findall(pat, app_js_text)
            self.assertEqual(
                len(matches),
                0,
                f"Found fallback pattern '{pat}' in app.js! Must fail closed without fabricating defaults."
            )

    def test_fail_closed_drawer_elements_exist(self):
        """Verify dynamic fail-closed drawer elements exist in index.html for JavaScript binding."""
        html_content = (self.static_dir / "index.html").read_text(encoding="utf-8")
        required_fc_elements = [
            'id="fc-step1-pill"',
            'id="fc-step1-desc"',
            'id="fc-step2-pill"',
            'id="fc-step2-desc"',
            'id="fc-step3-pill"',
            'id="fc-step3-desc"',
            'id="fc-step4-pill"',
            'id="fc-step4-desc"',
        ]
        for elem_id in required_fc_elements:
            self.assertIn(elem_id, html_content, f"Missing required dynamic element {elem_id} in index.html")

    def test_server_check_replay_provenance_no_hardcoded_v0001_fallback(self):
        """Verify check_replay_provenance returns UNAVAILABLE if restored version is missing."""
        from frontend.server import check_replay_provenance
        # Simulate history event without version key
        simulated_history = [
            '{"event": "ROLLED_BACK", "timestamp": "2026-09-05T01:00:00Z"}\n'
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, dir=self.repo_root) as tf:
            tf.writelines(simulated_history)
            temp_path = pathlib.Path(tf.name)

        try:
            with patch("frontend.server.REPO_ROOT", temp_path.parent):
                with patch.object(pathlib.Path, "exists", return_value=True):
                    with patch.object(pathlib.Path, "read_text", return_value="".join(simulated_history)):
                        res = check_replay_provenance()
                        self.assertEqual(res["restored_version"], "UNAVAILABLE", "Must not fall back to v0001")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    # =========================================================================
    # Task 3: Backlog Intelligence & Deferral Inspector Tests
    # =========================================================================

    def test_backlog_endpoint_available(self):
        """Verify load_json_artifact loads backlog_report.json with required fields."""
        res = load_json_artifact("backlog_report.json")
        self.assertEqual(res.get("status"), "AVAILABLE")
        data = res.get("data", {})
        self.assertIn("max_visits", data)
        self.assertIn("selected_count", data)
        self.assertIn("deferred_count", data)
        self.assertIn("deferred_high_risk_count", data)
        self.assertIn("deferred_risk_proxy_score", data)
        self.assertEqual(data.get("exposure_method"), "heuristic_proxy")
        self.assertEqual(data.get("max_visits"), 15)
        self.assertEqual(data.get("selected_count"), 15)

    def test_lookup_known_top15_dispatched(self):
        """Verify lookup_gateway_status identifies a top-15 dispatched gateway with exact rank and spend."""
        from frontend.server import lookup_gateway_status
        # Dispatched gateway from predictions.csv (0A2778A31BE3, Rank 1)
        res = lookup_gateway_status("0A2778A31BE3")
        self.assertEqual(res.get("status"), "AVAILABLE")
        self.assertEqual(res.get("disposition"), "DISPATCHED")
        self.assertEqual(res.get("rank"), 1)
        self.assertEqual(res.get("score"), 43.0)
        self.assertIn("allocated technician visit (Rank 1)", res.get("operational_narrative", ""))
        self.assertIn("€380 truck roll committed", res.get("operational_narrative", ""))

    def test_lookup_actual_rank16_deferred(self):
        """Verify lookup_gateway_status identifies an actual deferred gateway with exact rank 16+ from backlog artifact."""
        from frontend.server import lookup_gateway_status
        # Gateway in deferred_gateways (02D7623552C8, Rank 16)
        res = lookup_gateway_status("02D7623552C8")
        self.assertEqual(res.get("status"), "AVAILABLE")
        self.assertEqual(res.get("disposition"), "DEFERRED")
        self.assertEqual(res.get("rank"), 16)
        self.assertEqual(res.get("score"), 17.0)
        self.assertIn("deferred to backlog (Rank 16", res.get("operational_narrative", ""))
        self.assertIn("15-visit weekly capacity limit", res.get("operational_narrative", ""))
        self.assertEqual(res.get("exposure_method"), "heuristic_proxy")

        # Also check another deferred gateway (0639EA5602C1, Rank 169)
        res2 = lookup_gateway_status("0639EA5602C1")
        self.assertEqual(res2.get("status"), "AVAILABLE")
        self.assertEqual(res2.get("disposition"), "DEFERRED")
        self.assertEqual(res2.get("rank"), 169)
        self.assertEqual(res2.get("score"), 4.0)

    def test_lookup_ineligible_fleet_member_not_deferred(self):
        """Verify fleet members that are decommissioned or installed post-cutoff return INELIGIBLE_OR_UNSCORED, not DEFERRED."""
        from frontend.server import lookup_gateway_status
        # 023AD5204E1C exists in gateway_master.csv but was decommissioned before cutoff
        res_decomm = lookup_gateway_status("023AD5204E1C")
        self.assertEqual(res_decomm.get("status"), "INELIGIBLE_OR_UNSCORED")
        self.assertNotEqual(res_decomm.get("disposition"), "DEFERRED")
        self.assertIn("NOT eligible or scored", res_decomm.get("operational_narrative", ""))
        self.assertEqual(res_decomm.get("fleet_metadata", {}).get("decommissioned_on"), "2025-11-23")

        # 0A33C8DFA4C1 exists in gateway_master.csv but was installed after cutoff
        res_post = lookup_gateway_status("0A33C8DFA4C1")
        self.assertEqual(res_post.get("status"), "INELIGIBLE_OR_UNSCORED")
        self.assertNotEqual(res_post.get("disposition"), "DEFERRED")
        self.assertIn("NOT eligible or scored", res_post.get("operational_narrative", ""))

    def test_lookup_week_mismatch_returns_unavailable(self):
        """Verify requested week mismatch with backlog artifact returns UNAVAILABLE without cross-week leakage."""
        from frontend.server import lookup_gateway_status
        # Request a historical week while backlog artifact is for 2026-02-02
        res = lookup_gateway_status("0639EA5602C1", week="2025-11-03")
        self.assertEqual(res.get("status"), "UNAVAILABLE")
        self.assertIn("does not match backlog artifact week", res.get("reason", ""))

    def test_lookup_missing_backlog_artifact_unavailable(self):
        """Verify lookup returns UNAVAILABLE when backlog_report.json is absent."""
        from frontend.server import lookup_gateway_status
        with patch("frontend.server.load_json_artifact", return_value={"status": "UNAVAILABLE", "reason": "File missing"}):
            res = lookup_gateway_status("0639EA5602C1")
            self.assertEqual(res.get("status"), "UNAVAILABLE")
            self.assertIn("not found on disk", res.get("reason", ""))

    def test_lookup_gateway_status_not_found(self):
        """Verify lookup_gateway_status returns NOT_FOUND for unknown gateway ID."""
        from frontend.server import lookup_gateway_status
        res = lookup_gateway_status("FFFFFFFFFFFF")
        self.assertEqual(res.get("status"), "NOT_FOUND")
        self.assertIn("not found in active fleet master", res.get("operational_narrative", ""))

    def test_lookup_gateway_status_invalid_input(self):
        """Verify lookup_gateway_status rejects empty or whitespace-only inputs."""
        from frontend.server import lookup_gateway_status
        res = lookup_gateway_status("   ")
        self.assertEqual(res.get("status"), "INVALID")

    def test_no_fallback_to_15_when_capacity_missing(self):
        """Verify app.js does not fall back to 15 when maxVisits or selected_count is missing."""
        import re
        app_js_text = (self.static_dir / "app.js").read_text(encoding="utf-8")
        # Ensure no ?? 15 or || 15 fallbacks for capacity
        self.assertNotIn("maxVisits ?? 15", app_js_text)
        self.assertNotIn("selected ?? 15", app_js_text)
        self.assertNotIn("max_visits ?? 15", app_js_text)
        self.assertNotIn("selected_count ?? 15", app_js_text)

    def test_no_fallback_to_heuristic_proxy_when_missing(self):
        """Verify app.js does not fall back to 'heuristic_proxy' when exposure_method is missing."""
        app_js_text = (self.static_dir / "app.js").read_text(encoding="utf-8")
        # Ensure exposure badge handles missing exposure_method without defaulting to 'heuristic_proxy'
        self.assertNotIn('exposureBadge.textContent = data.exposure_method || "heuristic_proxy"', app_js_text)

    def test_same_ranked_object_continuity_contract(self):
        """Verify mathematical continuity between predictions.csv (ranks 1-15) and backlog_report.json (ranks 16+)."""
        import csv
        pred_path = self.repo_root / "predictions.csv"
        self.assertTrue(pred_path.exists(), "predictions.csv must exist")

        with open(pred_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))

        # Filter predictions for the matching week
        week_preds = [r for r in reader if r.get("week_start") == "2026-02-02"]
        self.assertEqual(len(week_preds), 15, "predictions.csv must contain exactly 15 records for week 2026-02-02")
        dispatched_ids = set(r["gateway_id"] for r in week_preds)
        self.assertEqual(len(dispatched_ids), 15, "15 unique dispatched gateway IDs")

        rank15_score = float(week_preds[-1]["score"])

        backlog_res = load_json_artifact("backlog_report.json")
        self.assertEqual(backlog_res.get("status"), "AVAILABLE")
        b_data = backlog_res["data"]
        deferred_list = b_data.get("deferred_gateways", [])
        self.assertEqual(len(deferred_list), 275, "deferred_gateways must contain 275 entries")

        deferred_ids = set(d["gateway_id"] for d in deferred_list)
        # Dispatched and deferred must be disjoint sets
        intersection = dispatched_ids.intersection(deferred_ids)
        self.assertEqual(len(intersection), 0, f"Dispatched and deferred sets must not overlap! Overlap: {intersection}")

        # Total unique evaluated gateways = 15 + 275 = 290
        total_gateways = dispatched_ids.union(deferred_ids)
        self.assertEqual(len(total_gateways), 290, "Dispatched + Deferred must exactly equal 290 eligible fleet")

        # Continuity check: rank 15 score >= rank 16 score
        rank16_score = float(deferred_list[0]["score"])
        self.assertEqual(deferred_list[0]["rank"], 16)
        self.assertGreaterEqual(
            rank15_score,
            rank16_score,
            f"Score continuity violated across dispatch/backlog boundary: Rank 15 ({rank15_score}) < Rank 16 ({rank16_score})"
        )

    def test_no_overclaimed_ast_or_verification_in_backlog_html(self):
        """Verify Backlog Intelligence section does not claim unproven AST enforcement or verification passes."""
        html_content = (self.static_dir / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(
            "AST-enforced integrity",
            html_content,
            "HTML must not overclaim 'AST-enforced integrity' for backlog continuity."
        )
        self.assertIn("DESIGN INVARIANT", html_content)
        self.assertIn("Pipeline architecture: one scoring pass feeds both dispatches and backlog", html_content)

    def test_no_hardcoded_backlog_metrics_in_javascript(self):
        """Anti-fabrication test: assert app.js contains zero hardcoded numbers for backlog counts."""
        import re
        app_js_text = (self.static_dir / "app.js").read_text(encoding="utf-8")
        forbidden_patterns = [
            r"\b275\b",         # deferred count
            r"\b245\b",         # deferred elevated risk count
            r"\b1523\b",        # proxy anomaly hours
        ]
        for pat in forbidden_patterns:
            matches = re.findall(pat, app_js_text)
            self.assertEqual(
                len(matches),
                0,
                f"Found hardcoded backlog metric '{pat}' in app.js! Backlog numbers must be dynamically derived."
            )

    def test_initial_html_contains_no_hardcoded_backlog_metrics(self):
        """Anti-fabrication test: assert index.html contains no hardcoded backlog numbers in initial state."""
        html_content = (self.static_dir / "index.html").read_text(encoding="utf-8")
        forbidden_metrics = [
            "275 Deferred",
            "245 Elevated",
            "1,523 Proxy",
            "1523 Proxy",
        ]
        for term in forbidden_metrics:
            self.assertNotIn(
                term,
                html_content,
                f"Found hardcoded metric '{term}' in initial index.html! Must use neutral placeholders."
            )

    def test_backlog_modal_and_elements_exist(self):
        """Verify Task 3 Backlog Intelligence modal and inspector elements exist in index.html."""
        html_content = (self.static_dir / "index.html").read_text(encoding="utf-8")
        required_elements = [
            'id="open-backlog-btn"',
            'id="backlog-modal"',
            'id="close-backlog-btn"',
            'id="alloc-label-dispatched"',
            'id="alloc-label-deferred"',
            'id="alloc-bar-dispatched"',
            'id="alloc-bar-deferred"',
            'id="backlog-modal-week"',
            'id="backlog-modal-version"',
            'id="bm-dispatched-summary"',
            'id="bm-deferred-count"',
            'id="bm-elevated-risk"',
            'id="bm-proxy-hours"',
            'id="backlog-lookup-input"',
            'id="backlog-lookup-btn"',
            'id="backlog-lookup-result"',
            'class="pipeline-continuity-flow"',
        ]
        for elem in required_elements:
            self.assertIn(elem, html_content, f"Missing required Task 3 element {elem} in index.html")


if __name__ == "__main__":
    unittest.main()


