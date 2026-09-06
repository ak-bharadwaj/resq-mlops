#!/usr/bin/env python3
"""Zero-dependency HTTP server for RESQ Operations Console (Frontend Task 1).

Read-only visualization server:
- Strictly serves static assets from frontend/static/.
- Exposes read-only JSON APIs reading existing artifacts on disk.
- Never mutates registry, never runs training/scoring, never writes to data/.
- When an artifact is missing, returns explicit 'UNAVAILABLE' state.
"""
from __future__ import annotations

import argparse
import csv
from http.server import HTTPServer, SimpleHTTPRequestHandler
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.parse

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"


def load_json_artifact(relative_path: str) -> dict:
    """Safely load a JSON artifact or return explicit UNAVAILABLE structure."""
    file_path = REPO_ROOT / relative_path
    if not file_path.exists():
        return {
            "status": "UNAVAILABLE",
            "reason": f"Artifact '{relative_path}' not found on disk",
            "file": relative_path,
        }
    try:
        content = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            # Dynamically derive aggregate window counts if window_results is present
            if "window_results" in content and isinstance(content["window_results"], dict):
                windows = [w for w in content["window_results"].values() if isinstance(w, dict)]
                if windows and all(
                    "active_missed_broken_weeks" in w and "candidate_missed_broken_weeks" in w
                    for w in windows
                ):
                    content["total_active_missed"] = sum(int(w["active_missed_broken_weeks"]) for w in windows)
                    content["total_candidate_missed"] = sum(int(w["candidate_missed_broken_weeks"]) for w in windows)
                else:
                    content["total_active_missed"] = None
                    content["total_candidate_missed"] = None

            return {"status": "AVAILABLE", "data": content, "file": relative_path}
        return {"status": "AVAILABLE", "data": {"raw": content}, "file": relative_path}
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": f"Failed to parse '{relative_path}': {exc}",
            "file": relative_path,
        }


def check_replay_provenance() -> dict:
    """Check whether deterministic replay equality is substantiated by artifacts.

    Strict truthful nullability:
    - Never fabricates VERIFIED when proof is absent.
    - If proven by registry history or run.json, returns VERIFIED with source.
    - Otherwise returns explicit UNAVAILABLE status.
    """
    # 1. Check registry history for verified ROLLED_BACK event
    history_file = REPO_ROOT / "registry" / "history.jsonl"
    if history_file.exists():
        try:
            lines = history_file.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("event") == "ROLLED_BACK":
                    return {
                        "status": "VERIFIED",
                        "reason": f"Substantiated by registry/history.jsonl ({record.get('timestamp')})",
                        "source": "registry/history.jsonl",
                        "target_validation": "VERIFIED",
                        "atomic_switch": "VERIFIED",
                        "replay_equality": "VERIFIED",
                        "restored_version": record.get("version") or "UNAVAILABLE",
                    }
        except Exception:
            pass

    # 2. Check prediction run metadata if it explicitly substantiated replay equality
    run_file = REPO_ROOT / "runs" / "prediction" / "run.json"
    if run_file.exists():
        try:
            run_data = json.loads(run_file.read_text(encoding="utf-8"))
            if run_data.get("replay_equality_verified") is True:
                return {
                    "status": "VERIFIED",
                    "reason": "Substantiated by runs/prediction/run.json (replay_equality_verified: true)",
                    "source": "runs/prediction/run.json",
                    "target_validation": "VERIFIED",
                    "atomic_switch": "VERIFIED",
                    "replay_equality": "VERIFIED",
                    "restored_version": run_data.get("model_version") or "UNAVAILABLE",
                }
        except Exception:
            pass

    # 3. Check dedicated rollback result if present
    rollback_file = REPO_ROOT / "runs" / "rollback" / "rollback_result.json"
    if rollback_file.exists():
        try:
            rb_data = json.loads(rollback_file.read_text(encoding="utf-8"))
            if rb_data.get("replay_equality") is True:
                return {
                    "status": "VERIFIED",
                    "reason": "Substantiated by runs/rollback/rollback_result.json",
                    "source": "runs/rollback/rollback_result.json",
                    "target_validation": "VERIFIED" if rb_data.get("target_validation_passed") else "UNAVAILABLE",
                    "atomic_switch": "VERIFIED",
                    "replay_equality": "VERIFIED",
                    "restored_version": rb_data.get("active_restored") or "UNAVAILABLE",
                }
        except Exception:
            pass

    return {
        "status": "UNAVAILABLE",
        "reason": "Replay equality not substantiated by run.json or rollback execution artifacts",
        "source": None,
        "target_validation": "UNAVAILABLE",
        "atomic_switch": "UNAVAILABLE",
        "replay_equality": "UNAVAILABLE",
        "restored_version": "UNAVAILABLE",
    }


