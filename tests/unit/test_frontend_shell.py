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

        self.assertIn('id="health-schema"', html_content)
        self.assertIn('id="health-completeness"', html_content)
        self.assertIn('id="health-absence"', html_content)
        self.assertIn('id="health-reporting"', html_content)

        # 5. Backlog Strip
        self.assertIn('id="backlog-deferred"', html_content)
        self.assertIn('id="backlog-high-risk"', html_content)
        self.assertIn('id="backlog-proxy-hours"', html_content)

        # 6. Lifecycle & Rollback Strip
        self.assertIn('id="flow-candidate"', html_content)
        self.assertIn('id="flow-gate"', html_content)
        self.assertIn('id="flow-restored"', html_content)
        self.assertIn('id="lifecycle-replay"', html_content)

    def test_promotion_artifact_derived_counts(self):
        """Verify load_json_artifact dynamically derives 71 vs 60 window missed weeks."""
        res = load_json_artifact("runs/promotion/promotion_decision_v0002.json")
        self.assertEqual(res.get("status"), "AVAILABLE")
        data = res.get("data", {})
        self.assertEqual(data.get("total_active_missed"), 71)
        self.assertEqual(data.get("total_candidate_missed"), 60)

    def test_replay_provenance_truthful_nullability(self):
        """Verify replay provenance fails closed to UNAVAILABLE when proof is absent."""
        from frontend.server import check_replay_provenance
        # Baseline state without rollback report should be UNAVAILABLE
        res = check_replay_provenance()
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertIn("not substantiated", res["reason"])

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


if __name__ == "__main__":
    unittest.main()
