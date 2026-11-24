"""Persistent investigation annotations linked to compact calculation traces."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import sqlite3
from uuid import uuid4

import pandas as pd

from src import database
from src.config import DB_PATH

TRACE_VERSION = 1
DEMO_SOURCE_ID = "synthetic-demo"
OUTCOME_STATUSES = ("Resolved", "Unresolved", "Escalated", "No action taken", "Other")
SCHEMA = """
CREATE TABLE IF NOT EXISTS calculation_traces (
    trace_id TEXT PRIMARY KEY,
    trace_version INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('demo','event_log')),
    incident_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    trace_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calculation_trace_source_incident
    ON calculation_traces(source_id, incident_id);
CREATE TRIGGER IF NOT EXISTS calculation_trace_no_update
BEFORE UPDATE ON calculation_traces
BEGIN
    SELECT RAISE(ABORT, 'Calculation traces are immutable.');
END;
CREATE TRIGGER IF NOT EXISTS calculation_trace_no_delete
BEFORE DELETE ON calculation_traces
BEGIN
    SELECT RAISE(ABORT, 'Calculation traces are immutable.');
END;

CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('demo','event_log')),
    source_name TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    trace_id TEXT NOT NULL REFERENCES calculation_traces(trace_id),
    owner TEXT NOT NULL,
    rationale TEXT NOT NULL,
    next_action TEXT NOT NULL,
    follow_up_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Open','Outcome recorded')),
    outcome_status TEXT,
    outcome_note TEXT,
    outcome_date TEXT,
    measured_value REAL,
    measured_unit TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS investigation_source_follow_up
    ON investigations(source_id, follow_up_date, status);
CREATE INDEX IF NOT EXISTS investigation_incident
    ON investigations(source_id, incident_id, created_at);
CREATE TRIGGER IF NOT EXISTS investigation_decision_fields_immutable
BEFORE UPDATE ON investigations
WHEN NEW.investigation_id IS NOT OLD.investigation_id
  OR NEW.source_id IS NOT OLD.source_id
  OR NEW.source_kind IS NOT OLD.source_kind
  OR NEW.source_name IS NOT OLD.source_name
  OR NEW.incident_id IS NOT OLD.incident_id
  OR NEW.trace_id IS NOT OLD.trace_id
  OR NEW.owner IS NOT OLD.owner
  OR NEW.rationale IS NOT OLD.rationale
  OR NEW.next_action IS NOT OLD.next_action
  OR NEW.follow_up_date IS NOT OLD.follow_up_date
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'Investigation decisions are immutable.');
END;

CREATE TABLE IF NOT EXISTS investigation_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id),
    event_type TEXT NOT NULL CHECK (event_type IN ('created','outcome_recorded')),
    actor_role TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS investigation_event_history
    ON investigation_events(investigation_id, event_id);
CREATE TRIGGER IF NOT EXISTS investigation_events_no_update
BEFORE UPDATE ON investigation_events
BEGIN
    SELECT RAISE(ABORT, 'Investigation events are append-only.');
