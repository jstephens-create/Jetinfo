"""SQLite storage layer: schema, safe writes, and SQL metric queries.

Every other component talks to the database through these functions, so SQL
lives in one file and the dashboard never writes to the database.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id             TEXT PRIMARY KEY,      -- natural key: prevents duplicates
    created_at              TEXT NOT NULL,         -- ISO-8601 'YYYY-MM-DD HH:MM:SS'
    priority                TEXT NOT NULL CHECK (priority IN ('Critical','High','Medium','Low')),
    category                TEXT NOT NULL,
    affected_service        TEXT NOT NULL,
    assignment_group        TEXT NOT NULL,
    response_time_minutes   REAL NOT NULL CHECK (response_time_minutes >= 0),
    resolution_time_minutes REAL,                  -- NULL while incident is open
    sla_target_minutes      INTEGER NOT NULL,
    status                  TEXT NOT NULL,
    sla_breached            INTEGER,               -- 1/0, NULL while open (outcome unknown)
    sla_margin_minutes      REAL,                  -- target - resolution (negative = breached)
    loaded_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    source_file        TEXT,
    rows_read          INTEGER,
    rows_loaded        INTEGER,
    rows_rejected      INTEGER,
    duplicates_removed INTEGER,
    new_incidents      INTEGER,
    missing_values     TEXT,                       -- JSON {column: count} from the raw file
    status             TEXT
);

CREATE TABLE IF NOT EXISTS rejected_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES pipeline_runs(run_id),
    incident_id TEXT,
    reason      TEXT NOT NULL,
    raw_record  TEXT NOT NULL                      -- original row as JSON, for auditing
);

CREATE TABLE IF NOT EXISTS predictions (
    incident_id        TEXT PRIMARY KEY REFERENCES incidents(incident_id),
    breach_probability REAL NOT NULL,
    risk_level         TEXT NOT NULL,
    scored_at          TEXT NOT NULL
);
"""

INCIDENT_COLUMNS = [
    "incident_id", "created_at", "priority", "category", "affected_service",
    "assignment_group", "response_time_minutes", "resolution_time_minutes",
    "sla_target_minutes", "status", "sla_breached", "sla_margin_minutes",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect(db_path: Path | str = DB_PATH):
    """Open a connection, commit on success, roll back on error, always close."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _clean_value(v):
    """Convert pandas/numpy values into types sqlite3 understands (NaN -> NULL)."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if hasattr(v, "item"):  # numpy scalar -> python scalar
        return v.item()
    return v


# ---------------------------------------------------------------- writes
def upsert_incidents(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Insert new incidents and update existing ones. Returns how many were NEW.

    'ON CONFLICT DO UPDATE' (an upsert) is what makes the pipeline safe to rerun:
    loading the same file twice updates rows in place instead of duplicating them.
    """
    before = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    cols = INCIDENT_COLUMNS + ["loaded_at"]
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "incident_id")
    sql = (f"INSERT INTO incidents ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
           f"ON CONFLICT(incident_id) DO UPDATE SET {updates}")
    loaded_at = _now()
    rows = [tuple(_clean_value(r[c]) for c in INCIDENT_COLUMNS) + (loaded_at,)
            for r in df[INCIDENT_COLUMNS].to_dict("records")]
    conn.executemany(sql, rows)
    after = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    return after - before


def start_run(conn: sqlite3.Connection, source_file: str) -> int:
    cur = conn.execute("INSERT INTO pipeline_runs (started_at, source_file, status) VALUES (?, ?, 'running')",
                       (_now(), source_file))
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, summary: dict) -> None:
    conn.execute(
        """UPDATE pipeline_runs SET finished_at=?, rows_read=?, rows_loaded=?, rows_rejected=?,
           duplicates_removed=?, new_incidents=?, missing_values=?, status=? WHERE run_id=?""",
        (_now(), summary["rows_read"], summary["rows_loaded"], summary["rows_rejected"],
         summary["duplicates_removed"], summary["new_incidents"],
         json.dumps(summary["missing_values"]), summary["status"], run_id))


def insert_rejected(conn: sqlite3.Connection, run_id: int, rejected: pd.DataFrame) -> None:
    rows = []
    for rec in rejected.to_dict("records"):
        reason = rec.pop("rejection_reason")
        raw = {k: _clean_value(v) for k, v in rec.items()}
        rows.append((run_id, raw.get("incident_id"), reason, json.dumps(raw)))
    conn.executemany("INSERT INTO rejected_records (run_id, incident_id, reason, raw_record) VALUES (?,?,?,?)", rows)


def save_predictions(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """Replace all predictions with the latest model's scores."""
    conn.execute("DELETE FROM predictions")
    scored_at = _now()
    conn.executemany(
        "INSERT INTO predictions (incident_id, breach_probability, risk_level, scored_at) VALUES (?,?,?,?)",
        [(r.incident_id, float(r.breach_probability), r.risk_level, scored_at) for r in df.itertuples()])


# ---------------------------------------------------------------- reads
def query(sql: str, db_path: Path | str = DB_PATH, params: tuple = ()) -> pd.DataFrame:
    with connect(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def read_incidents(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    return query("""SELECT i.*, p.breach_probability, p.risk_level
                    FROM incidents i LEFT JOIN predictions p USING (incident_id)
                    ORDER BY i.created_at""", db_path)


# ---------------------------------------------------------------- SQL metrics
# Compliance is measured on RESOLVED incidents only (open ones have no outcome yet).
def kpi_summary(db_path=DB_PATH) -> dict:
    return query("""
        SELECT COUNT(*)                                                     AS total_incidents,
               ROUND(100.0 * SUM(sla_breached = 0) / COUNT(sla_breached), 1) AS sla_compliance_pct,
               ROUND(AVG(resolution_time_minutes) / 60.0, 1)                AS avg_resolution_hours,
               SUM(priority IN ('Critical','High'))                         AS high_priority_incidents,
               SUM(sla_breached IS NULL)                                    AS open_incidents
        FROM incidents""", db_path).iloc[0].to_dict()


def sla_by_dimension(dimension: str, db_path=DB_PATH) -> pd.DataFrame:
    allowed = {"priority", "category", "assignment_group", "affected_service"}
    if dimension not in allowed:  # never interpolate untrusted text into SQL
        raise ValueError(f"dimension must be one of {allowed}")
    return query(f"""
        SELECT {dimension}                                                   AS dimension,
               COUNT(*)                                                      AS incidents,
               SUM(sla_breached)                                             AS breaches,
               ROUND(100.0 * SUM(sla_breached = 0) / COUNT(sla_breached), 1) AS compliance_pct,
               ROUND(AVG(resolution_time_minutes) / 60.0, 1)                 AS avg_resolution_hours
        FROM incidents GROUP BY {dimension} ORDER BY compliance_pct""", db_path)


def monthly_trend(db_path=DB_PATH) -> pd.DataFrame:
    return query("""
        SELECT strftime('%Y-%m', created_at)                                AS month,
               COUNT(*)                                                     AS incidents,
               ROUND(100.0 * SUM(sla_breached = 0) / COUNT(sla_breached), 1) AS compliance_pct
        FROM incidents GROUP BY month ORDER BY month""", db_path)


def run_history(db_path=DB_PATH) -> pd.DataFrame:
    return query("SELECT * FROM pipeline_runs ORDER BY run_id DESC", db_path)


def rejected_for_run(run_id: int, db_path=DB_PATH) -> pd.DataFrame:
    return query("SELECT incident_id, reason, raw_record FROM rejected_records WHERE run_id = ? ORDER BY id",
                 db_path, (run_id,))
