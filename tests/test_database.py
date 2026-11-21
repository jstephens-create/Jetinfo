"""Database insertion, idempotent reruns, and the end-to-end pipeline."""
import pandas as pd

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
