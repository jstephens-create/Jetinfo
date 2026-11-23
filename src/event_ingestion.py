"""Event-aware CSV intake, separate from the small synthetic demo pipeline.

A row in an audit export is an event, not a ticket. We retain each valid event
and point the incident table at one deterministic latest whole row. Keeping the
raw file and the source row number makes every normalized value traceable.

No response times, SLA agreements, category meanings, or time zones are guessed.
This module deliberately does not train or invoke the synthetic-data model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import ROOT
from src.database import connect

IMPORT_DB_PATH = ROOT / "data" / "processed" / "okai_imports.db"
IMPORT_STORAGE_ROOT = ROOT / "data" / "imports"

# These names are application-owned, rather than interpolated source headers.
EVENT_COLUMNS = [
    "incident_id", "source_row", "event_at", "source_sequence", "opened_at",
    "resolved_at", "closed_at", "status", "priority", "category",
    "assignment_group", "assigned_to", "source_sla_met", "is_active",
    "reassignment_count", "reopen_count", "timestamp_timezone",
    "resolved_after_event", "closed_after_event", "validation_warnings",
]
TIMESTAMP_FIELDS = ("event_at", "opened_at", "resolved_at", "closed_at")
INTEGER_FIELDS = ("source_sequence", "reassignment_count", "reopen_count")
BOOLEAN_FIELDS = ("source_sla_met", "is_active")


@dataclass(frozen=True)
class MappingProfile:
    """Explicit source contract: mapping keys are canonical target field names.

    ``None`` time zone means unknown source-local clock time. A supplied named
    time zone is localized strictly, then converted to UTC. Ambiguous DST times
    cannot identify an instant, so they are never silently resolved for a user.
    """
    profile_id: str
    version: str
    source_name: str
    field_mapping: dict[str, str]
    timestamp_format: str = "%d/%m/%Y %H:%M"
    source_timezone: str | None = None
    missing_values: tuple[str, ...] = ("", "?")
    priority_mapping: dict[str, str] = field(default_factory=dict)
    required_fields: tuple[str, ...] = ("incident_id", "event_at")
    source_kind: str = "historical_event_log"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        # Profile content, not just its friendly name, is part of import identity.
        # Changing a time zone or mapping cannot accidentally reuse old results.
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


UCI_PROFILE = MappingProfile(
    profile_id="uci_incident_event_log", version="1.0.0",
    source_name="UCI Incident Management Process Enriched Event Log",
    field_mapping={
        "incident_id": "number", "event_at": "sys_updated_at",
        "source_sequence": "sys_mod_count", "opened_at": "opened_at",
        "resolved_at": "resolved_at", "closed_at": "closed_at",
        "status": "incident_state", "priority": "priority", "category": "category",
        "assignment_group": "assignment_group", "assigned_to": "assigned_to",
        "source_sla_met": "made_sla", "is_active": "active",
        "reassignment_count": "reassignment_count", "reopen_count": "reopen_count",
    },
    priority_mapping={"1 - Critical": "Critical", "2 - High": "High",
                      "3 - Moderate": "Medium", "4 - Low": "Low"},
)


@dataclass(frozen=True)
class ImportResult:
    import_id: str
    source_name: str
    source_path: str
    source_sha256: str
    source_bytes: int
    profile_id: str
    profile_version: str
    profile_fingerprint: str
    source_timezone: str | None
    timestamp_timezone: str
    rows_read: int
    events_loaded: int
    incidents_loaded: int
    rows_rejected: int
    original_copy_path: str
    rejection_csv_path: str
    warnings_csv_path: str
    quality_summary: dict
    warnings: list[str]
    timings_seconds: dict[str, float]
    imported_at: str
    idempotent_reuse: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


SCHEMA = """
CREATE TABLE IF NOT EXISTS source_imports (
    import_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    profile_fingerprint TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    UNIQUE(source_sha256, profile_fingerprint)
);
CREATE TABLE IF NOT EXISTS source_import_attempts (
    attempt_id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    profile_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'preserving','parsing','validating','normalizing','exporting',
        'database_write','committed','failed','interrupted'
    )),
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS source_import_attempt_lookup
    ON source_import_attempts(source_sha256, profile_fingerprint, started_at);
