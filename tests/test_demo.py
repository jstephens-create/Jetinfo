"""Demo edits persist and remain separate from training facts and other visitors."""
import json

import pandas as pd
import pytest

from src import database, demo
from src.etl import clean_incidents

WORKSPACE = "12345678123456781234567812345678"
OTHER_WORKSPACE = "22345678123456781234567812345678"


@pytest.fixture
def workspace_db(make_raw, db_path):
    database.init_db(db_path)
    clean, _, _ = clean_incidents(make_raw(
        {"incident_id": "OPEN", "status": "Open", "resolution_time_minutes": None},
        {"incident_id": "CLOSED", "assignment_group": "Service Desk"},
    ))
    with database.connect(db_path) as conn:
        database.upsert_incidents(conn, clean)
        database.save_predictions(conn, pd.DataFrame([
            {"incident_id": "OPEN", "breach_probability": 0.8, "risk_level": "High"},
            {"incident_id": "CLOSED", "breach_probability": 0.2, "risk_level": "Low"},
        ]))
    demo.ensure_workspace(WORKSPACE, db_path)
    demo.ensure_workspace(OTHER_WORKSPACE, db_path)
    return db_path


def save(db_path, **changes):
    args = dict(workspace_id=WORKSPACE, incident_id="OPEN", role="Analyst",
                assigned_team="Service Desk", owner="Alex Morgan", review_state="In review",
                note="Investigate the service impact.", db_path=db_path)
    args.update(changes)
    return demo.save_review(**args)


def test_review_persists_with_an_audit_trail_and_preserves_model_inputs(workspace_db):
    original = database.read_incidents(workspace_db)
    assert save(workspace_db)
    row = demo.read_queue(WORKSPACE, workspace_db).iloc[0]
    assert (row["assigned_team"], row["owner"], row["review_state"], row["note_count"]) == (
        "Service Desk", "Alex Morgan", "In review", 1)
    event = demo.read_events(WORKSPACE, db_path=workspace_db).iloc[0]
    assert json.loads(event["before_json"])["assigned_team"] == "Network Operations"
    assert json.loads(event["after_json"])["assigned_team"] == "Service Desk"
    assert event["actor"] == "Alex Morgan"
    pd.testing.assert_frame_equal(original, database.read_incidents(workspace_db))


def test_demo_workspaces_are_isolated_and_no_op_saves_do_not_add_events(workspace_db):
    save(workspace_db)
    assert not save(workspace_db, note="  ")
    assert len(demo.read_events(WORKSPACE, db_path=workspace_db)) == 1
    other = demo.read_queue(OTHER_WORKSPACE, workspace_db).iloc[0]
    assert other["review_state"] == "Unreviewed"
    assert other["owner"] == "Unassigned"
    assert demo.read_events(OTHER_WORKSPACE, db_path=workspace_db).empty


@pytest.mark.parametrize("changes, message", [
    ({"incident_id": "CLOSED"}, "Only open"),
    ({"incident_id": "MISSING"}, "Only open"),
    ({"assigned_team": "Unknown team"}, "Choose a team"),
    ({"owner": "Unknown user"}, "valid owner"),
    ({"role": "Unknown role"}, "valid demo role"),
    ({"note": "x" * 1501}, "1,500 characters"),
])
def test_invalid_edits_leave_no_partial_review_or_event(workspace_db, changes, message):
    with pytest.raises(ValueError, match=message):
        save(workspace_db, **changes)
    assert demo.read_events(WORKSPACE, db_path=workspace_db).empty
    assert demo.read_queue(WORKSPACE, workspace_db).iloc[0]["review_state"] == "Unreviewed"


def test_manager_summary_reflects_assignments_and_reset_is_limited_to_its_workspace(workspace_db):
    save(workspace_db)
    save(workspace_db, workspace_id=OTHER_WORKSPACE)
    summary = demo.team_summary(WORKSPACE, workspace_db).iloc[0]
    assert (summary["team"], summary["reviewed"], summary["high_risk"]) == ("Service Desk", 1, 1)
    with pytest.raises(PermissionError):
        demo.reset_workspace(WORKSPACE, "Analyst", workspace_db)
    demo.reset_workspace(WORKSPACE, "Admin", workspace_db)
    assert demo.read_events(WORKSPACE, db_path=workspace_db).empty
    assert demo.read_queue(WORKSPACE, workspace_db).iloc[0]["review_state"] == "Unreviewed"
    assert len(demo.read_events(OTHER_WORKSPACE, db_path=workspace_db)) == 1
    assert len(database.read_incidents(workspace_db)) == 2
