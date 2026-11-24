import json
import sqlite3
from datetime import date

import pandas as pd
import pytest

from src import investigations
from src.calculations import CalculationContext, CalculationEngine


def build_trace(source_kind="demo"):
    incidents = pd.DataFrame([
        {"incident_id": "INC-A", "status": "Closed", "priority": "High"},
        {"incident_id": "INC-B", "status": "Open", "priority": "Low"},
    ])
    import_id = "stable-import-id" if source_kind == "event_log" else "demo-run-4"
    engine = CalculationEngine(incidents, context=CalculationContext(
        dataset_id=import_id, source_name="Test source", source_kind=source_kind,
        import_id=import_id, timezone="unknown", observation_start="2024-01-01",
        observation_end="2024-01-02"))
    inspection = engine.inspect("unique_incident_count")
    membership = inspection["records"].loc[inspection["records"]["incident_id"].eq("INC-A")]
    trace = investigations.build_trace_reference(
        engine, "INC-A", inspection, {}, {}, membership)
    return engine, trace


def test_stable_source_ids_do_not_depend_on_demo_run_id():
    _, first = build_trace("demo")
    _, imported = build_trace("event_log")

    assert first["source_id"] == investigations.DEMO_SOURCE_ID
    assert imported["source_id"] == "stable-import-id"
    assert first["trace_id"].startswith("trace-v1-")
    assert json.loads(first["trace_json"])["evidence"]["records"][0]["incident_id"] == "INC-A"


def test_scenario_trace_labels_user_assumptions_and_keeps_only_incident_membership():
    engine, _ = build_trace()
    parameters = {"currency": "USD", "operational_cost": 1000, "incident_count": 2}
    inspection = engine.inspect("cost_per_incident", parameters)
    membership = engine.inspect("unique_incident_count")["records"]
    membership = membership.loc[membership["incident_id"].eq("INC-A")]
    trace = investigations.build_trace_reference(
        engine, "INC-A", inspection, parameters,
        {"currency": "Selected by you", "operational_cost": "Entered by you · assumption",
         "incident_count": "Entered by you · assumption"},
        membership)
    payload = json.loads(trace["trace_json"])

    assert payload["result"]["value"] == 500.0
    assert payload["inputs"]["origins"]["operational_cost"] == "Entered by you · assumption"
    assert payload["evidence"]["kind"] == "source incident membership"
    assert payload["evidence"]["record_count"] == 1
    assert payload["evidence"]["records"][0]["incident_id"] == "INC-A"


def test_trace_is_reused_and_outcomes_do_not_change_evidence(tmp_path):
    db_path = tmp_path / "investigations.db"
    _, trace = build_trace()
    investigations.initialize(db_path)

    first_id = investigations.create_investigation(
        trace, "Alex Morgan", "Review the incident.", "Check service history.",
        date(2026, 12, 1), "Analyst", db_path)
    second_id = investigations.create_investigation(
        trace, "Jordan Lee", "Compare the outcome.", "Confirm the service is stable.",
        date(2026, 12, 2), "Manager", db_path)
    original_trace = investigations.read_investigation(first_id, db_path)["trace_json"]

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM calculation_traces").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE calculation_traces SET trace_json='{}'")
    assert len(json.loads(original_trace)["evidence"]["records"]) == 1

    investigations.record_outcome(first_id, "Resolved", "Queue returned to normal.",
                                   date(2026, 12, 3), 2.5, "hours", "Analyst", db_path)
    saved = investigations.read_investigation(first_id, db_path)
    assert saved["trace_json"] == original_trace
    assert saved["status"] == "Outcome recorded"
    assert investigations.read_events(first_id, db_path).event_type.tolist() == [
        "created", "outcome_recorded"]
    assert investigations.read_investigation(second_id, db_path)["status"] == "Open"