CREATE TABLE IF NOT EXISTS source_events (
    import_id TEXT NOT NULL REFERENCES source_imports(import_id),
    incident_id TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    event_at TEXT NOT NULL,
    source_sequence INTEGER,
    opened_at TEXT,
    resolved_at TEXT,
    closed_at TEXT,
    status TEXT,
    priority TEXT,
    category TEXT,
    assignment_group TEXT,
    assigned_to TEXT,
    source_sla_met INTEGER CHECK(source_sla_met IN (0, 1) OR source_sla_met IS NULL),
    is_active INTEGER CHECK(is_active IN (0, 1) OR is_active IS NULL),
    reassignment_count INTEGER,
    reopen_count INTEGER,
    timestamp_timezone TEXT NOT NULL,
    resolved_after_event INTEGER,
    closed_after_event INTEGER,
    validation_warnings TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    PRIMARY KEY(import_id, source_row)
);
CREATE INDEX IF NOT EXISTS source_event_incident
    ON source_events(import_id, incident_id, event_at, source_sequence, source_row);
CREATE INDEX IF NOT EXISTS source_event_timeline
    ON source_events(import_id, incident_id, source_row);
-- A snapshot is a pointer to an entire stored event. This avoids assembling a
-- synthetic row by taking different nonmissing columns from different events.
CREATE TABLE IF NOT EXISTS source_incidents (
    import_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    PRIMARY KEY(import_id, incident_id),
    FOREIGN KEY(import_id, source_row) REFERENCES source_events(import_id, source_row)
);
CREATE INDEX IF NOT EXISTS source_incident_snapshot_order
    ON source_incidents(import_id, incident_id, source_row);
CREATE TABLE IF NOT EXISTS source_rejections (
    import_id TEXT NOT NULL REFERENCES source_imports(import_id),
    source_row INTEGER NOT NULL,
    incident_id TEXT,
    reason TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    PRIMARY KEY(import_id, source_row)
);
"""


def init_import_db(db_path: Path | str = IMPORT_DB_PATH) -> None:
    """Add isolated source tables; never rename or replace existing demo tables."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _attempt_lookup(conn: sqlite3.Connection, digest: str, profile_fingerprint: str):
    return conn.execute(
        """SELECT attempt_id, import_id, status
           FROM source_import_attempts
           WHERE source_sha256=? AND profile_fingerprint=?
           ORDER BY rowid DESC LIMIT 1""",
        (digest, profile_fingerprint),
    ).fetchone()


def _mark_attempt(conn: sqlite3.Connection, attempt_id: str, status: str,
                  stage: str, error_message: str | None = None) -> None:
    finished = status in {"committed", "failed", "interrupted"}
    conn.execute(
        """UPDATE source_import_attempts
           SET status=?, stage=?, finished_at=?, error_message=?
           WHERE attempt_id=?""",
        (status, stage, _now() if finished else None, error_message, attempt_id),
    )


