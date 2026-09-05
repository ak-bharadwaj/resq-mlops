"""Feature definitions and taxonomy per Rule 6 and v25 Sections 2B, 3, and 6.

Frozen signals:
1. flagged_hours: 3-sigma anomaly persistence over trailing 28-day baseline in trailing 7-day window.
2. norm_anomaly: min(flagged_hours / 168.0, 1.0) scaling anomaly persistence into [0.0, 1.0].
3. recent_silence_ratio: missing expected hourly observations in trailing 7-day window / 168.0.
   - Total silence (0 hours in trailing 7 days, prior history exists) -> 1.0.
   - Complete reporting (168+ hours) -> 0.0.
   - Institutional non-coverage (0 hours in complete 28-day history) -> excluded with NO_TELEMETRY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


EXPECTED_HOURS_WEEK: int = 168
DEFAULT_BASELINE_DAYS: int = 28
DEFAULT_RECENT_DAYS: int = 7
DEFAULT_SIGMA: float = 3.0
DEFAULT_METRICS: list[str] = ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]


@dataclass(frozen=True)
class GatewayFeatures:
    """Structured candidate feature representation for a single gateway-week."""

    gateway_id: str
    flagged_hours: float
    norm_anomaly: float
    recent_silence_ratio: float
    worst_metric: str
    baseline_observed_hours: int
    recent_observed_hours: int
    status: str  # "VALID", "NO_TELEMETRY", "INSUFFICIENT_HISTORY"
    exclusion_reason: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "gateway_id": self.gateway_id,
            "flagged_hours": float(self.flagged_hours),
            "norm_anomaly": float(self.norm_anomaly),
            "recent_silence_ratio": float(self.recent_silence_ratio),
            "worst_metric": self.worst_metric,
            "baseline_observed_hours": int(self.baseline_observed_hours),
            "recent_observed_hours": int(self.recent_observed_hours),
            "status": self.status,
            "exclusion_reason": self.exclusion_reason,
        }