def test_review_export_reconciles_with_the_stored_trace_and_history(tmp_path):
    db_path = tmp_path / "investigations.db"
    _, trace = build_trace()
    investigations.initialize(db_path)

    case_id = investigations.create_investigation(
        trace, "Alex Morgan", "Review the incident.", "Check service history.",
        date(2026, 12, 1), "Analyst", db_path)
    investigations.record_outcome(case_id, "Resolved", "Queue returned to normal.",
                                   date(2026, 12, 3), 2.5, "hours", "Analyst", db_path)

    saved = investigations.read_investigation(case_id, db_path)
    events = investigations.read_events(case_id, db_path)
    export = json.loads(investigations.build_review_export(saved, events))

    assert export["schema"] == investigations.REVIEW_EXPORT_SCHEMA
    assert export["investigation"]["investigation_id"] == case_id
    assert export["investigation"]["status"] == "Outcome recorded"
    assert export["outcome"]["outcome_status"] == "Resolved"
    assert export["outcome"]["measured_value"] == 2.5
    assert export["trace"]["trace_id"] == trace["trace_id"]
    assert export["trace"]["payload_sha256"] == trace["payload_sha256"]
    stored_trace = json.loads(saved["trace_json"])
    assert export["trace"]["result"] == stored_trace["result"]
    assert export["trace"]["evidence"] == stored_trace["evidence"]
    assert [item["event_type"] for item in export["history"]] == ["created", "outcome_recorded"]


def test_review_export_omits_history_when_no_events_are_supplied(tmp_path):
    db_path = tmp_path / "investigations.db"
    _, trace = build_trace()
    investigations.initialize(db_path)
    case_id = investigations.create_investigation(
        trace, "Alex Morgan", "Review the incident.", "Check service history.",
        date(2026, 12, 1), "Analyst", db_path)
    saved = investigations.read_investigation(case_id, db_path)

    export = json.loads(investigations.build_review_export(saved, pd.DataFrame()))

    assert export["history"] == []
    assert export["investigation"]["status"] == "Open"
    assert export["outcome"]["outcome_status"] is None


def test_invalid_case_or_unmeasured_unit_leaves_no_partial_changes(tmp_path):
    db_path = tmp_path / "investigations.db"
    _, trace = build_trace()
    investigations.initialize(db_path)

    with pytest.raises(ValueError, match="Owner is required"):
        investigations.create_investigation(
            trace, "", "Review it.", "Check history.", date(2026, 12, 1), "Analyst", db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM calculation_traces").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0] == 0

    case_id = investigations.create_investigation(
        trace, "Alex Morgan", "Review it.", "Check history.", date(2026, 12, 1), "Analyst", db_path)
    with pytest.raises(ValueError, match="Measured outcome unit"):
        investigations.record_outcome(case_id, "Resolved", "Done.", date(2026, 12, 2),
                                       1.0, "", "Analyst", db_path)
    saved = investigations.read_investigation(case_id, db_path)
    assert saved["status"] == "Open"
    assert investigations.read_events(case_id, db_path).event_type.tolist() == ["created"]


def test_decision_fields_and_audit_events_are_immutable(tmp_path):
    db_path = tmp_path / "investigations.db"
    _, trace = build_trace()
    case_id = investigations.create_investigation(
        trace, "Alex Morgan", "Review the incident.", "Check service history.",
        date(2026, 12, 1), "Analyst", db_path)
    investigations.record_outcome(
        case_id, "Resolved", "Queue returned to normal.", date(2026, 12, 3),
        2.5, "hours", "Analyst", db_path)

    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="decisions are immutable"):
            conn.execute("UPDATE investigations SET owner='Someone else' WHERE investigation_id=?",
                         (case_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE investigation_events SET details_json='{}' WHERE investigation_id=?",
                         (case_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM investigation_events WHERE investigation_id=?",
                         (case_id,))

    assert investigations.read_events(case_id, db_path).event_type.tolist() == [
        "created", "outcome_recorded"]