END;
CREATE TRIGGER IF NOT EXISTS investigation_events_no_delete
BEFORE DELETE ON investigation_events
BEGIN
    SELECT RAISE(ABORT, 'Investigation events are append-only.');
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize(db_path=DB_PATH) -> None:
    with database.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def stable_source_id(context) -> str:
    """Return a durable source namespace, not a transient calculation run ID."""
    if context.source_kind == "demo":
        return DEMO_SOURCE_ID
    if context.source_kind == "event_log" and context.import_id:
        return context.import_id
    raise ValueError("The selected source has no stable identifier for investigations.")


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def build_trace_reference(engine, incident_id: str, inspection: dict, parameters: dict,
                          parameter_origins: dict, membership_records: pd.DataFrame) -> dict:
    """Build an immutable trace containing only the selected incident's evidence."""
    metric_records = inspection["records"]
    if "incident_id" in metric_records:
        metric_records = metric_records[
            metric_records["incident_id"].astype("string").eq(incident_id)
        ]
    else:
        metric_records = metric_records.iloc[0:0]
    if "incident_id" in membership_records:
        membership_records = membership_records[
            membership_records["incident_id"].astype("string").eq(incident_id)
        ]
    origins = {name: parameter_origins.get(name, "Selected in investigation workflow")
               for name in parameters}
    evidence_records = metric_records if not metric_records.empty else membership_records
    evidence = {
        "kind": "metric calculation rows" if not metric_records.empty else "source incident membership",
        "record_count": len(evidence_records),
        "records": _records(evidence_records),
    }
    evidence_sha256 = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    payload = {
        "schema": "okai.incident-calculation-trace.v1",
        "trace_version": TRACE_VERSION,
        "source": {"source_id": stable_source_id(engine.context),
                   "source_kind": engine.context.source_kind,
                   "source_name": engine.context.source_name,
                   "dataset_id": engine.context.dataset_id,
                   "import_id": engine.context.import_id,
                   "timezone": engine.context.timezone,
                   "observation_start": engine.context.observation_start,
                   "observation_end": engine.context.observation_end,
                   "warnings": list(engine.context.warnings)},
        "incident_id": incident_id,
        "metric_definition": inspection["definition"],
        "result": inspection["result"],
        "inputs": {"values": dict(parameters), "origins": origins},
        "evidence": evidence,
    }
    trace_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
    payload_sha256 = hashlib.sha256(trace_json.encode("utf-8")).hexdigest()
    result = inspection["result"]
    return {
        "trace_id": f"trace-v{TRACE_VERSION}-{payload_sha256}",
        "trace_version": TRACE_VERSION,
        "source_id": payload["source"]["source_id"],
        "source_kind": payload["source"]["source_kind"],
        "source_name": payload["source"]["source_name"],
        "incident_id": incident_id,
        "metric_id": result["metric_id"],
        "formula_version": result["formula_version"],
        "evidence_sha256": evidence_sha256,
        "payload_sha256": payload_sha256,
        "trace_json": trace_json,
    }


