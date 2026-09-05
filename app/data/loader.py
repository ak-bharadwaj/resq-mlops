"""Data loading, ID canonicalization, CP1252 parsing, and eligibility filtering."""
from __future__ import annotations

import datetime as dt
import logging
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

logger = logging.getLogger(__name__)

from app.data.schema import (
    ConflictingRecordError,
    FieldVisitsSchemaContract,
    GatewayMasterSchemaContract,
    MissingDataReason,
    SchemaValidationError,
    TelemetrySchemaContract,
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


def enforce_duplicate_policy(
    df: pd.DataFrame,
    key_cols: List[str],
    semantic_cols: Optional[List[str]] = None,
    source_name: str = "dataset",
) -> Tuple[pd.DataFrame, int]:
    """Formalized duplicate-record policy across all ingestion paths (Task 7 / Section 7A).

    Frozen Policy:
    - Exact/equivalent duplicate across semantic columns:
      deterministic deduplication (keep first occurrence, log count).
    - Same logical key (key_cols) + conflicting semantic values:
      BLOCK ingestion/evaluation by raising ConflictingRecordError.
      Never silently choose an arbitrary winner or average values.
    """
    if df.empty:
        return df, 0

    work_df = df
    if "canonical_id" not in work_df.columns and "gateway_id" in work_df.columns:
        work_df = work_df.copy()
        work_df["canonical_id"] = work_df["gateway_id"].apply(canonicalize_gateway_id)

    # Normalize key_cols to use canonical_id if gateway_id was specified
    resolved_key_cols = [
        "canonical_id" if (c == "gateway_id" and "canonical_id" in work_df.columns) else c
        for c in key_cols
    ]

    if semantic_cols is None:
        # Exclude raw formatting columns (gateway_id, and ts_utc if authoritative parsed ts is present)
        excluded = set()
        if "canonical_id" in work_df.columns and "gateway_id" in work_df.columns:
            excluded.add("gateway_id")
        if "ts" in work_df.columns and "ts_utc" in work_df.columns:
            excluded.add("ts_utc")
        semantic_cols = [c for c in work_df.columns if c not in excluded]

    exact_dup_mask = work_df.duplicated(subset=semantic_cols, keep="first")
    exact_dup_count = int(exact_dup_mask.sum())
    deduped = work_df.drop_duplicates(subset=semantic_cols, keep="first").copy()

    if exact_dup_count > 0:
        logger.info(
            "Duplicate policy [%s]: deterministically deduplicated %d exact/equivalent record(s)",
            source_name,
            exact_dup_count,
        )

    # Check for conflicting duplicates on logical key_cols
    key_dup_mask = deduped.duplicated(subset=resolved_key_cols, keep=False)
    if key_dup_mask.any():
        conflicts = deduped.loc[key_dup_mask].sort_values(by=resolved_key_cols)
        sample = conflicts[resolved_key_cols].head(4).to_dict(orient="records")
        if source_name == "gateway_master":
            msg = (
                f"Conflicting master records detected for canonical gateway ID(s): {sample}. "
                "Distinct records colliding on the same canonical ID BLOCK ingestion per frozen contract."
            )
        elif source_name == "field_visits":
            msg = (
                f"Conflicting visit records detected for visit_id(s): {sample}. "
                "Distinct records colliding on the same visit ID BLOCK ingestion per frozen contract."
            )
        elif source_name == "telemetry":
            msg = (
                f"Conflicting telemetry records detected for same gateway and timestamp: {sample}. "
                "Conflicting records BLOCK prediction per frozen Section 7A contract."
            )
        else:
            msg = (
                f"Conflicting records detected in {source_name} for logical key {resolved_key_cols}: {sample}. "
                "Conflicting records BLOCK ingestion per frozen duplicate-record contract. "
                "Never silently select an arbitrary winner."
            )
        raise ConflictingRecordError(msg)

    return deduped, exact_dup_count


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
    deduped, _ = enforce_duplicate_policy(
        df,
        key_cols=["canonical_id"],
        semantic_cols=semantic_cols,
        source_name="gateway_master",
    )

    return deduped



def verify_field_visits_encoding(data_dir: pathlib.Path) -> str:
    """Explicitly verify field_visits.csv encoding ahead of parsing.

    Reads raw bytes to verify UTF-8 or CP1252 compatibility.
    Fails closed if the encoding is unsupported or malformed.
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

    raise ValueError(
        f"Unsupported or malformed encoding in {path}. "
        "File must be encoded in valid UTF-8 or CP1252 per frozen contract."
    )


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

    # Enforce duplicate policy on logical key 'visit_id'
    semantic_cols = [c for c in df.columns if c != "gateway_id"]
    deduped, _ = enforce_duplicate_policy(
        df,
        key_cols=["visit_id"],
        semantic_cols=semantic_cols,
        source_name="field_visits",
    )

    return deduped



def get_gateway_eligibility(
    master_df: pd.DataFrame,
    monday: Any,
) -> pd.DataFrame:
    """Evaluate gateway eligibility for a given scored Monday.

    Frozen Contract:
    - installed_on <= Monday
      AND
      (decommissioned_on is null OR decommissioned_on > Monday)
    - Eligibility filtering is mandatory BEFORE feature construction and ranking;
      it is never inferred from telemetry presence or telemetry absence.
    - Tags each gateway with is_eligible (bool) and exclusion_reason (MissingDataReason | None).
    - Preserves canonical_id and all master attributes.
    """
    if master_df.empty:
        df = master_df.copy()
        df["is_eligible"] = pd.Series(dtype=bool)
        df["exclusion_reason"] = pd.Series(dtype=object)
        return df

    df = master_df.copy()
    if "canonical_id" not in df.columns and "gateway_id" in df.columns:
        df["canonical_id"] = df["gateway_id"].apply(canonicalize_gateway_id)

    # Normalize monday parameter to date midnight Timestamp (naive)
    if hasattr(monday, "date") and callable(getattr(monday, "date")):
        monday_date = monday.date()
    elif isinstance(monday, str):
        monday_date = pd.to_datetime(monday).date()
    else:
        monday_date = pd.to_datetime(monday).date()

    monday_ts = pd.Timestamp(monday_date)

    # Parse installed_on and decommissioned_on as naive date midnight Timestamps
    installed_ts = pd.to_datetime(df["installed_on"]).dt.tz_localize(None).dt.floor("D")
    if "decommissioned_on" in df.columns:
        decom_ts = pd.to_datetime(df["decommissioned_on"]).dt.tz_localize(None).dt.floor("D")
        not_decommissioned = decom_ts.isna() | (decom_ts > monday_ts)
    else:
        not_decommissioned = pd.Series(True, index=df.index)

    installed_eligible = installed_ts <= monday_ts
    is_eligible = installed_eligible & not_decommissioned

    df["is_eligible"] = is_eligible.astype(bool)
    df["exclusion_reason"] = [
        None if e else MissingDataReason.INELIGIBLE_DATE.value
        for e in df["is_eligible"]
    ]
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
        work_df["ts"] = pd.to_datetime(work_df["ts_utc"], utc=True, format="ISO8601")

    return enforce_duplicate_policy(
        work_df,
        key_cols=key_cols,
        source_name="telemetry",
    )


def _check_is_utc(dt_val: dt.datetime, param_name: str) -> None:
    """Strictly verify datetime parameter is timezone-aware and in UTC timezone."""
    if dt_val.tzinfo is None:
        raise ValueError(f"{param_name} must be a timezone-aware UTC datetime (got naive datetime)")
    offset = dt_val.utcoffset()
    if offset != dt.timedelta(0):
        raise ValueError(
            f"{param_name} must be in UTC timezone (got tzinfo={dt_val.tzinfo} with offset {offset})"
        )


def load_telemetry_window(
    data_dir: pathlib.Path,
    cutoff_utc: dt.datetime,
    start_utc: Optional[dt.datetime] = None,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Load telemetry strictly adhering to Monday 00:00 UTC cutoff.

    Leakage Firewall Contract:
    - FEATURE_CUTOFF is strictly Monday 00:00 UTC.
    - cutoff_utc and start_utc MUST be timezone-aware UTC datetimes (utcoffset == 0).
    - Path discovery fails closed (only data_dir/telemetry or data_dir/telemetry.parquet or explicit parquet file).
    - Enforces TelemetrySchemaContract on loaded DataFrame.
    - No record with ts >= cutoff_utc may ever be loaded or returned.
    - Half-open window: [start_utc, cutoff_utc).
    - Adds canonical_id column using canonicalize_gateway_id.
    - Column projection supports requesting derived 'canonical_id' and 'ts' without crashing parquet loader.
    """
    _check_is_utc(cutoff_utc, "cutoff_utc")
    if start_utc is not None:
        _check_is_utc(start_utc, "start_utc")

    if data_dir.is_file() and data_dir.suffix == ".parquet":
        telemetry_path = data_dir
    else:
        telemetry_path = data_dir / "telemetry"
        if not telemetry_path.exists():
            if (data_dir / "telemetry.parquet").exists():
                telemetry_path = data_dir / "telemetry.parquet"
            else:
                raise FileNotFoundError(
                    f"Telemetry path not found: Expected directory '{data_dir / 'telemetry'}' or file '{data_dir / 'telemetry.parquet'}'"
                )

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

    # Enforce authoritative model telemetry schema contract on incoming raw DataFrame
    contract = TelemetrySchemaContract.load_active_schema()
    contract.validate_or_raise(df, projected=(columns is not None))

    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601")

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