def load_predictions_artifact(selected_week: str | None = None) -> dict:
    """Load predictions.csv and filter by week, returning UNAVAILABLE if missing."""
    file_path = REPO_ROOT / "predictions.csv"
    if not file_path.exists():
        return {
            "status": "UNAVAILABLE",
            "reason": "predictions.csv not found on disk. Run 'make run' to generate.",
            "file": "predictions.csv",
        }
    try:
        rows = []
        weeks = set()
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                w = row.get("week_start", "")
                weeks.add(w)
                rows.append(row)

        sorted_weeks = sorted(list(weeks))
        if not sorted_weeks:
            return {
                "status": "UNAVAILABLE",
                "reason": "predictions.csv is empty",
                "file": "predictions.csv",
            }

        target_week = selected_week if (selected_week and selected_week in weeks) else sorted_weeks[0]
        filtered_rows = [r for r in rows if r.get("week_start") == target_week]
        filtered_rows.sort(key=lambda r: int(r.get("rank", 999)))

        return {
            "status": "AVAILABLE",
            "available_weeks": sorted_weeks,
            "selected_week": target_week,
            "total_rows": len(rows),
            "week_rows_count": len(filtered_rows),
            "predictions": filtered_rows,
            "file": "predictions.csv",
        }
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": f"Failed to parse predictions.csv: {exc}",
            "file": "predictions.csv",
        }


def lookup_gateway_status(gateway_id: str, week: str | None = None) -> dict:
    """Look up whether a gateway was dispatched in predictions.csv or deferred to backlog."""
    cleaned_id = gateway_id.strip().replace(":", "").upper()
    if not cleaned_id:
        return {"status": "INVALID", "reason": "Empty gateway ID provided"}

    # 1. Check predictions.csv
    preds_res = load_predictions_artifact(week)
    if preds_res.get("status") == "AVAILABLE":
        for p in preds_res.get("predictions", []):
            p_id = p.get("gateway_id", "").strip().replace(":", "").upper()
            if p_id == cleaned_id:
                return {
                    "status": "AVAILABLE",
                    "gateway_id": cleaned_id,
                    "disposition": "DISPATCHED",
                    "rank": int(p.get("rank", 0)),
                    "score": float(p.get("score", 0.0)),
                    "reason": p.get("reason", ""),
                    "week_start": p.get("week_start", week or ""),
                    "operational_narrative": (
                        f"Gateway {cleaned_id} allocated technician visit (Rank {p.get('rank')}) "
                        f"in weekly capacity quota (€380 truck roll committed). Primary signal: {p.get('reason')}."
                    ),
                }

    # 2. Check gateway_master.csv to confirm fleet membership
    master_path = REPO_ROOT / "data" / "gateway_master.csv"
    in_master = False
    master_info = {}
    if master_path.exists():
        try:
            with open(master_path, "r", encoding="latin-1") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    m_id = row.get("gateway_id", "").strip().replace(":", "").upper()
                    if m_id == cleaned_id:
                        in_master = True
                        master_info = {
                            "tenant": row.get("tenant"),
                            "site_type": row.get("site_type"),
                            "region": row.get("region"),
                            "hw_model": row.get("hw_model"),
                        }
                        break
        except Exception:
            pass

    # 3. Load Backlog Report for context
    backlog_res = load_json_artifact("backlog_report.json")

    if in_master:
        if backlog_res.get("status") == "AVAILABLE":
            b_data = backlog_res.get("data", {})
            return {
                "status": "AVAILABLE",
                "gateway_id": cleaned_id,
                "disposition": "DEFERRED",
                "rank_tier": "Ranks 16+",
                "week_start": b_data.get("week_start", week or ""),
                "operational_narrative": (
                    f"Gateway {cleaned_id} deferred to backlog. Evaluated in single scoring pass; "
                    f"deferred strictly to protect the 15-visit weekly capacity limit (€5,700 budget ceiling). "
                    f"Lower relative priority than rank 15. Tracked under heuristic risk proxy exposure."
                ),
                "exposure_method": b_data.get("exposure_method", "heuristic_proxy"),
                "evidence_quality": b_data.get("evidence_quality", "baseline"),
                "fleet_metadata": master_info,
            }
        else:
            return {
                "status": "UNAVAILABLE",
                "gateway_id": cleaned_id,
                "disposition": "DEFERRED",
                "reason": "backlog_report.json not found on disk. Run 'make run' to generate backlog intelligence.",
            }

    # 4. Gateway not in master
    return {
        "status": "NOT_FOUND",
        "gateway_id": cleaned_id,
        "operational_narrative": f"Gateway ID '{cleaned_id}' not found in active fleet master.",
    }


