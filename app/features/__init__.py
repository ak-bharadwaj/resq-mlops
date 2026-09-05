"""Features module per v25 architecture contracts."""
from app.features.definitions import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_METRICS,
    DEFAULT_RECENT_DAYS,
    DEFAULT_SIGMA,
    EXPECTED_HOURS_WEEK,
    GatewayFeatures,
)
from app.features.build import extract_candidate_features
from app.features.holdout import (
    check_gateway_holdout,
    freeze_group_holdout_ids,
    load_group_holdout_ids,
)

__all__ = [
    "DEFAULT_BASELINE_DAYS",
    "DEFAULT_METRICS",
    "DEFAULT_RECENT_DAYS",
    "DEFAULT_SIGMA",
    "EXPECTED_HOURS_WEEK",
    "GatewayFeatures",
    "extract_candidate_features",
    "check_gateway_holdout",
    "freeze_group_holdout_ids",
    "load_group_holdout_ids",
]
