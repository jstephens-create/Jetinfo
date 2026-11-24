"""Database insertion, idempotent reruns, and the end-to-end pipeline."""
import sqlite3

import pandas as pd
import pytest

from src import database
from src.etl import clean_incidents, run_pipeline


def _clean(make_raw, *rows):
    return clean_incidents(make_raw(*rows))[0]


def test_insert_and_read_back(make_raw, db_path):
    database.init_db(db_path)
    with database.connect(db_path) as conn:
        new = database.upsert_incidents(conn, _clean(make_raw, {"incident_id": "A"}, {"incident_id": "B"}))
    assert new == 2
    df = database.read_incidents(db_path)
    assert sorted(df["incident_id"]) == ["A", "B"]
    assert df.loc[df.incident_id == "A", "priority"].item() == "High"


def test_connections_enable_foreign_keys_and_a_busy_timeout(db_path):
    with database.connect(db_path) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000


def test_new_schema_rejects_non_finite_incident_durations(make_raw, db_path):
    database.init_db(db_path)
    batch = _clean(make_raw, {"incident_id": "INF"})
    batch["response_time_minutes"] = batch.response_time_minutes.astype(float)
    batch.loc[0, "response_time_minutes"] = float("inf")

    with pytest.raises(sqlite3.IntegrityError):
        with database.connect(db_path) as conn:
            database.upsert_incidents(conn, batch)

    assert database.read_incidents(db_path).empty


def test_additive_triggers_protect_legacy_incident_tables(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE incidents (
                incident_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, priority TEXT NOT NULL,
                category TEXT NOT NULL, affected_service TEXT NOT NULL, assignment_group TEXT NOT NULL,
                response_time_minutes REAL NOT NULL, resolution_time_minutes REAL,
                sla_target_minutes INTEGER NOT NULL, status TEXT NOT NULL, sla_breached INTEGER,
                sla_margin_minutes REAL, loaded_at TEXT NOT NULL
            )
        """)
        conn.execute(
            """INSERT INTO incidents VALUES
               ('A','2024-03-04 10:15:00','High','Network','VPN','Network Operations',
                20,300,480,'Closed',0,180,'2024-03-04 10:15:00')"""
        )

    database.init_db(db_path)
    with pytest.raises(sqlite3.IntegrityError, match="Incident values"):
        with database.connect(db_path) as conn:
            conn.execute("UPDATE incidents SET status='Unknown' WHERE incident_id='A'")
    with pytest.raises(sqlite3.IntegrityError, match="Incident values"):
        with database.connect(db_path) as conn:
            conn.execute("UPDATE incidents SET resolution_time_minutes=10 WHERE incident_id='A'")


def test_reloading_same_incidents_does_not_duplicate(make_raw, db_path):
    database.init_db(db_path)
    batch = _clean(make_raw, {"incident_id": "A"})
    with database.connect(db_path) as conn:
        assert database.upsert_incidents(conn, batch) == 1
    with database.connect(db_path) as conn:
        assert database.upsert_incidents(conn, batch) == 0
    assert len(database.read_incidents(db_path)) == 1


def test_upsert_updates_changed_record(make_raw, db_path):
    database.init_db(db_path)
    with database.connect(db_path) as conn:  # first seen while open
        database.upsert_incidents(conn, _clean(make_raw, {"incident_id": "A", "status": "Open",
                                                          "resolution_time_minutes": None}))
    with database.connect(db_path) as conn:  # later export: now resolved
        database.upsert_incidents(conn, _clean(make_raw, {"incident_id": "A"}))
    row = database.read_incidents(db_path).iloc[0]
    assert row["status"] == "Closed" and row["sla_breached"] == 0


def test_kpi_query(make_raw, db_path):
    database.init_db(db_path)
    rows = [{"incident_id": "A", "resolution_time_minutes": "100"},   # met
            {"incident_id": "B", "resolution_time_minutes": "900"},   # breached (High target 480)
            {"incident_id": "C", "status": "Open", "resolution_time_minutes": None, "priority": "Low"}]
    with database.connect(db_path) as conn:
        database.upsert_incidents(conn, _clean(make_raw, *rows))
    k = database.kpi_summary(db_path)
    assert k["total_incidents"] == 3
    assert k["sla_compliance_pct"] == 50.0  # open incident excluded
    assert k["high_priority_incidents"] == 2
    assert k["open_incidents"] == 1


def test_full_pipeline_is_safe_to_rerun(make_raw, tmp_path, db_path):
    raw = make_raw({"incident_id": "A"}, {"incident_id": "A"}, {"incident_id": "B", "priority": None})
    raw_csv = tmp_path / "raw.csv"
    raw.to_csv(raw_csv, index=False)
    kwargs = dict(raw_path=raw_csv, db_path=db_path, processed_path=tmp_path / "clean.csv",
                  rejected_path=tmp_path / "rej.csv")
    first = run_pipeline(**kwargs)
    second = run_pipeline(**kwargs)
    assert (first["rows_loaded"], first["rows_rejected"], first["new_incidents"]) == (1, 2, 1)
    assert second["new_incidents"] == 0
    assert len(database.read_incidents(db_path)) == 1
    assert len(database.run_history(db_path)) == 2
    assert len(database.rejected_for_run(second["run_id"], db_path)) == 2
    assert pd.read_csv(tmp_path / "clean.csv").shape[0] == 1