def _required_text(value, label: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    return value


def _iso_date(value, label: str) -> str:
    if type(value) is date:
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError(f"{label} is required.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid YYYY-MM-DD date.") from exc


def _validated_trace(trace: dict) -> dict:
    try:
        payload_json = trace["trace_json"]
        payload = json.loads(payload_json)
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if (trace["trace_id"] != f"trace-v{TRACE_VERSION}-{digest}"
                or trace["payload_sha256"] != digest
                or payload["trace_version"] != TRACE_VERSION
                or payload["schema"] != "okai.incident-calculation-trace.v1"):
            raise ValueError("The calculation trace reference is invalid.")
        if (payload["source"]["source_id"] != trace["source_id"]
                or payload["source"]["source_kind"] != trace["source_kind"]
                or payload["incident_id"] != trace["incident_id"]
                or payload["result"]["metric_id"] != trace["metric_id"]
                or payload["result"]["formula_version"] != trace["formula_version"]):
            raise ValueError("The calculation trace metadata does not match its payload.")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("A valid calculation trace is required.") from exc
    return payload


def create_investigation(trace: dict, owner: str, rationale: str, next_action: str,
                         follow_up_date, actor_role: str, db_path=DB_PATH) -> str:
    """Store one case and its immutable compact trace atomically."""
    payload = _validated_trace(trace)
    owner = _required_text(owner, "Owner", 120)
    rationale = _required_text(rationale, "Rationale", 1500)
    next_action = _required_text(next_action, "Next action", 1000)
    follow_up_date = _iso_date(follow_up_date, "Follow-up date")
    actor_role = _required_text(actor_role, "Actor role", 40)
    source = payload["source"]
    investigation_id = uuid4().hex
    now = _now()
    with database.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        stored = conn.execute("SELECT payload_sha256 FROM calculation_traces WHERE trace_id=?",
                              (trace["trace_id"],)).fetchone()
        if stored and stored[0] != trace["payload_sha256"]:
            raise ValueError("Calculation trace ID collision detected.")
        conn.execute("""
            INSERT OR IGNORE INTO calculation_traces
                (trace_id, trace_version, source_id, source_kind, incident_id, metric_id,
                 formula_version, evidence_sha256, payload_sha256, trace_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trace["trace_id"], trace["trace_version"], trace["source_id"], trace["source_kind"],
                  trace["incident_id"], trace["metric_id"], trace["formula_version"],
                  trace["evidence_sha256"], trace["payload_sha256"], trace["trace_json"]))
        conn.execute("""
            INSERT INTO investigations
                (investigation_id, source_id, source_kind, source_name, incident_id, trace_id,
                 owner, rationale, next_action, follow_up_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?, ?)
            """, (investigation_id, trace["source_id"], trace["source_kind"], source["source_name"],
                  trace["incident_id"], trace["trace_id"], owner, rationale, next_action,
                  follow_up_date, now, now))
        conn.execute("""
            INSERT INTO investigation_events
                (investigation_id, event_type, actor_role, happened_at, details_json)
            VALUES (?, 'created', ?, ?, ?)
            """, (investigation_id, actor_role, now, json.dumps({
                "owner": owner, "rationale": rationale, "next_action": next_action,
                "follow_up_date": follow_up_date, "trace_id": trace["trace_id"],
            }, ensure_ascii=False, allow_nan=False)))
    return investigation_id


def list_investigations(source_id: str, db_path=DB_PATH) -> pd.DataFrame:
    initialize(db_path)
    with database.connect(db_path) as conn:
        return pd.read_sql_query("""
            SELECT c.investigation_id, c.source_id, c.source_kind, c.source_name, c.incident_id,
                   c.owner, c.rationale, c.next_action, c.follow_up_date, c.status,
                   c.outcome_status, c.outcome_date, c.measured_value, c.measured_unit,
                   c.created_at, c.updated_at, t.trace_id, t.trace_version,
                   t.metric_id, t.formula_version
            FROM investigations c JOIN calculation_traces t ON t.trace_id=c.trace_id
            WHERE c.source_id=?
            ORDER BY CASE c.status WHEN 'Open' THEN 0 ELSE 1 END, c.follow_up_date, c.created_at DESC
            """, conn, params=(source_id,))


def read_investigation(investigation_id: str, db_path=DB_PATH) -> dict:
    initialize(db_path)
    with database.connect(db_path) as conn:
        cursor = conn.execute("""
            SELECT c.*, t.trace_version, t.metric_id, t.formula_version,
                   t.evidence_sha256, t.payload_sha256, t.trace_json
            FROM investigations c JOIN calculation_traces t ON t.trace_id=c.trace_id
            WHERE c.investigation_id=?
            """, (investigation_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Investigation not found.")
        return dict(zip((column[0] for column in cursor.description), row))


def read_events(investigation_id: str, db_path=DB_PATH) -> pd.DataFrame:
    initialize(db_path)
    with database.connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM investigation_events WHERE investigation_id=? ORDER BY event_id",
            conn, params=(investigation_id,))


def record_outcome(investigation_id: str, outcome_status: str, outcome_note: str,
                   outcome_date, measured_value=None, measured_unit: str | None = None,
                   actor_role: str = "Analyst", db_path=DB_PATH) -> None:
    """Append a user-reported outcome without changing source facts or its trace."""
    if outcome_status not in OUTCOME_STATUSES:
        raise ValueError("Choose a valid outcome status.")
    outcome_note = _required_text(outcome_note, "Outcome note", 1500)
    outcome_date = _iso_date(outcome_date, "Outcome date")
    actor_role = _required_text(actor_role, "Actor role", 40)
    if measured_unit is not None and not isinstance(measured_unit, str):
        raise ValueError("Measured outcome unit must be text.")
    unit = "" if measured_unit is None else measured_unit.strip()
    if measured_value is not None:
        if isinstance(measured_value, bool):
            raise ValueError("Measured outcome must be a finite number.")
        try:
            measured_value = float(measured_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Measured outcome must be a finite number.") from exc
        if not math.isfinite(measured_value):
            raise ValueError("Measured outcome must be a finite number.")
        unit = _required_text(unit, "Measured outcome unit", 40)
    elif unit:
        raise ValueError("Enter a measured outcome value with its unit.")
    now = _now()
    details = {"outcome_status": outcome_status, "outcome_note": outcome_note,
               "outcome_date": outcome_date, "measured_value": measured_value,
               "measured_unit": unit or None}
    with database.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM investigations WHERE investigation_id=?",
                            (investigation_id,)).fetchone():
            raise ValueError("Investigation not found.")
        conn.execute("""
            UPDATE investigations SET status='Outcome recorded', outcome_status=?, outcome_note=?,
                outcome_date=?, measured_value=?, measured_unit=?, updated_at=? WHERE investigation_id=?
            """, (outcome_status, outcome_note, outcome_date, measured_value, unit or None, now, investigation_id))
        conn.execute("""
            INSERT INTO investigation_events
                (investigation_id, event_type, actor_role, happened_at, details_json)
            VALUES (?, 'outcome_recorded', ?, ?, ?)
            """, (investigation_id, actor_role, now,
                  json.dumps(details, ensure_ascii=False, allow_nan=False)))