def _start_attempt(db_path: Path | str, digest: str, profile_fingerprint: str) -> tuple[str, str]:
    """Create or recover an import attempt in SQLite without touching source facts."""
    attempt_id = uuid.uuid4().hex
    with connect(db_path) as conn:
        prior = _attempt_lookup(conn, digest, profile_fingerprint)
        if prior and prior[2] not in {"committed", "failed"}:
            conn.execute(
                """UPDATE source_import_attempts
                   SET status='interrupted', stage=stage, finished_at=?, error_message=? 
                   WHERE attempt_id=?""",
                (_now(), "Superseded by a retry; the prior process did not complete.", prior[0]),
            )
        if prior:
            import_id = prior[1]
        else:
            import_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO source_import_attempts
               (attempt_id, import_id, source_sha256, profile_fingerprint, status, stage, started_at)
               VALUES (?, ?, ?, ?, 'preserving', 'preserving', ?)""",
            (attempt_id, import_id, digest, profile_fingerprint, _now()),
        )
    return attempt_id, import_id


def _set_attempt(db_path: Path | str, attempt_id: str, status: str,
                 stage: str, error_message: str | None = None) -> None:
    with connect(db_path) as conn:
        _mark_attempt(conn, attempt_id, status, stage, error_message)


def list_import_attempts(db_path: Path | str = IMPORT_DB_PATH) -> pd.DataFrame:
    """Return import lifecycle evidence from the isolated import database."""
    init_import_db(db_path)
    with connect(db_path) as conn:
        return pd.read_sql_query(
            """SELECT attempt_id, import_id, source_sha256, profile_fingerprint,
                      status, stage, started_at, finished_at, error_message
               FROM source_import_attempts
               ORDER BY rowid DESC""",
            conn,
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _preserve_source(source: Path, storage_root: Path) -> tuple[Path, str]:
    digest = _sha256(source)
    destination = storage_root / "raw" / f"{digest}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(destination) != digest:
            raise ValueError("Preserved source failed its SHA-256 integrity check")
    elif source != destination.resolve():
        # Copying rather than moving leaves the user's original export untouched.
        temporary = destination.parent / f".{uuid.uuid4().hex}.tmp"
        try:
            shutil.copyfile(source, temporary)
            if _sha256(temporary) != digest:
                raise ValueError("Source changed while it was being preserved; retry the import")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination, digest


def _validate_profile(profile: MappingProfile) -> None:
    allowed = set(EVENT_COLUMNS) - {"source_row", "timestamp_timezone", "resolved_after_event",
                                    "closed_after_event", "validation_warnings"}
    invalid = set(profile.field_mapping) - allowed
    if invalid:
        raise ValueError(f"Unsupported target fields in mapping profile: {sorted(invalid)}")
    if not {"incident_id", "event_at"}.issubset(profile.field_mapping):
        raise ValueError("Mapping profile must map incident_id and event_at")
    if not set(profile.required_fields).issubset(profile.field_mapping):
        raise ValueError("Every required field must have an explicit source mapping")
    if len(set(profile.field_mapping.values())) != len(profile.field_mapping):
        raise ValueError("Each mapped source column must have one unambiguous target")
    if not profile.profile_id or not profile.version or not profile.timestamp_format:
        raise ValueError("Profile ID, version and timestamp format are required")
    if profile.source_timezone:
        # Let pandas validate the named zone before any data is imported.
        try:
            pd.Timestamp("2024-01-15").tz_localize(profile.source_timezone)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Unknown or invalid source time zone: {profile.source_timezone}") from error


def _nonnegative_integer(value: Any) -> int | None:
    """Parse counters without a floating-point round trip near SQLite's limit.

    A float cannot represent every 64-bit integer. Decimal validates the source
    text exactly before we bind a signed SQLite integer, including when other
    rows are unknown or use decimal/exponent notation for an integral value.
    """
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
        if number.is_finite() and 0 <= number <= 2**63 - 1 and number == number.to_integral_value():
            return int(number)
    except (InvalidOperation, ValueError, OverflowError):
        pass
    return None


def _read_source(path: Path, profile: MappingProfile) -> pd.DataFrame:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    if len(set(header)) != len(header):
        raise ValueError("Duplicate CSV column names are ambiguous; supply a corrected export")
    if any(name.startswith("_okai_") for name in header):
        raise ValueError("CSV headers beginning _okai_ are reserved for audit exports")
    missing = set(profile.field_mapping.values()) - set(header)
    if missing:
        raise ValueError(f"Mapping profile {profile.profile_id!r} is missing source columns: {sorted(missing)}")
    # Default pandas NA parsing would lose the distinction between source text
    # and a source-specific missing marker. Our profile makes that decision.
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def _validate(raw: pd.DataFrame, profile: MappingProfile) -> tuple[dict, dict, pd.Series, dict]:
    stripped = raw.apply(lambda column: column.str.strip())
    source = stripped.mask(stripped.isin(profile.missing_values))
    mapped = {target: source[column] for target, column in profile.field_mapping.items()}
    empty = pd.Series(None, index=raw.index, dtype=object)
    warnings = pd.Series([[] for _ in raw.index], index=raw.index, dtype=object)
    reasons = pd.Series([[] for _ in raw.index], index=raw.index, dtype=object)
    invalid_counts: dict[str, int] = {}

    def flag(mask: pd.Series, message: str, *, reject: bool = False) -> None:
        mask = mask.fillna(False)
        invalid_counts[message] = int(mask.sum())
        collection = reasons if reject else warnings
        for index in mask[mask].index:
            collection.at[index].append(message)

    for target in profile.required_fields:
        flag(mapped[target].isna(), f"missing {target}", reject=True)
    flag(mapped["incident_id"].isna(), "missing incident_id", reject=True)

    normalized: dict[str, pd.Series] = {}
    for target in TIMESTAMP_FIELDS:
        values = mapped.get(target, empty)
        parsed = pd.to_datetime(values, format=profile.timestamp_format, errors="coerce")
        if profile.source_timezone:
            parsed = parsed.dt.tz_localize(profile.source_timezone, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
        invalid = values.notna() & parsed.isna()
        flag(invalid, f"invalid {target}", reject=target in profile.required_fields or target == "event_at")
        normalized[target] = parsed
    flag(normalized["resolved_at"].notna() & normalized["opened_at"].notna()
         & normalized["resolved_at"].lt(normalized["opened_at"]), "resolved_at before opened_at")
    flag(normalized["closed_at"].notna() & normalized["resolved_at"].notna()
         & normalized["closed_at"].lt(normalized["resolved_at"]), "closed_at before resolved_at")
    # Even a customized profile cannot admit an event without an orderable time.
    if "event_at" not in profile.required_fields:
        flag(mapped["event_at"].isna(), "missing event_at", reject=True)

    for target in INTEGER_FIELDS:
        values = mapped.get(target, empty)
        parsed = pd.Series(pd.array([_nonnegative_integer(value) for value in values], dtype="Int64"), index=raw.index)
        flag(values.notna() & parsed.isna(), f"invalid {target}", reject=target in profile.required_fields)
        normalized[target] = parsed
    for target in BOOLEAN_FIELDS:
        values = mapped.get(target, empty)
        normalized[target] = values.str.lower().map({"true": True, "false": False}).astype("boolean")
        flag(values.notna() & normalized[target].isna(), f"invalid {target}", reject=target in profile.required_fields)
    for target in ("incident_id", "status", "priority", "category", "assignment_group", "assigned_to"):
        normalized[target] = mapped.get(target, empty).copy()
    if profile.priority_mapping:
        priority = normalized["priority"].map(profile.priority_mapping)
        flag(normalized["priority"].notna() & priority.isna(), "unmapped priority", reject="priority" in profile.required_fields)
        normalized["priority"] = priority

    # Optional invalid values are not silently treated as genuine source blanks.
    # The normalized null, original text, and warning all remain inspectable.
    normalized["validation_warnings"] = warnings
    quality = {
        "missing_source_cells": {name: int(count) for name, count in source.isna().sum().items()},
        "invalid_field_counts": {name: count for name, count in invalid_counts.items() if count},
        "exact_duplicate_visible_rows": int(raw.duplicated().sum()),
    }
    return normalized, mapped, reasons, quality


def _normalize(normalized: dict, reasons: pd.Series, raw: pd.DataFrame,
               profile: MappingProfile) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    frame = pd.DataFrame(normalized)
    frame["source_row"] = range(1, len(raw) + 1)
    timezone_name = "UTC" if profile.source_timezone else "unknown"
    frame["timestamp_timezone"] = timezone_name
    temporal_counts = {}
    for outcome in ("resolved", "closed"):
        available = frame[f"{outcome}_at"].notna() & frame["event_at"].notna()
        flag = (frame[f"{outcome}_at"] > frame["event_at"]).astype("boolean").where(available)
        frame[f"{outcome}_after_event"] = flag
        temporal_counts[f"{outcome}_after_event"] = int(flag.fillna(False).sum())
    for target in TIMESTAMP_FIELDS:
        # ISO strings preserve ordering. Unknown-zone clock times remain naive;
        # only a named source time zone can justify a UTC conversion and suffix.
        fmt = "%Y-%m-%dT%H:%M:%SZ" if profile.source_timezone else "%Y-%m-%dT%H:%M:%S"
        frame[target] = frame[target].dt.strftime(fmt).where(frame[target].notna(), None)
    rejected_mask = reasons.str.len().gt(0)
    rejected = raw.loc[rejected_mask].copy()
    rejected["_okai_source_row"] = frame.loc[rejected_mask, "source_row"]
    rejected["_okai_rejection_reason"] = reasons[rejected_mask].map(lambda value: "; ".join(dict.fromkeys(value)))
    valid = frame.loc[~rejected_mask, EVENT_COLUMNS].copy()
    # Stable whole-row selection: update time, then source modification counter,
    # then data-row position. Missing counters come first, never ahead of a known
    # counter at the same time. We preserve ties and explain this fallback.
    ordered = valid.sort_values(["incident_id", "event_at", "source_sequence", "source_row"],
                                kind="stable", na_position="first")
    latest = ordered.drop_duplicates("incident_id", keep="last")
    return valid, latest, rejected, temporal_counts


def _sql_value(value: Any) -> Any:
    if value is None or value is pd.NA or (not isinstance(value, (str, list)) and pd.isna(value)):
        return None
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "item"):
        return value.item()
    return value


def _commit_import(conn: sqlite3.Connection, import_id: str, digest: str,
                   profile_fingerprint: str, metadata_json: str,
                   event_rows: list[tuple], latest: pd.DataFrame,
                   rejection_rows: list[tuple]) -> None:
    """Commit all import facts atomically with the manifest and lifecycle identity."""
    conn.execute("INSERT INTO source_imports VALUES (?, ?, ?, ?)",
                 (import_id, digest, profile_fingerprint, metadata_json))
    columns = ["import_id"] + EVENT_COLUMNS + ["raw_record_json"]
    conn.executemany(
        f"INSERT INTO source_events ({', '.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        ((import_id,) + row for row in event_rows),
    )
    conn.executemany(
        "INSERT INTO source_incidents VALUES (?, ?, ?)",
        ((import_id, str(row.incident_id), int(row.source_row)) for row in latest.itertuples()),
    )
    conn.executemany(
        "INSERT INTO source_rejections VALUES (?, ?, ?, ?, ?)",
        ((import_id,) + row for row in rejection_rows),
    )


def import_event_log(source_path: Path | str, db_path: Path | str = IMPORT_DB_PATH,
                     storage_root: Path | str = IMPORT_STORAGE_ROOT,
                     profile: MappingProfile = UCI_PROFILE,
                     source_name: str | None = None) -> ImportResult:
    """Preserve, validate and atomically store an explicitly mapped event export.

    Repeating identical bytes with the identical profile reuses its immutable
    import. A changed file or changed mapping gets its own source namespace.
    Financial estimates and SLA policy calculations are intentionally absent.
    """
    started = time.perf_counter()
    if profile.source_timezone and profile.source_timezone.lower() == "unknown":
        profile = replace(profile, source_timezone=None)
    _validate_profile(profile)
    source_path = Path(source_path).resolve(strict=True)
    storage_root = Path(storage_root).resolve()
    init_import_db(db_path)
    attempt_id = None
    timings = {}
    try:
        stage = time.perf_counter()
        digest = _sha256(source_path)
        with connect(db_path) as conn:
            existing = conn.execute(
                "SELECT metadata_json FROM source_imports WHERE source_sha256=? AND profile_fingerprint=?",
                (digest, profile.fingerprint),
            ).fetchone()
        if existing:
            original, preserved_digest = _preserve_source(source_path, storage_root)
            if preserved_digest != digest:
                raise ValueError("Source changed while it was being preserved; retry the import")
            timings["file_preservation"] = time.perf_counter() - stage
            metadata = json.loads(existing[0])
            metadata["lifecycle"] = "committed"
            # Timings in stored metadata always refer to the original processing run.
            return ImportResult(
                **{key: value for key, value in metadata.items()
                   if key in ImportResult.__dataclass_fields__},
                idempotent_reuse=True,
            )

        attempt_id, import_id = _start_attempt(db_path, digest, profile.fingerprint)
        _set_attempt(db_path, attempt_id, "preserving", "preserving")
        original, preserved_digest = _preserve_source(source_path, storage_root)
        if preserved_digest != digest:
            raise ValueError("Source changed while it was being preserved; retry the import")
        timings["file_preservation"] = time.perf_counter() - stage

        stage = time.perf_counter()
        _set_attempt(db_path, attempt_id, "parsing", "parsing")
        raw = _read_source(original, profile)
        timings["parsing"] = time.perf_counter() - stage

        stage = time.perf_counter()
        _set_attempt(db_path, attempt_id, "validating", "validating")
        normalized, _mapped, reasons, quality = _validate(raw, profile)
        timings["validation"] = time.perf_counter() - stage

        stage = time.perf_counter()
        _set_attempt(db_path, attempt_id, "normalizing", "normalizing")
        events, latest, rejected, temporal = _normalize(normalized, reasons, raw, profile)
        quality.update(temporal)
        quality["rows_with_field_warnings"] = int(events.validation_warnings.str.len().gt(0).sum())
        quality["history_rows_beyond_one_per_incident"] = len(events) - len(latest)
        quality["snapshot_order"] = ["event_at ASC", "source_sequence ASC NULLS FIRST", "source_row ASC"]
        raw_json = raw.to_json(orient="records", lines=True, force_ascii=False).splitlines()
        event_rows = [tuple(_sql_value(value) for value in record) + (raw_json[int(record[1]) - 1],)
                      for record in events.itertuples(index=False, name=None)]
        rejection_rows = [(int(index) + 1, _sql_value(normalized["incident_id"].loc[index]),
                           "; ".join(dict.fromkeys(reasons.loc[index])), raw_json[int(index)])
                          for index in rejected.index]
        timings["normalization"] = time.perf_counter() - stage

        exports = storage_root / "exports" / import_id
        exports.mkdir(parents=True, exist_ok=True)
        rejected_path = exports / "rejected_rows.csv"
        warning_path = exports / "validation_warnings.csv"
        stage = time.perf_counter()
        _set_attempt(db_path, attempt_id, "exporting", "exporting")
        rejected.to_csv(rejected_path, index=False)
        warning_frame = events.loc[events.validation_warnings.str.len().gt(0),
                                   ["source_row", "incident_id", "validation_warnings"]].copy()
        warning_frame["validation_warnings"] = warning_frame.validation_warnings.map(
            lambda values: "; ".join(values)
        )
        warning_frame.to_csv(warning_path, index=False)
        timings["audit_exports"] = time.perf_counter() - stage

        warnings = [
            "Source-reported SLA outcomes; contractual policy has not been independently verified.",
            "Latest snapshots are retrospective outcomes, not creation-time prediction features.",
            "Response time, SLA targets, business calendars and financial costs are unavailable unless separately supplied.",
        ]
        if not profile.source_timezone:
            warnings.append("Source time zone is unknown. Timestamps are source-local clock times, not asserted UTC instants.")
        if any(temporal.values()):
            warnings.append("Some event rows contain later outcome timestamps; never use those enriched values as point-in-time model features.")
        if len(rejected):
            warnings.append(f"{len(rejected)} source rows excluded from valid events; see the rejection export.")
        if quality["rows_with_field_warnings"]:
            warnings.append(f"{quality['rows_with_field_warnings']} valid events contain invalid optional fields; see the validation warning export.")
        result = ImportResult(
            import_id=import_id, source_name=source_name or profile.source_name, source_path=str(source_path),
            source_sha256=digest, source_bytes=original.stat().st_size,
            profile_id=profile.profile_id, profile_version=profile.version,
            profile_fingerprint=profile.fingerprint, source_timezone=profile.source_timezone,
            timestamp_timezone="UTC" if profile.source_timezone else "unknown", rows_read=len(raw),
            events_loaded=len(events), incidents_loaded=len(latest), rows_rejected=len(rejected),
            original_copy_path=str(original), rejection_csv_path=str(rejected_path),
            warnings_csv_path=str(warning_path), quality_summary=quality, warnings=warnings,
            timings_seconds=timings, imported_at=_now())
        metadata = result.to_dict()
        metadata.pop("idempotent_reuse")
        metadata.update(
            mapping_profile=profile.to_dict(), source_kind=profile.source_kind,
            source_filename=source_path.name, dataset_id=import_id,
            snapshot_method="latest whole event by update time, modification counter, then source row",
            lifecycle="committed",
        )

        stage = time.perf_counter()
        _set_attempt(db_path, attempt_id, "database_write", "database_write")
        with connect(db_path) as conn:
            _commit_import(
                conn, import_id, digest, profile.fingerprint,
                json.dumps(metadata, ensure_ascii=False),
                event_rows, latest, rejection_rows,
            )
        timings["database_write"] = time.perf_counter() - stage
        timings["total"] = time.perf_counter() - started
        metadata["timings_seconds"] = timings
        with connect(db_path) as conn:
            conn.execute(
                "UPDATE source_imports SET metadata_json=? WHERE import_id=?",
                (json.dumps(metadata, ensure_ascii=False), import_id),
            )
        _set_attempt(db_path, attempt_id, "committed", "committed")
        return replace(result, timings_seconds=timings)
    except Exception as exc:
        if attempt_id is not None:
            try:
                _set_attempt(db_path, attempt_id, "failed", "failed", f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
        raise


def _require_import(conn: sqlite3.Connection, import_id: str) -> dict:
    row = conn.execute("SELECT metadata_json FROM source_imports WHERE import_id=?", (import_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown import ID: {import_id}")
    return json.loads(row[0])


def read_import(import_id: str, db_path: Path | str = IMPORT_DB_PATH) -> dict:
    with connect(db_path) as conn:
        return _require_import(conn, import_id)


def list_imports(db_path: Path | str = IMPORT_DB_PATH) -> pd.DataFrame:
    init_import_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT metadata_json FROM source_imports").fetchall()
    columns = ["import_id", "source_name", "source_filename", "imported_at", "events_loaded",
               "incidents_loaded", "rows_rejected", "timestamp_timezone", "profile_id"]
    frame = pd.DataFrame([json.loads(row[0]) for row in rows], columns=columns)
    return frame.sort_values("imported_at", ascending=False).reset_index(drop=True)


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    for column in (*BOOLEAN_FIELDS, "resolved_after_event", "closed_after_event"):
        if column in frame:
            frame[column] = frame[column].astype("boolean")
    for column in INTEGER_FIELDS:
        if column in frame:
            frame[column] = frame[column].astype("Int64")
    if "validation_warnings" in frame:
        frame["validation_warnings"] = frame.validation_warnings.map(json.loads)
    return frame


def read_events(import_id: str, db_path: Path | str = IMPORT_DB_PATH,
                columns: list[str] | None = None, include_raw: bool = False,
                incident_id: str | None = None) -> pd.DataFrame:
    selected = list(EVENT_COLUMNS if columns is None else columns)
    if include_raw:
        selected.append("raw_record_json")
    if not selected or set(selected) - set(EVENT_COLUMNS + ["raw_record_json", "import_id"]):
        raise ValueError("Event columns must be selected from the normalized source contract")
    selected = list(dict.fromkeys(selected))
    where, params = "import_id=?", [import_id]
    if incident_id is not None:
        where += " AND incident_id=?"
        params.append(incident_id)
    with connect(db_path) as conn:
        _require_import(conn, import_id)
        frame = pd.read_sql_query(f"SELECT {', '.join(selected)} FROM source_events WHERE {where} ORDER BY source_row",
                                  conn, params=params, dtype_backend="numpy_nullable")
    return _typed(frame)


def read_snapshots(import_id: str, db_path: Path | str = IMPORT_DB_PATH) -> pd.DataFrame:
    columns = ", ".join(f"e.{name}" for name in EVENT_COLUMNS)
    with connect(db_path) as conn:
        _require_import(conn, import_id)
        frame = pd.read_sql_query(f"""SELECT e.import_id, {columns} FROM source_events e
            JOIN source_incidents i ON e.import_id=i.import_id AND e.source_row=i.source_row
            WHERE e.import_id=? ORDER BY i.incident_id""", conn, params=(import_id,), dtype_backend="numpy_nullable")
    return _typed(frame)


def read_initial_snapshots(import_id: str, db_path: Path | str = IMPORT_DB_PATH) -> pd.DataFrame:
    """Earliest observed whole event, which is NOT guaranteed to be creation-time."""
    frame = read_events(import_id, db_path)
    return frame.sort_values(["incident_id", "event_at", "source_sequence", "source_row"],
                             kind="stable", na_position="first").drop_duplicates("incident_id", keep="first").reset_index(drop=True)


def read_rejections(import_id: str, db_path: Path | str = IMPORT_DB_PATH) -> pd.DataFrame:
    with connect(db_path) as conn:
        _require_import(conn, import_id)
        return pd.read_sql_query("SELECT source_row, incident_id, reason, raw_record_json FROM source_rejections WHERE import_id=? ORDER BY source_row",
                                 conn, params=(import_id,))


def event_count(import_id: str, db_path: Path | str = IMPORT_DB_PATH) -> int:
    """Count in SQL without loading or parsing historical raw JSON into memory."""
    with connect(db_path) as conn:
        _require_import(conn, import_id)
        return int(conn.execute("SELECT COUNT(*) FROM source_events WHERE import_id=?", (import_id,)).fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Preserve and import a UCI incident event log into isolated OKai source tables")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=IMPORT_DB_PATH)
    parser.add_argument("--storage", type=Path, default=IMPORT_STORAGE_ROOT)
    args = parser.parse_args()
    print(json.dumps(import_event_log(args.source, args.db, args.storage).to_dict(), indent=2))


if __name__ == "__main__":
    main()
