"""SQLite storage layer: schema, safe writes, and SQL metric queries.

SQL for incident facts and analytical metrics lives here. The dashboard reads
these source facts; demo review writes use separate tables in src/demo.py.
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
    response_time_minutes   REAL NOT NULL CHECK (
        response_time_minutes >= 0 AND response_time_minutes <= 1.7976931348623157e308
    ),
    resolution_time_minutes REAL CHECK (
        resolution_time_minutes IS NULL OR
        (resolution_time_minutes >= 0 AND resolution_time_minutes <= 1.7976931348623157e308)
    ),                                              -- NULL while incident is open
    sla_target_minutes      INTEGER NOT NULL CHECK (sla_target_minutes > 0),
    status                  TEXT NOT NULL CHECK (status IN ('Resolved','Closed','Open','In Progress')),
    sla_breached            INTEGER CHECK (sla_breached IN (0, 1) OR sla_breached IS NULL),
    sla_margin_minutes      REAL CHECK (
        sla_margin_minutes IS NULL OR abs(sla_margin_minutes) <= 1.7976931348623157e308
    ),                                              -- target - resolution (negative = breached)
    loaded_at               TEXT NOT NULL
);

-- Additive guards also protect databases created before these CHECK constraints.
CREATE TRIGGER IF NOT EXISTS incidents_integrity_insert
BEFORE INSERT ON incidents
WHEN NEW.sla_target_minutes <= 0
  OR NEW.status NOT IN ('Resolved','Closed','Open','In Progress')
  OR NEW.response_time_minutes > 1.7976931348623157e308
  OR (NEW.resolution_time_minutes IS NOT NULL AND
      (NEW.resolution_time_minutes < NEW.response_time_minutes
       OR NEW.resolution_time_minutes > 1.7976931348623157e308))
  OR (NEW.sla_breached IS NOT NULL AND NEW.sla_breached NOT IN (0, 1))
  OR (NEW.sla_margin_minutes IS NOT NULL AND abs(NEW.sla_margin_minutes) > 1.7976931348623157e308)
  OR (NEW.status IN ('Open','In Progress') AND
      (NEW.resolution_time_minutes IS NOT NULL OR NEW.sla_breached IS NOT NULL))
  OR (NEW.status IN ('Resolved','Closed') AND
      (NEW.resolution_time_minutes IS NULL OR NEW.sla_breached IS NULL))
BEGIN
    SELECT RAISE(ABORT, 'Incident values violate operational data constraints.');
END;

CREATE TRIGGER IF NOT EXISTS incidents_integrity_update
BEFORE UPDATE ON incidents
WHEN NEW.sla_target_minutes <= 0
  OR NEW.status NOT IN ('Resolved','Closed','Open','In Progress')
  OR NEW.response_time_minutes > 1.7976931348623157e308
  OR (NEW.resolution_time_minutes IS NOT NULL AND
      (NEW.resolution_time_minutes < NEW.response_time_minutes
       OR NEW.resolution_time_minutes > 1.7976931348623157e308))
  OR (NEW.sla_breached IS NOT NULL AND NEW.sla_breached NOT IN (0, 1))
  OR (NEW.sla_margin_minutes IS NOT NULL AND abs(NEW.sla_margin_minutes) > 1.7976931348623157e308)
  OR (NEW.status IN ('Open','In Progress') AND
      (NEW.resolution_time_minutes IS NOT NULL OR NEW.sla_breached IS NOT NULL))
  OR (NEW.status IN ('Resolved','Closed') AND
      (NEW.resolution_time_minutes IS NULL OR NEW.sla_breached IS NULL))
BEGIN
    SELECT RAISE(ABORT, 'Incident values violate operational data constraints.');
END;

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
    """Open a connection, commit on success, roll back on error, always close.

    A caller's ``with connect(...) as conn`` block defines one transaction for
    its ordinary SQL writes. Related rows are saved together or not at all.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    # SQLite requires this switch for each connection; REFERENCES declarations
    # alone do not enforce that predictions/rejections point to existing parents.
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
    # Column names come from our fixed list. Question marks bind row VALUES
    # separately from SQL, so quotes in source text are handled as data.
    loaded_at = _now()
    rows = [tuple(_clean_value(r[c]) for c in INCIDENT_COLUMNS) + (loaded_at,)
            for r in df[INCIDENT_COLUMNS].to_dict("records")]
    conn.executemany(sql, rows)
    # Updates are not new incidents. Comparing table sizes gives the number of
    # newly inserted IDs, rather than the number of rows processed in this run.
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
    # This table is a current snapshot, not a model/prediction history. DELETE and
    # INSERT share the caller's transaction so readers never get a committed
    # half-replaced snapshot.
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
    # A LEFT JOIN preserves incidents that have not been scored yet; an INNER
    # JOIN would silently remove them from the dashboard's incident population.
    return query("""SELECT i.*, p.breach_probability, p.risk_level
                    FROM incidents i LEFT JOIN predictions p USING (incident_id)
                    ORDER BY i.created_at""", db_path)


# ------------------------------------------------ compatibility metric reads
# Keep these long-standing names for callers, while the shared calculation
# engine owns numerical definitions used by dashboards, tools, and inspectors.
def calculation_engine(db_path=DB_PATH):
    """Build an explicitly synthetic engine without mixing imported histories.

    Local imports avoid a dependency cycle: calculations never imports storage,
    and ETL can still import the database while using the shared SLA helper.
    """
    from src.calculations import CalculationContext, CalculationEngine
    incidents = read_incidents(db_path)
    start = incidents.created_at.min() if not incidents.empty else None
    end = incidents.created_at.max() if not incidents.empty else None
    context = CalculationContext("synthetic-demo", "Seeded synthetic incidents", source_kind="demo",
                                 observation_start=start, observation_end=end)
    return CalculationEngine(incidents, context=context)


def kpi_summary(db_path=DB_PATH) -> dict:
    """Return legacy keys using the same definitions as the inspector."""
    engine = calculation_engine(db_path)
    return {"total_incidents": engine.calculate("unique_incident_count").value,
            "sla_compliance_pct": engine.calculate("demo_sla_attainment").value,
            "avg_resolution_hours": engine.calculate("mean_resolution_hours").value,
            "high_priority_incidents": engine.calculate("high_priority_incident_count").value,
            "open_incidents": engine.calculate("unresolved_incident_count").value}


def sla_by_dimension(dimension: str, db_path=DB_PATH) -> pd.DataFrame:
    """Aggregate each group, retaining distinct denominators for volume and SLA.

    ``incidents`` counts every ticket in a group; ``compliance_pct`` uses only
    tickets with known outcomes. Group percentages should not be averaged to
    produce overall compliance: recompute it from the underlying outcome counts.
    """
    return calculation_engine(db_path).by_dimension(dimension)


def monthly_trend(db_path=DB_PATH) -> pd.DataFrame:
    return calculation_engine(db_path).monthly_trend()


def run_history(db_path=DB_PATH) -> pd.DataFrame:
    return query("SELECT * FROM pipeline_runs ORDER BY run_id DESC", db_path)


def rejected_for_run(run_id: int, db_path=DB_PATH) -> pd.DataFrame:
    return query("SELECT incident_id, reason, raw_record FROM rejected_records WHERE run_id = ? ORDER BY id",
                 db_path, (run_id,))
