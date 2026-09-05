"""Data loading, ID canonicalization, CP1252 parsing, and eligibility filtering."""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

from app.data.schema import ConflictingRecordError, MissingDataReason

# Canonical Gateway ID: 12 uppercase hexadecimal characters, separators removed
BARE_12HEX_REGEX = re.compile(r"^[0-9A-Fa-f]{12}$")
COLON_12HEX_REGEX = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def canonicalize_gateway_id(raw_id: Any) -> str:
    """Canonicalize a gateway ID to 12 uppercase hex characters with separators removed.

    Accepts:
    - 12 hex characters bare (e.g. '0639EA5602C1')
    - 6 octets colon-separated (e.g. '06:39:EA:56:02:C1')
    - Mixed case or leading/trailing whitespace

    Rejects:
    - Non-hex characters
    - Length != 12 after normalization
    """
    if raw_id is None or pd.isna(raw_id):
        raise ValueError("gateway_id cannot be null or empty")

    cleaned = str(raw_id).strip()
    if COLON_12HEX_REGEX.match(cleaned):
        return cleaned.replace(":", "").upper()
    if BARE_12HEX_REGEX.match(cleaned):
        return cleaned.upper()

    # If format doesn't match standard patterns, check if stripping colons/hyphens gives 12 hex
    normalized = re.sub(r"[:-]", "", cleaned).upper()
    if len(normalized) == 12 and BARE_12HEX_REGEX.match(normalized):
        return normalized

    raise ValueError(
        f"Invalid gateway ID format: '{raw_id}'. Expected 12 hexadecimal characters or colon-separated octets."
    )


def load_gateway_master(data_dir: pathlib.Path) -> pd.DataFrame:
    """Load gateway_master.csv using frozen CP1252 encoding.

    Invariants:
    - Encoded as cp1252 (handles German characters safely).
    - Adds canonical_id column.
    - Dates parsed as dt.date.
    """
    path = data_dir / "gateway_master.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing gateway_master.csv at {path}")

    df = pd.read_csv(path, encoding="cp1252")
    df["canonical_id"] = df["gateway_id"].apply(canonicalize_gateway_id)
    df["installed_on"] = pd.to_datetime(df["installed_on"]).dt.date
    df["decommissioned_on"] = pd.to_datetime(df["decommissioned_on"]).dt.date
    return df


def verify_field_visits_encoding(data_dir: pathlib.Path) -> str:
    """Explicitly verify field_visits.csv encoding ahead of parsing.

    Reads raw bytes to verify UTF-8 or CP1252 compatibility.
    Returns the verified encoding name.
    """
    path = data_dir / "field_visits.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing field_visits.csv at {path}")

    raw_bytes = path.read_bytes()
    # Test UTF-8 first
    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Test CP1252
    try:
        raw_bytes.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        pass

    return "latin-1"


def load_field_visits(data_dir: pathlib.Path) -> pd.DataFrame:
    """Load field_visits.csv with verified encoding."""
    path = data_dir / "field_visits.csv"
    encoding = verify_field_visits_encoding(data_dir)
    df = pd.read_csv(path, encoding=encoding)
    df["canonical_id"] = df["gateway_id"].apply(canonicalize_gateway_id)
    df["requested_on"] = pd.to_datetime(df["requested_on"]).dt.date
    df["visited_on"] = pd.to_datetime(df["visited_on"]).dt.date
    return df


def get_gateway_eligibility(
    master_df: pd.DataFrame,
    monday: dt.date,
) -> pd.DataFrame:
    """Evaluate gateway eligibility for a given scored Monday.

    Frozen Contract:
    - installed_on <= Monday
      AND
      (decommissioned_on is null OR decommissioned_on > Monday)
    - Eligibility filtering is mandatory BEFORE feature construction and ranking;
      it is never inferred from telemetry presence.
    - Tags each gateway with is_eligible (bool) and exclusion_reason (MissingDataReason | None).
    """
    df = master_df.copy()
    installed_ts = pd.to_datetime(df["installed_on"])
    decom_ts = pd.to_datetime(df["decommissioned_on"])
    monday_ts = pd.to_datetime(monday)
    installed = installed_ts <= monday_ts
    not_decommissioned = decom_ts.isna() | (decom_ts > monday_ts)
    is_eligible = installed & not_decommissioned

    df["is_eligible"] = is_eligible

    def assign_reason(row: pd.Series) -> Optional[str]:
        if row["is_eligible"]:
            return None
        return MissingDataReason.INELIGIBLE_DATE.value

    df["exclusion_reason"] = df.apply(assign_reason, axis=1)
    return df


def resolve_telemetry_duplicates(
    df: pd.DataFrame,
    key_cols: List[str] = ["canonical_id", "ts"],
) -> Tuple[pd.DataFrame, int]:
    """Resolve duplicates per frozen telemetry contract (Section 7A).

    Semantics:
    - Exact duplicate records across all columns: follow deterministic frozen rule
      (keep first occurrence, log count).
    - Conflicting records for same (gateway_id, timestamp) with differing values:
      must BLOCK prediction/evaluation by raising ConflictingRecordError. Never silently choose.
    """
    if df.empty:
        return df, 0

    # 1. Check exact duplicates
    exact_dup_mask = df.duplicated(keep="first")
    exact_dup_count = int(exact_dup_mask.sum())
    deduped = df.drop_duplicates(keep="first").copy()

    # 2. Check for conflicting duplicates on key_cols
    key_dup_mask = deduped.duplicated(subset=key_cols, keep=False)
    if key_dup_mask.any():
        conflicts = deduped.loc[key_dup_mask].sort_values(by=key_cols)
        sample = conflicts[key_cols].head(4).to_dict(orient="records")
        raise ConflictingRecordError(
            f"Conflicting telemetry records detected for same gateway and timestamp: {sample}. "
            "Conflicting records BLOCK prediction per frozen Section 7A contract."
        )

    return deduped, exact_dup_count


def load_telemetry_window(
    data_dir: pathlib.Path,
    cutoff_utc: dt.datetime,
    start_utc: Optional[dt.datetime] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Load telemetry strictly adhering to Monday 00:00 UTC cutoff.

    Leakage Firewall Contract:
    - FEATURE_CUTOFF is strictly Monday 00:00 UTC.
    - No record with ts >= cutoff_utc may ever be loaded or returned.
    - Half-open window: [start_utc, cutoff_utc).
    """
    if cutoff_utc.tzinfo is None:
        raise ValueError("cutoff_utc must be a timezone-aware UTC datetime")

    telemetry_path = data_dir / "telemetry"
    if not telemetry_path.exists():
        raise FileNotFoundError(f"Telemetry path not found: {telemetry_path}")

    # If columns specified, ensure gateway_id and ts_utc are included
    cols = None
    if columns is not None:
        cols = list(columns)
        for req in ["gateway_id", "ts_utc"]:
            if req not in cols:
                cols.append(req)

    # Read parquet partitions
    df = pd.read_parquet(telemetry_path, columns=cols)
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["canonical_id"] = df["gateway_id"].apply(canonicalize_gateway_id)

    # Apply strict temporal firewall
    mask = df["ts"] < cutoff_utc
    if start_utc is not None:
        if start_utc.tzinfo is None:
            raise ValueError("start_utc must be a timezone-aware UTC datetime")
        mask = mask & (df["ts"] >= start_utc)

    window_df = df.loc[mask].copy()

    # Resolve duplicates deterministically
    deduped_df, _ = resolve_telemetry_duplicates(window_df, key_cols=["canonical_id", "ts"])
    return deduped_df
