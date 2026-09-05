"""Grouped holdout management and protection per Rule 8 and v25 Section 8.

v25 Specification:
- A fixed GROUP_HOLDOUT_IDS set is generated and frozen before feature discovery
  and configuration/weight selection.
- Those IDs are excluded from the four-hour EDA and from every candidate-construction/training
  computation in all rolling windows.
- They are scored only after v0002 is frozen.
- Accessing holdouts during development/training without explicit authorization
  raises HoldoutAccessError.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Optional, Set

from app.data.quality import HoldoutAccessError, HoldoutProtection


DEFAULT_HOLDOUT_PATH = pathlib.Path("registry/grouped_holdout.json")


def load_group_holdout_ids(holdout_path: Optional[pathlib.Path] = None) -> Set[str]:
    """Load the canonical frozen group holdout gateway IDs.

    Args:
        holdout_path: Path to the grouped holdout JSON artifact (defaults to registry/grouped_holdout.json).

    Returns:
        Set of canonical 12-hex gateway IDs reserved exclusively for holdout evaluation.
    """
    path = holdout_path or DEFAULT_HOLDOUT_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Grouped holdout registry file not found at {path}. "
            "The holdout set must be frozen before candidate development or training."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    holdout_ids = set(data.get("group_holdout_ids", []))
    return holdout_ids


def freeze_group_holdout_ids(
    canonical_gateway_ids: list[str],
    holdout_path: Optional[pathlib.Path] = None,
    modulo: int = 5,
) -> Set[str]:
    """Deterministically partition and freeze the canonical group holdout IDs.

    Uses SHA-256 cryptographic partition over sorted canonical IDs.
    Once written, the file is immutable and governs all rolling window evaluations.
    """
    path = holdout_path or DEFAULT_HOLDOUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    sorted_gids = sorted(set(canonical_gateway_ids))
    holdout_ids: list[str] = []

    for gid in sorted_gids:
        digest = hashlib.sha256(f"holdout:{gid}".encode("utf-8")).hexdigest()
        if int(digest, 16) % modulo == 0:
            holdout_ids.append(gid)

    record = {
        "holdout_version": "v1",
        "description": "Canonical frozen grouped holdout gateways per ARCHITECTURE_v25_FREEZE.md Section 8 and Rule 8",
        "created_at_utc": "2026-09-05T00:00:00Z",
        "total_fleet_gateways": len(sorted_gids),
        "holdout_gateway_count": len(holdout_ids),
        "group_holdout_ids": sorted(holdout_ids),
    }

    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return set(holdout_ids)


def check_gateway_holdout(
    gateway_id: str,
    holdout_ids: Set[str],
    allow_holdout: bool = False,
) -> None:
    """Verify that gateway_id does not leak into development or candidate training."""
    HoldoutProtection.check_gateway_access(
        gateway_id=gateway_id,
        holdout_gateways=holdout_ids,
        allow_holdout=allow_holdout,
    )
