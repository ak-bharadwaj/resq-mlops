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
    """Model-specific telemetry contract loaded from models/<version>/schema.json."""
    required_columns: List[str]
    dtypes: Dict[str, str]
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
                    ts_converted = pd.to_datetime(ts_series, utc=True)
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
