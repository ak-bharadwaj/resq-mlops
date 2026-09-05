"""Schema definitions, validation contracts, and missing-data taxonomy."""
from __future__ import annotations

from enum import Enum
import json
import pathlib
from typing import Any, Dict, List, Tuple
import pandas as pd
from pydantic import BaseModel


class MissingDataReason(str, Enum):
    """Frozen missing-data reason taxonomy.

    Must remain distinct:
    - NO_TELEMETRY: Zero telemetry across complete eligible history.
    - INSUFFICIENT_HISTORY: Telemetry exists, but history is below baseline requirements.
    - INSUFFICIENT_FEATURE_DATA: Intermediate feature window is incomplete.
    - INELIGIBLE_DATE: Gateway is decommissioned or not yet installed on scored Monday.
    - SCHEMA_INVALID: Corrupt or missing required schema columns/dtypes.
    """
    NO_TELEMETRY = "NO_TELEMETRY"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_FEATURE_DATA = "INSUFFICIENT_FEATURE_DATA"
    INELIGIBLE_DATE = "INELIGIBLE_DATE"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class ConflictingRecordError(Exception):
    """Raised when conflicting records exist for the same (gateway_id, timestamp)."""
    pass


class SchemaValidationError(Exception):
    """Raised when incoming data violates the authoritative model schema."""
    pass


