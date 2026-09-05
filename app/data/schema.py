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

    @classmethod
    def load_active_schema(
        cls,
        models_dir: pathlib.Path = pathlib.Path("models"),
        registry_path: pathlib.Path = pathlib.Path("registry/active.json"),
        baseline_path: pathlib.Path = pathlib.Path("monitoring/schema_baseline.json"),
    ) -> "TelemetrySchemaContract":
        """Load authoritative model schema contract based on registry/active.json.

        Rule: models/<version>/schema.json is authoritative once model artifacts exist.
        monitoring/schema_baseline.json must never override it.
        Fail closed: if an active model/version is registered, any failure to load its
        authoritative schema contract MUST raise SchemaValidationError, never silently
        falling back to default or baseline schemas.
        """
        if registry_path.exists():
            try:
                with open(registry_path, encoding="utf-8") as f:
                    active = json.load(f)
            except Exception as ex:
                raise SchemaValidationError(
                    f"Active model registry at '{registry_path}' is unreadable or corrupt JSON: {ex}"
                ) from ex

            if not isinstance(active, dict) or "production_version" not in active:
                raise SchemaValidationError(
                    f"Active model registry at '{registry_path}' is invalid: missing required 'production_version' field."
                )

            active_version = active["production_version"]
            model_dir = models_dir / active_version
            if not model_dir.exists():
                raise SchemaValidationError(
                    f"Active model '{active_version}' declared in registry '{registry_path}' but model artifact directory '{model_dir}' does not exist. Failing closed."
                )

            schema_path = model_dir / "schema.json"
            if not schema_path.exists():
                raise SchemaValidationError(
                    f"Authoritative schema contract missing for active model '{active_version}' at '{schema_path}'. Failing closed per frozen governance rules."
                )

            try:
                with open(schema_path, encoding="utf-8") as f:
                    schema_data = json.load(f)
                return cls(**schema_data)
            except Exception as ex:
                raise SchemaValidationError(
                    f"Authoritative schema contract for active model '{active_version}' at '{schema_path}' is corrupt or invalid: {ex}"
                ) from ex

        # Pre-model foundation phase: if no active model registry exists, fall back to monitoring baseline if present
        if baseline_path.exists():
            try:
                with open(baseline_path, encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**data)
            except Exception as ex:
                raise SchemaValidationError(
                    f"Baseline monitoring schema at '{baseline_path}' is corrupt or invalid: {ex}"
                ) from ex

        return cls()

    def validate_dataframe(self, df: pd.DataFrame, projected: bool = False) -> Tuple[bool, List[str]]:
        """Validate incoming DataFrame against structural schema contract.

        Checks:
        1. All required columns exist (for full load; or base columns if projected).
        2. Non-null identifiers and timestamps.
        3. Timestamp column is present, parseable, strictly timezone-aware UTC (rejecting naive).
        4. Hourly grain validation (minutes and seconds must be 00:00).
        5. Column dtypes match expected types where verifiable.
        6. Numerical range checks for declared fields (non-negative counters/duration).
        7. Gateway ID validity.
        """
        errors: List[str] = []

        # 1. Required columns presence
        check_cols = ["gateway_id", "ts_utc"] if projected else self.required_columns
        missing_cols = [c for c in check_cols if c not in df.columns]
        if missing_cols:
            errors.append(f"Missing required column(s): {missing_cols}")

        if errors:
            return False, errors

        # 2. Non-null checks for mandatory fields
        if "gateway_id" in df.columns and df["gateway_id"].isna().any():
            errors.append("gateway_id contains null or missing values")

        ts_col = self.timestamp_column
        if ts_col in df.columns:
            ts_series = df[ts_col]
            if ts_series.isna().any():
                errors.append(f"{ts_col} contains null or missing timestamp values")

            # 3. Strict UTC timestamp parsing and naive timezone rejection
            parsed_utc_ts: Optional[pd.Series] = None
            if not pd.api.types.is_datetime64_any_dtype(ts_series):
                try:
                    # Parse without forcing utc=True to catch tz-naive strings
                    ts_check = pd.to_datetime(ts_series, format="ISO8601")
                    if ts_check.dt.tz is None:
                        errors.append(
                            f"{ts_col} contains naive timestamp(s) lacking UTC timezone indicator. "
                            "Naive timestamps must not be silently interpreted as UTC."
                        )
                    else:
                        tz_str = str(ts_check.dt.tz)
                        if tz_str not in ("UTC", "datetime.timezone.utc"):
                            errors.append(f"{ts_col} must be UTC timezone, got {tz_str}")
                        else:
                            parsed_utc_ts = ts_check
                except Exception as ex:
                    errors.append(f"{ts_col} failed UTC datetime parsing: {ex}")
            else:
                # Check timezone of datetime64 Series
                tz_str = str(getattr(ts_series.dt, "tz", None))
                if tz_str not in ("UTC", "datetime.timezone.utc"):
                    errors.append(
                        f"{ts_col} must be timezone-aware UTC. Got naive or non-UTC datetime: {ts_series.dt.tz}. "
                        "Naive timestamps must not be silently interpreted as UTC."
                    )
                else:
                    parsed_utc_ts = ts_series

            # 4. Hourly telemetry grain validation (minutes == 0, seconds == 0)
            if self.time_grain == "hourly" and parsed_utc_ts is not None and len(df) > 0:
                try:
                    non_hourly = (parsed_utc_ts.dt.minute != 0) | (parsed_utc_ts.dt.second != 0)
                    if non_hourly.any():
                        errors.append(f"{ts_col} contains non-hourly grain timestamps (minutes/seconds non-zero)")
                except Exception:
                    pass

        # 5. Numeric dtypes and range validation
        for col, expected_dtype in self.dtypes.items():
            if col in df.columns and col != ts_col:
                if expected_dtype in ("float64", "int64", "numeric", "float32", "int32"):
                    if not pd.api.types.is_numeric_dtype(df[col]):
                        errors.append(f"Column '{col}' expected numeric dtype, got {df[col].dtype}")

        # Range checks for declared telemetry fields
        if "offline_duration_sec" in df.columns:
            off = df["offline_duration_sec"]
            if (off < 0.0).any():
                errors.append("offline_duration_sec must be non-negative (>= 0.0)")

        if "disconnection_cnt" in df.columns:
            disc = df["disconnection_cnt"]
            if (disc < 0.0).any():
                errors.append("disconnection_cnt must be non-negative (>= 0.0)")

        if "reboot_cnt" in df.columns:
            reb = df["reboot_cnt"]
            if (reb < 0.0).any():
                errors.append("reboot_cnt must be non-negative (>= 0.0)")

        return len(errors) == 0, errors

    def validate_or_raise(self, df: pd.DataFrame, projected: bool = False) -> None:
        """Validate DataFrame and raise SchemaValidationError if invalid."""
        valid, errors = self.validate_dataframe(df, projected=projected)
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