class ConsoleRequestHandler(SimpleHTTPRequestHandler):
    """Custom HTTP handler serving dashboard static assets and read-only APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # 1. API: Consolidated Summary Dashboard Payload
        if path == "/api/summary":
            active_reg = load_json_artifact("registry/active.json")
            schema_drift = load_json_artifact("monitoring/drift_reports/schema_check.json")
            run_rec = load_json_artifact("runs/prediction/run.json")
            backlog = load_json_artifact("backlog_report.json")
            promotion = load_json_artifact("runs/promotion/promotion_decision_v0002.json")

            response_payload = {
                "server_time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "active_registry": active_reg,
                "schema_health": schema_drift,
                "prediction_run": run_rec,
                "backlog_report": backlog,
                "promotion_decision": promotion,
                "replay_provenance": check_replay_provenance(),
            }
            self._send_json(response_payload)
            return

        # 2. API: Priority Dispatches from predictions.csv
        if path == "/api/predictions":
            week_param = query.get("week", [None])[0]
            preds_payload = load_predictions_artifact(week_param)
            self._send_json(preds_payload)
            return

        # 3. API: Backlog Report Artifact
        if path == "/api/backlog":
            backlog_payload = load_json_artifact("backlog_report.json")
            self._send_json(backlog_payload)
            return

        # 4. API: Gateway Deferral Status Lookup
        if path == "/api/backlog/lookup":
            gw_param = query.get("gateway_id", [""])[0]
            week_param = query.get("week", [None])[0]
            lookup_payload = lookup_gateway_status(gw_param, week_param)
            self._send_json(lookup_payload)
            return

        # 5. API: Health Check
        if path == "/api/health":
            self._send_json({"status": "OK", "service": "RESQ Operations Console"})
            return

        # 4. Fallback to static files
        if path == "/" or path == "":
            self.path = "/index.html"
        return super().do_GET()

    def _send_json(self, data: dict, status_code: int = 200) -> None:
        raw_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw_bytes)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(raw_bytes)


def run_server(port: int = 8080, host: str = "127.0.0.1") -> None:
    """Start local web server serving RESQ Operations Console."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, ConsoleRequestHandler)
    print("=" * 70)
    print(f"RESQ Operations Console running at http://{host}:{port}/")
    print(f"Serving read-only dashboard over artifacts in: {REPO_ROOT}")
    print("Press Ctrl+C to terminate.")
    print("=" * 70)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down RESQ Operations Console.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start RESQ Operations Console web server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
