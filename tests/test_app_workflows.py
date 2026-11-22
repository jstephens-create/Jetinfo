"""Exercise user journeys against isolated databases, not the portfolio's data.

Unit tests prove individual formulas. These checks prove that source selection,
navigation, evidence, and the prediction boundary stay connected in the app.
"""
import csv
import json
from inspect import signature
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config, database, demo, event_ingestion, intelligence_views
from src.etl import clean_incidents


@pytest.fixture
def application_data(tmp_path, monkeypatch, make_raw):
    demo_db = tmp_path / "demo.db"
    imports_db = tmp_path / "imports.db"
    storage = tmp_path / "source_evidence"
    database.init_db(demo_db)
    clean = clean_incidents(make_raw(
        {"incident_id": "DEMO-CLOSED"},
        {"incident_id": "DEMO-OPEN", "status": "Open", "resolution_time_minutes": None},
    ))[0]
    with database.connect(demo_db) as connection:
        database.upsert_incidents(connection, clean)

    source = tmp_path / "history.csv"
    fields = list(event_ingestion.UCI_PROFILE.field_mapping.values())
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for incident, outcome in [("REAL-A", "true"), ("REAL-B", "false")]:
            for sequence, state, updated in [(0, "New", "01/03/2016 10:00"),
                                              (1, "Closed", "01/03/2016 13:00")]:
                row = dict.fromkeys(fields, "?")
                row.update(number=incident, incident_state=state, active="false" if sequence else "true",
                           sys_mod_count=str(sequence), opened_at="01/03/2016 10:00",
                           sys_updated_at=updated, resolved_at="01/03/2016 12:00",
                           closed_at="01/03/2016 13:00", priority="2 - High", category="Category 46",
                           assignment_group="Group 1", assigned_to="Analyst 1", made_sla=outcome,
                           reassignment_count="0", reopen_count="0")
                writer.writerow(row)
    imported = event_ingestion.import_event_log(source, db_path=imports_db, storage_root=storage)

    # Default arguments in Python are bound at function definition time. Patch
    # these public boundaries explicitly rather than assuming a config change
    # will redirect functions that have already been imported by another test.
    def redirect(module, name, path, **overrides):
        original = getattr(module, name)
        contract = signature(original)
        def isolated(*args, **kwargs):
            bound = contract.bind_partial(*args, **kwargs)
            bound.arguments.update(db_path=path, **overrides)
            return original(*bound.args, **bound.kwargs)
        monkeypatch.setattr(module, name, isolated)

    for name in ["read_incidents", "kpi_summary", "run_history", "query", "rejected_for_run"]:
        redirect(database, name, demo_db)
    for name in ["ensure_workspace", "read_queue", "team_summary", "read_events",
                 "save_review", "reset_workspace"]:
        redirect(demo, name, demo_db)
    for name in ["list_imports", "read_import", "read_snapshots", "read_events", "read_rejections"]:
        redirect(event_ingestion, name, imports_db)
    redirect(event_ingestion, "import_event_log", imports_db, storage_root=storage)
    monkeypatch.setattr(config, "DB_PATH", demo_db)
    monkeypatch.setattr(config, "MODEL_PATH", tmp_path / "absent_model.joblib")
    monkeypatch.setattr(config, "METRICS_PATH", tmp_path / "absent_metrics.json")
    intelligence_views.imported_payload.clear()
    yield imported, source
    intelligence_views.imported_payload.clear()


def enter_manager():
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    assert not app.exception
    app.selectbox(key="login_role").select("Manager")
    next(button for button in app.button if button.label == "Open workspace →").click().run()
    assert not app.exception
    return app


def inspection_json(app):
    return next(json.loads(element.value) for element in app.json
                if "definition" in json.loads(element.value))


def test_demo_navigation_inspector_and_explicit_missing_scenario(application_data):
    app = enter_manager()
    app.button(key="inspect_overview_demo_sla_attainment").click().run()
    assert app.radio(key="page").value == "Calculation Inspector"
    result = inspection_json(app)["result"]
    assert result["value"] == 100.0
    assert (result["eligible_count"], result["excluded_count"]) == (1, 1)
    app.selectbox(key="inspector_metric").select("time_reduction_pct").run()
    assert inspection_json(app)["result"]["status"] == "unavailable"
    app.number_input(key="scenario_time_reduction_pct_baseline_hours").set_value(0.0)
    app.number_input(key="scenario_time_reduction_pct_observed_hours").set_value(0.0).run()
    assert inspection_json(app)["result"]["value"] is None
    for page in ["Overview", "Incident queue", "Import Desk", "Decision Support",
                 "Data quality", "Risk lab", "Project notes", "Settings & Governance"]:
        app.radio(key="page").set_value(page).run()
        assert not app.exception, page


def test_imported_source_counts_events_separately_and_never_scores_snapshot(application_data):
    imported, _ = application_data
    app = enter_manager()
    app.selectbox(key="analytical_source").select(imported.import_id).run()
    assert not app.exception
    app.button(key="inspect_overview_total_event_count").click().run()
    assert inspection_json(app)["result"]["value"] == 4
    assert len(app.dataframe[0].value) == 4
    app.selectbox(key="inspector_metric").select("source_sla_attainment").run()
    result = inspection_json(app)["result"]
    assert result["value"] == 50.0
    assert (result["numerator"], result["denominator"]) == (1, 2)
    assert result["import_id"] == imported.import_id
    for page in ["Incident queue", "Data quality", "Decision Support", "Settings & Governance"]:
        app.radio(key="page").set_value(page).run()
        assert not app.exception, page
    app.radio(key="page").set_value("Risk lab").run()
    assert not app.exception
    assert any("not scored" in item.value for item in app.info)


def test_local_import_reuses_identity_and_rule_form_runs(application_data):
    imported, source = application_data
    app = enter_manager()
    app.radio(key="page").set_value("Import Desk").run()
    next(item for item in app.radio if item.label == "CSV location").set_value("Local file on this machine").run()
    next(item for item in app.text_input if item.label == "Local CSV path").input(str(source))
    next(button for button in app.button if button.label == "Validate and import →").click().run()
    assert not app.exception
    assert app.selectbox(key="analytical_source").value == imported.import_id
    assert app.session_state["import_notice"]["idempotent_reuse"] is True
    app.radio(key="page").set_value("Decision Support").run()
    next(button for button in app.button if button.label == "Evaluate investigation rules →").click().run()
    assert not app.exception
    assert any("No investigation rules matched" in item.value for item in app.info)
