"""Data loading, ID canonicalization, CP1252 parsing, and eligibility filtering."""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

from app.data.schema import (
    ConflictingRecordError,
    FieldVisitsSchemaContract,
    GatewayMasterSchemaContract,
    MissingDataReason,
    SchemaValidationError,
)


# Canonical Gateway ID: 12 uppercase hexadecimal characters, separators removed
BARE_12HEX_REGEX = re.compile(r"^[0-9A-Fa-f]{12}$")
COLON_12HEX_REGEX = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def canonicalize_gateway_id(raw_id: Any) -> str:
    """Canonicalize a gateway ID to 12 uppercase hex characters with separators removed.

    Frozen Contract:
    - 12 uppercase hexadecimal characters, separators removed.
    - Accepts bare 12-character hexadecimal IDs (e.g. '0639EA5602C1', '0639ea5602c1').
    - Accepts 6-octet colon-separated hexadecimal IDs (e.g. '06:39:EA:56:02:C1', '06:39:ea:56:02:c1').
    - Strips surrounding whitespace.
    - Normalizes lowercase to uppercase.
    - Removes permitted colon separators.
    - Rejects null, empty, whitespace-only, non-hex characters, incorrect length,
      or unauthorized separators (e.g. hyphens).
    - Fails deterministically rather than silently coercing malformed IDs.
    """
    if raw_id is None:
        raise ValueError("gateway_id cannot be null or empty")

    # Reject non-scalar structures (arrays, collections, Series) deterministically
    if isinstance(raw_id, (list, tuple, dict, set, pd.Series, pd.DataFrame)) or (
        hasattr(raw_id, "__len__") and not isinstance(raw_id, (str, bytes))
    ):
        raise ValueError(
            f"Invalid gateway ID format: '{raw_id}'. Expected bare 12-hex or 6-octet colon-separated hexadecimal."
        )

    try:
        if pd.isna(raw_id):
            raise ValueError("gateway_id cannot be null or empty")
    except (ValueError, TypeError):
        raise ValueError(
            f"Invalid gateway ID format: '{raw_id}'. Expected bare 12-hex or 6-octet colon-separated hexadecimal."
        )

    cleaned = str(raw_id).strip()
    if not cleaned:
        raise ValueError("gateway_id cannot be null or empty")

    if COLON_12HEX_REGEX.match(cleaned):
        return cleaned.replace(":", "").upper()
    if BARE_12HEX_REGEX.match(cleaned):
        return cleaned.upper()

    raise ValueError(
        f"Invalid gateway ID format: '{raw_id}'. Expected bare 12-hex or 6-octet colon-separated hexadecimal."
    )