class TelemetrySchemaContract(BaseModel):
    """Model-specific telemetry contract loaded from models/<version>/schema.json or defaults."""
    required_columns: List[str] = ["gateway_id", "ts_utc"]
    dtypes: Dict[str, str] = {"gateway_id": "string", "ts_utc": "datetime"}
    time_grain: str = "hourly"
    timestamp_column: str = "ts_utc"

    @classmethod
    def load_from_model(cls, model_dir: pathlib.Path) -> "TelemetrySchemaContract":
        schema_path = model_dir / "schema.json"
        if not schema_path.exists():
            raise FileNotFoundError(f"Authoritative schema contract missing at {schema_path}")
        with open(schema_path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def validate_dataframe(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Validate incoming DataFrame against schema contract.

        Checks:
        1. All required columns exist.
        2. Timestamp column is present, parseable, and timezone-aware UTC.
        3. Column dtypes match expected types where verifiable.
        """
        errors: List[str] = []

        # 1. Required columns presence
        missing_cols = [c for c in self.required_columns if c not in df.columns]
        if missing_cols:
            errors.append(f"Missing required column(s): {missing_cols}")

        # If columns missing, cannot perform deeper checks reliably
        if errors:
            return False, errors

        # 2. Timestamp column validation
        ts_col = self.timestamp_column
        if ts_col in df.columns:
            ts_series = df[ts_col]
            if not pd.api.types.is_datetime64_any_dtype(ts_series):
                try:
                    ts_converted = pd.to_datetime(ts_series, utc=True, format="ISO8601")
                    if ts_converted.isna().any() and not ts_series.isna().all():
                        errors.append(f"{ts_col} contains unparseable timestamp values")
                except Exception as ex:
                    errors.append(f"{ts_col} failed UTC datetime parsing: {ex}")
            else:
                # Check timezone is UTC
                tz_str = str(getattr(ts_series.dt, "tz", None))
                if tz_str not in ("UTC", "datetime.timezone.utc"):
                    errors.append(f"{ts_col} must be timezone-aware UTC, got {ts_series.dt.tz}")

        # 3. Numeric dtypes validation
        for col, expected_dtype in self.dtypes.items():
            if col in df.columns and col != ts_col:
                if expected_dtype in ("float64", "int64", "numeric"):
                    if not pd.api.types.is_numeric_dtype(df[col]):
                        errors.append(f"Column '{col}' expected numeric dtype, got {df[col].dtype}")

        return len(errors) == 0, errors

    def validate_or_raise(self, df: pd.DataFrame) -> None:
        """Validate DataFrame and raise SchemaValidationError if invalid."""
        valid, errors = self.validate_dataframe(df)
        if not valid:
            raise SchemaValidationError(f"Telemetry schema validation failed: {errors}")


class GatewayMasterSchemaContract(BaseModel):

    """Authoritative schema contract for gateway_master.csv."""
    required_columns: List[str] = [
        "gateway_id",
        "tenant",
        "site_type",
        "region",
        "hw_model",
        "antenna_type",
        "fw_version",
        "installed_on",
        "n_meters_installed",
    ]

    def validate_dataframe(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Validate incoming gateway master DataFrame against schema contract invariants.

        Checks:
        1. Required columns presence:
           gateway_id, tenant, site_type, region, hw_model, antenna_type,
           fw_version, installed_on, n_meters_installed.
        2. Date logical ordering:
           installed_on <= decommissioned_on (if decommissioned_on is present and not null).
        3. Non-negative n_meters_installed:
           n_meters_installed >= 0.
        """
        errors: List[str] = []

        # 1. Required columns presence
        missing_cols = [c for c in self.required_columns if c not in df.columns]
        if missing_cols:
            errors.append(f"Missing required column(s): {missing_cols}")

        if errors:
            return False, errors

        # 2. Date logical ordering: installed_on <= decommissioned_on
        if "installed_on" in df.columns and "decommissioned_on" in df.columns:
            inst_ts = pd.to_datetime(df["installed_on"], errors="coerce")
            decom_ts = pd.to_datetime(df["decommissioned_on"], errors="coerce")

            # Missing or unparseable installed_on values
            if inst_ts.isna().any() and df["installed_on"].notna().any():
                errors.append("installed_on contains unparseable date values")

            # Logical ordering violation: installed_on > decommissioned_on
            invalid_dates = inst_ts.notna() & decom_ts.notna() & (inst_ts > decom_ts)
            if invalid_dates.any():
                violating_rows = df.loc[invalid_dates, ["gateway_id", "installed_on", "decommissioned_on"]].to_dict(orient="records")
                errors.append(f"Date ordering violation: installed_on > decommissioned_on for record(s): {violating_rows}")

        # 3. Non-negative n_meters_installed
        if "n_meters_installed" in df.columns:
            meters_numeric = pd.to_numeric(df["n_meters_installed"], errors="coerce")
            if meters_numeric.isna().any() and df["n_meters_installed"].notna().any():
                errors.append("n_meters_installed contains non-numeric values")
            elif (meters_numeric < 0).any():
                negative_rows = df.loc[meters_numeric < 0, ["gateway_id", "n_meters_installed"]].to_dict(orient="records")
                errors.append(f"n_meters_installed invariant violation (< 0) for record(s): {negative_rows}")

        return len(errors) == 0, errors


    def validate_or_raise(self, df: pd.DataFrame) -> None:
        """Validate DataFrame and raise SchemaValidationError if invalid."""
        valid, errors = self.validate_dataframe(df)
        if not valid:
            raise SchemaValidationError(f"Gateway master schema validation failed: {errors}")



class FieldVisitsSchemaContract(BaseModel):
    """Authoritative schema contract for field_visits.csv ingestion.

    Invariants:
    - Required columns present: visit_id, gateway_id, requested_on, visited_on,
      reason_reported, outcome, parts_replaced, technician_hours.
    - Non-null mandatory fields: visit_id, gateway_id, requested_on, visited_on.
    - Date logical ordering: requested_on <= visited_on.
    - Non-negative technician hours: technician_hours >= 0.0.
    """

    required_columns: List[str] = [
        "visit_id",
        "gateway_id",
        "requested_on",
        "visited_on",
        "reason_reported",
        "outcome",
        "parts_replaced",
        "technician_hours",
    ]

    def validate_dataframe(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Validate incoming field visits DataFrame against schema contract.

        Checks:
        1. Required columns presence.
        2. Non-null mandatory fields (visit_id, gateway_id, requested_on, visited_on).
        3. Non-negative technician_hours (>= 0.0).
        4. Date logical ordering (requested_on <= visited_on).
        """
        errors: List[str] = []

        # 1. Required columns presence
        missing_cols = [c for c in self.required_columns if c not in df.columns]
        if missing_cols:
            errors.append(f"Missing required column(s): {missing_cols}")
            return False, errors

        # 2. Check null values in mandatory identifier and date columns
        for col in ["visit_id", "gateway_id", "requested_on", "visited_on"]:
            if df[col].isna().any():
                errors.append(f"Column '{col}' contains missing/null values")

        # 3. Check technician_hours numeric and non-negative
        if "technician_hours" in df.columns:
            try:
                hours = pd.to_numeric(df["technician_hours"], errors="coerce")
                if hours.isna().any() and not df["technician_hours"].isna().all():
                    errors.append("technician_hours contains non-numeric values")
                elif (hours < 0.0).any():
                    errors.append("technician_hours must be non-negative (>= 0.0)")
            except Exception as ex:
                errors.append(f"technician_hours validation failed: {ex}")

        # 4. Check date logical ordering: requested_on <= visited_on
        try:
            req_dates = pd.to_datetime(df["requested_on"], errors="coerce")
            vis_dates = pd.to_datetime(df["visited_on"], errors="coerce")

            if req_dates.isna().any() and not df["requested_on"].isna().all():
                errors.append("requested_on contains unparseable date values")
            if vis_dates.isna().any() and not df["visited_on"].isna().all():
                errors.append("visited_on contains unparseable date values")

            if not req_dates.isna().any() and not vis_dates.isna().any():
                if (req_dates > vis_dates).any():
                    errors.append("Date logical ordering violated: requested_on > visited_on")
        except Exception as ex:
            errors.append(f"Date validation failed: {ex}")

        return len(errors) == 0, errors

    def validate_or_raise(self, df: pd.DataFrame) -> None:
        """Validate DataFrame and raise SchemaValidationError if invalid."""
        valid, errors = self.validate_dataframe(df)
        if not valid:
            raise SchemaValidationError(f"Field visits schema validation failed: {errors}")

    def validate(self, df: pd.DataFrame) -> None:
        """Alias for validate_or_raise."""
        self.validate_or_raise(df)