def load_gateway_master(data_dir: pathlib.Path) -> pd.DataFrame:
    """Load gateway_master.csv using frozen CP1252 encoding.

    Invariants:
    - Encoded as cp1252 (handles German characters safely).
    - Preserves leading zeros in numeric IDs via dtype={"gateway_id": str}.
    - Adds canonical_id column using canonicalize_gateway_id.
    - Dates parsed as dt.date: installed_on (dt.date), decommissioned_on (Optional dt.date),
      fw_updated_on (Optional dt.date).
    - Enforces schema contract invariants via GatewayMasterSchemaContract.
    - Collision safety: equivalent representations across attributes are deduplicated safely;
      distinct records colliding on canonical_id raise ConflictingRecordError.
    """
    path = data_dir / "gateway_master.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing gateway_master.csv at {path}")

    df = pd.read_csv(path, encoding="cp1252", dtype={"gateway_id": str})
    df["canonical_id"] = df["gateway_id"].apply(canonicalize_gateway_id)

    if "installed_on" in df.columns:
        df["installed_on"] = pd.to_datetime(df["installed_on"]).dt.date
    if "decommissioned_on" in df.columns:
        df["decommissioned_on"] = pd.to_datetime(df["decommissioned_on"]).dt.date
    if "fw_updated_on" in df.columns:
        df["fw_updated_on"] = pd.to_datetime(df["fw_updated_on"]).dt.date

    # Validate schema contract invariants
    contract = GatewayMasterSchemaContract()
    contract.validate_or_raise(df)

    # Collision safety: Check for equivalent vs distinct collisions on canonical_id
    semantic_cols = [c for c in df.columns if c != "gateway_id"]
    deduped = df.drop_duplicates(subset=semantic_cols, keep="first").copy()

    if deduped["canonical_id"].duplicated().any():
        conflicts = deduped.loc[deduped["canonical_id"].duplicated(keep=False)].sort_values(by="canonical_id")
        sample = conflicts[["canonical_id"]].head(4).to_dict(orient="records")
        raise ConflictingRecordError(
            f"Conflicting master records detected for canonical gateway ID(s): {sample}. "
            "Distinct records colliding on the same canonical ID BLOCK ingestion per frozen contract."
        )

    return deduped



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
    """Load field_visits.csv with verified encoding.

    Invariants:
    - Encoding explicitly verified (UTF-8 / CP1252 / latin-1).
    - String dtypes preserved via dtype={"gateway_id": str, "visit_id": str}.
    - Schema validation via FieldVisitsSchemaContract.
    - Adds canonical_id column using canonicalize_gateway_id.
    - Dates parsed as dt.date.
    - Invariants enforced: requested_on <= visited_on, technician_hours >= 0.0.
    - Collision safety: equivalent representations across visit attributes are deduplicated safely;
      distinct records colliding on visit_id raise ConflictingRecordError.
    """
    path = data_dir / "field_visits.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing field_visits.csv at {path}")

    encoding = verify_field_visits_encoding(data_dir)
    df = pd.read_csv(path, encoding=encoding, dtype={"gateway_id": str, "visit_id": str})

    # Validate against authoritative FieldVisitsSchemaContract
    contract = FieldVisitsSchemaContract()
    contract.validate(df)

    # Canonicalize gateway ID
    df["canonical_id"] = df["gateway_id"].apply(canonicalize_gateway_id)

    # Parse date fields as datetime.date
    df["requested_on"] = pd.to_datetime(df["requested_on"]).dt.date
    df["visited_on"] = pd.to_datetime(df["visited_on"]).dt.date

    # Enforce date logical ordering: requested_on <= visited_on
    if (df["requested_on"] > df["visited_on"]).any():
        raise SchemaValidationError("Date logical ordering violated: requested_on > visited_on")

    # Enforce technician_hours >= 0.0
    if (df["technician_hours"] < 0.0).any():
        raise SchemaValidationError("technician_hours must be non-negative (>= 0.0)")

    # Collision safety: Check for equivalent vs distinct duplicate visits
    semantic_cols = [c for c in df.columns if c != "gateway_id"]
    deduped = df.drop_duplicates(subset=semantic_cols, keep="first").copy()

    if "visit_id" in deduped.columns and deduped["visit_id"].duplicated().any():
        conflicts = deduped.loc[deduped["visit_id"].duplicated(keep=False)].sort_values(by="visit_id")
        sample = conflicts[["visit_id", "canonical_id"]].head(4).to_dict(orient="records")
        raise ConflictingRecordError(
            f"Conflicting visit records detected for visit_id(s): {sample}. "
            "Distinct records colliding on the same visit ID BLOCK ingestion per frozen contract."
        )

    return deduped



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
    - Exact duplicate records across all columns (or equivalent representations across
      all semantic columns other than raw formatting): follow deterministic frozen rule
      (keep first occurrence, log count).
    - Conflicting records for same key_cols (default: canonical_id, timestamp) with differing values:
      must BLOCK prediction/evaluation by raising ConflictingRecordError. Never silently choose.
    """
    if df.empty:
        return df, 0

    work_df = df
    if "canonical_id" not in work_df.columns and "gateway_id" in work_df.columns:
        work_df = work_df.copy()
        work_df["canonical_id"] = work_df["gateway_id"].apply(canonicalize_gateway_id)

    if "ts" not in work_df.columns and "ts_utc" in work_df.columns:
        if work_df is df:
            work_df = work_df.copy()
        work_df["ts"] = pd.to_datetime(work_df["ts_utc"], utc=True)

    # 1. Check exact duplicates / equivalent representations across all semantic columns
    # Exclude raw formatting columns (gateway_id, and ts_utc if authoritative parsed ts is present)
    excluded = {"gateway_id"}
    if "ts" in work_df.columns and "ts_utc" in work_df.columns:
        excluded.add("ts_utc")
    semantic_cols = [c for c in work_df.columns if c not in excluded]

    exact_dup_mask = work_df.duplicated(subset=semantic_cols, keep="first")
    exact_dup_count = int(exact_dup_mask.sum())
    deduped = work_df.drop_duplicates(subset=semantic_cols, keep="first").copy()

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
    - Adds canonical_id column using canonicalize_gateway_id.
    - Column projection supports requesting derived 'canonical_id' and 'ts' without crashing parquet loader.
    """
    if cutoff_utc.tzinfo is None:
        raise ValueError("cutoff_utc must be a timezone-aware UTC datetime")
    if start_utc is not None and start_utc.tzinfo is None:
        raise ValueError("start_utc must be a timezone-aware UTC datetime")

    telemetry_path = data_dir / "telemetry"
    if not telemetry_path.exists():
        if (data_dir / "telemetry.parquet").exists():
            telemetry_path = data_dir / "telemetry.parquet"
        elif data_dir.is_dir() and len(list(data_dir.glob("*.parquet"))) > 0:
            telemetry_path = data_dir
        elif data_dir.suffix == ".parquet" and data_dir.exists():
            telemetry_path = data_dir
        else:
            raise FileNotFoundError(f"Telemetry path not found: {telemetry_path}")

    # If columns specified, separate physical parquet columns from derived columns ('canonical_id', 'ts')
    cols = None
    if columns is not None:
        physical_cols = [c for c in columns if c not in ("canonical_id", "ts")]
        for req in ["gateway_id", "ts_utc"]:
            if req not in physical_cols:
                physical_cols.append(req)
        cols = physical_cols

    # Read parquet partitions
    df = pd.read_parquet(telemetry_path, columns=cols)
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)

    # Apply strict temporal firewall BEFORE canonicalization to avoid wasteful compute
    mask = df["ts"] < cutoff_utc
    if start_utc is not None:
        mask = mask & (df["ts"] >= start_utc)

    window_df = df.loc[mask].copy()
    window_df["canonical_id"] = window_df["gateway_id"].apply(canonicalize_gateway_id)

    # Resolve duplicates deterministically
    deduped_df, _ = resolve_telemetry_duplicates(window_df, key_cols=["canonical_id", "ts"])

    if columns is not None:
        # Retain requested columns that exist in deduped_df
        requested_present = [c for c in columns if c in deduped_df.columns]
        return deduped_df[requested_present]

    return deduped_df

