"""Exercise user journeys against isolated databases, not the portfolio's data.

Unit tests prove individual formulas. These checks prove that source selection,
navigation, evidence, and the prediction boundary stay connected in the app.
"""
import ast
import csv
import json
from inspect import signature
from pathlib import Path

import pytest
import pandas as pd
import joblib
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import config, database, demo, event_ingestion, intelligence_views, tutorial, views
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


def complete_orientation(app):
    assert app.session_state["tutorial"]["index"] == 0
    assert app.button(key="tutorial_next").disabled
    assert any("Next is locked" in item.value for item in app.markdown)
    app.button(key="tutorial_begin_queue").click().run()
    assert app.radio(key="page").value == "Incident queue"
    assert not app.button(key="tutorial_next").disabled
    assert app.session_state["tutorial"]["index"] == 0
    app.button(key="tutorial_continue_focus").click().run()
    assert app.session_state["tutorial"]["index"] == 1


def test_entry_point_demo_function_references_exist():
    tree = ast.parse((Path(config.ROOT) / "app.py").read_text(encoding="utf-8"))
    functions = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "demo"
    }
    assert "owner_label" in functions
    assert all(callable(getattr(demo, name, None)) for name in functions)


def test_tutorial_references_exist_across_application_modules():
    references = set()
    for path in (Path("app.py"), Path("src") / "views.py", Path("src") / "intelligence_views.py"):
        tree = ast.parse((Path(config.ROOT) / path).read_text(encoding="utf-8"))
        references.update(
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "tutorial"
        )
    assert "navigation_observed" in references
    assert {name for name in references if not hasattr(tutorial, name)} == set()
    signature(tutorial.navigation_observed).bind()


@pytest.mark.parametrize("page,source,role,paused,verified", [
    ("Overview", "demo", "Analyst", False, False),
    ("Data quality", "demo", "Analyst", False, False),
    ("Incident queue", "imported", "Analyst", False, False),
    ("Incident queue", "demo", "Manager", False, False),
    ("Incident queue", "demo", "Analyst", True, False),
    ("Incident queue", "demo", "Analyst", False, True),
])
def test_navigation_observation_requires_active_matching_context(monkeypatch, page, source, role, paused, verified):
    state = {"persona_role": "Analyst"}
    monkeypatch.setattr(tutorial.st, "session_state", state)
    tutorial.start("Analyst")
    state.update(page=page, analytical_source=source, persona_role=role)
    state["tutorial"]["paused"] = paused
    tutorial.navigation_observed()
    assert state["tutorial"]["verified"] is verified
    assert state["tutorial"]["index"] == 0
    assert state["tutorial"]["completed"] == []


@pytest.mark.parametrize("role", list(demo.PROFILES))
def test_persona_login_and_sidebar_role_switches(application_data, role):
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert demo.owner_label(demo.PROFILES[role]["name"]) in app.selectbox(key="login_role").options[
        list(demo.PROFILES).index(role)]
    app.selectbox(key="login_role").select(role)
    next(button for button in app.button if button.label == "Open workspace →").click().run()
    assert not app.exception
    assert app.selectbox(key="persona_role").value == role
    for selected in demo.PROFILES:
        app.selectbox(key="persona_role").select(selected).run()
        assert not app.exception
        assert app.selectbox(key="persona_role").value == selected
        assert demo.owner_label(demo.PROFILES[selected]["name"]) in app.selectbox(key="persona_role").options[
            list(demo.PROFILES).index(selected)]


def test_demo_navigation_inspector_and_explicit_missing_scenario(application_data):
    app = enter_manager()
    app.button(key="inspect_overview_demo_sla_attainment").click().run()
    assert app.radio(key="page").value == "Calculation Inspector"
    result = inspection_json(app)["result"]
    assert result["value"] == 100.0
    assert (result["eligible_count"], result["excluded_count"]) == (1, 1)
    app.radio(key="inspector_group").set_value("needs_inputs").run()
    app.selectbox(key="inspector_metric").select("time_saved_hours").run()
    assert inspection_json(app)["result"]["status"] == "unavailable"
    app.number_input(key="scenario_time_saved_hours_baseline_hours").set_value(0.0)
    app.number_input(key="scenario_time_saved_hours_observed_hours").set_value(0.0).run()
    assert inspection_json(app)["result"]["value"] == 0
    assert any("Percentage unavailable:" in item.value for item in app.caption)
    app.number_input(key="scenario_time_saved_hours_baseline_hours").set_value(10.0)
    app.number_input(key="scenario_time_saved_hours_observed_hours").set_value(6.0).run()
    assert inspection_json(app)["result"]["value"] == 4
    assert any("Processing time reduction:" in item.value and "40.0%" in item.value for item in app.markdown)
    for page in ["Overview", "Incident queue", "Import Desk", "Decision Support",
                 "Data quality", "Risk lab", "Project notes", "Settings & Governance"]:
        app.radio(key="page").set_value(page).run()
        assert not app.exception, page


def test_cost_per_incident_flow_uses_source_count_only_when_confirmed(application_data):
    app = enter_manager()
    app.button(key="inspect_overview_demo_sla_attainment").click().run()
    app.radio(key="inspector_group").set_value("needs_inputs").run()
    app.selectbox(key="inspector_metric").select("cost_per_incident").run()
    assert not app.exception
    assert any("does not read an operational cost field" in item.value for item in app.markdown)
    assert any("Possible inclusions" in item.value and "Exclude" in item.value for item in app.markdown)
    assert inspection_json(app)["result"]["status"] == "unavailable"
    app.selectbox(key="currency_cost_per_incident").select("USD").run()
    app.number_input(key="scenario_cost_per_incident_operational_cost").set_value(1000.0).run()
    assert inspection_json(app)["result"]["status"] == "unavailable"
    basis = next(r for r in app.radio if r.key.startswith("count_basis_cost_per_incident_"))
    assert basis.value is None and "unique incidents" in basis.options[0]
    basis.set_value(basis.options[0]).run()
    assert not app.exception
    result = inspection_json(app)["result"]
    assert (result["value"], result["unit"], result["denominator"]) == (500.0, "USD/incident", 2)
    assert len(app.dataframe[-1].value) == 2
    assert any("your assumption" in n.label for n in app.number_input)


def test_source_navigation_and_metric_search(application_data):
    app = enter_manager()
    assert app.radio(key="page").options[:2] == ["Overview", "Incident queue"]
    assert app.radio(key="page").options[-1] == "Import Desk"
    app.button(key="source_import").click().run()
    assert app.radio(key="page").value == "Import Desk"
    app.radio(key="page").set_value("Overview").run()
    app.button(key="inspect_overview_demo_sla_attainment").click().run()
    assert any("Eligibility and exclusions" in item.value for item in app.markdown)
    app.radio(key="inspector_group").set_value("needs_inputs").run()
    next(item for item in app.text_input if item.label == "Find a metric").input("operational cost").run()
    assert app.selectbox(key="inspector_metric").value == "cost_per_incident"
    next(item for item in app.text_input if item.label == "Find a metric").input("reduction").run()
    assert app.selectbox(key="inspector_metric").value == "time_saved_hours"
    assert len(app.selectbox(key="inspector_metric").options) == 1
    next(item for item in app.text_input if item.label == "Find a metric").input("nonexistent").run()
    assert any("No metrics in this group" in item.value for item in app.info)
    app.radio(key="page").set_value("Overview").run()
    app.button(key="inspect_overview_demo_sla_attainment").click().run()
    assert app.selectbox(key="inspector_metric").value == "demo_sla_attainment"
    assert app.text_input(key="inspector_search").value == ""
    assert not app.exception


def test_imported_source_counts_events_separately_and_never_scores_snapshot(application_data):
    imported, _ = application_data
    app = enter_manager()
    app.selectbox(key="analytical_source").select(imported.import_id).run()
    assert not app.exception
    app.button(key="inspect_overview_total_event_count").click().run()
    assert inspection_json(app)["result"]["value"] == 4
    assert len(app.dataframe[-1].value) == 4
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


@pytest.mark.parametrize("role,first", [("Analyst", "queue"), ("Manager", "overview"), ("Admin", "quality")])
def test_guided_missions_cover_each_persona_and_real_demo_actions(application_data, role, first):
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    assert all(demo.owner_label(profile["name"]) in option
               for profile, option in zip(demo.PROFILES.values(), app.selectbox(key="login_role").options))
    app.selectbox(key="login_role").select(role)
    next(button for button in app.button if button.label == "Start guided demo").click().run()
    assert app.session_state["tutorial"]["order"][:2] == ["orientation", first]
    assert app.selectbox(key="analytical_source").value == "demo"
    assert not app.exception

    while app.session_state["tutorial"]["index"] < len(app.session_state["tutorial"]["order"]):
        state = app.session_state["tutorial"]
        mission = state["order"][state["index"]]
        assert any("Key moment:" in item.value for item in app.info)
        assert app.button(key="tutorial_next").disabled
        if mission == "orientation":
            app.button(key="tutorial_begin_queue").click().run()
            assert app.radio(key="page").value == "Incident queue"
        elif mission == "overview":
            app.button(key="inspect_overview_demo_sla_attainment").click().run()
            assert app.radio(key="page").value == "Calculation Inspector"
        elif mission == "inspector":
            assert app.selectbox(key="inspector_metric").value == "demo_sla_attainment"
            app.button(key="inspector_action_excluded").click().run()
            assert app.radio(key="inspector_evidence").value == "Excluded"
        elif mission == "limits":
            assert app.selectbox(key="inspector_metric").value == "total_event_count"
            assert inspection_json(app)["result"]["status"] == "unavailable"
            app.radio(key="tutorial_answer_limits").set_value("Every incident snapshot is one historical event").run()
            assert app.button(key="tutorial_next").disabled
            app.radio(key="tutorial_answer_limits").set_value(
                "The demo contains incident snapshots, not an event history").run()
        elif mission == "scenario":
            assert app.selectbox(key="inspector_metric").value == "cost_per_incident"
            assert any("select USD" in item.value and "1,000" in item.value for item in app.markdown)
            app.selectbox(key="currency_cost_per_incident").select("USD").run()
            app.number_input(key="scenario_cost_per_incident_operational_cost").set_value(1000.0).run()
            basis = next(r for r in app.radio if r.key.startswith("count_basis_cost_per_incident_"))
            basis.set_value(basis.options[-1]).run()
            app.number_input(key="scenario_cost_per_incident_incident_count").set_value(5).run()
            assert app.button(key="tutorial_next").disabled
            app.number_input(key="scenario_cost_per_incident_incident_count").set_value(10).run()
            assert inspection_json(app)["result"]["value"] == 100
        elif mission == "time":
            app.number_input(key="scenario_time_saved_hours_baseline_hours").set_value(10.0)
            app.number_input(key="scenario_time_saved_hours_observed_hours").set_value(6.0).run()
            assert inspection_json(app)["result"]["value"] == 4
            assert any("40.0%" in item.value for item in app.markdown)
        elif mission == "queue":
            incident = app.selectbox(key="review_incident").value
            assert app.selectbox(key=f"review_owner_{incident}").options == [
                "Unassigned", "Alex Morgan — Service desk analyst (mock)",
                "Jordan Lee — Operations manager (mock)", "Casey Brooks — Data administrator (mock)"]
            app.selectbox(key=f"review_owner_{incident}").select("Alex Morgan")
            app.selectbox(key=f"review_status_{incident}").select("In review")
            app.text_area(key=f"review_note_{incident}").input("Practice handover")
            next(button for button in app.button if button.label == "Save review →").click().run()
            assert any("Review saved" in item.value for item in app.success)
            assert any("owner" in frame.value.columns and demo.owner_label("Alex Morgan")
                       in frame.value["owner"].tolist() for frame in app.dataframe)
            assert any(demo.owner_label(demo.PROFILES[role]["name"]) in item.value
                       and demo.owner_label("Alex Morgan") in item.value for item in app.get("html"))
        elif mission == "decision":
            next(button for button in app.button if button.label == "Evaluate investigation rules →").click().run()
            assert app.session_state["decision_evidence"]["source"] == "synthetic-demo"
        elif mission == "governance":
            app.radio(key="tutorial_answer_governance").set_value(
                "Production authentication isolates each user's imports").run()
            assert app.button(key="tutorial_next").disabled
            app.radio(key="tutorial_answer_governance").set_value(
                "Personas are simulated and imports are shared locally").run()
        elif mission in {"quality", "risk"}:
            app.button(key="tutorial_skip").click().run()
            continue
        assert not app.button(key="tutorial_next").disabled
        app.button(key="tutorial_continue_focus").click().run()
        assert not app.exception
    assert len(app.session_state["tutorial"]["completed"]) == 9
    assert set(app.session_state["tutorial"]["skipped"]) == {"quality", "risk"}
    assert any("Tour finished" in item.value for item in app.success)
    event = demo.read_events(app.query_params["workspace"]).iloc[0]
    assert event["note"] == "Practice handover"
    assert json.loads(event["after_json"])["owner"] == "Alex Morgan"


def test_tutorial_is_separate_from_import_and_resumes_only_on_request(application_data):
    imported, source = application_data
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    app.selectbox(key="login_role").select("Manager")
    next(button for button in app.button if button.label == "Import a CSV").click().run()
    assert app.radio(key="page").value == "Import Desk"
    assert "tutorial" not in app.session_state
    app.selectbox(key="analytical_source").select(imported.import_id).run()
    app.button(key="tutorial_start").click().run()
    assert app.selectbox(key="analytical_source").value == "demo"
    complete_orientation(app)
    assert any("st-key-inspect_overview_demo_sla_attainment" in item.value for item in app.get("html"))
    app.button(key="source_import").click().run()
    assert not any(button.key == "tutorial_next" for button in app.button)
    assert not any("st-key-inspect_overview_demo_sla_attainment" in item.value for item in app.get("html"))
    next(item for item in app.radio if item.label == "CSV location").set_value("Local file on this machine").run()
    next(item for item in app.text_input if item.label == "Local CSV path").input(str(source))
    next(button for button in app.button if button.label == "Validate and import →").click().run()
    assert app.selectbox(key="analytical_source").value == imported.import_id
    assert app.session_state["tutorial"]["index"] == 1
    assert app.button(key="tutorial_back").disabled
    assert not any(button.key == "tutorial_next" for button in app.button)
    app.button(key="tutorial_resume").click().run()
    assert app.selectbox(key="analytical_source").value == "demo"
    assert app.radio(key="page").value == "Overview"
    app.radio(key="page").set_value("Incident queue").run()
    app.button(key="tutorial_go").click().run()
    assert app.radio(key="page").value == "Overview"
    app.button(key="tutorial_pause").click().run()
    assert not any("Key moment:" in item.value for item in app.info)
    app.selectbox(key="persona_role").select("Analyst").run()
    assert any(button.key == "tutorial_restart_role" for button in app.button)
    assert not app.exception


def test_tutorial_requires_a_saved_complete_handover(application_data):
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    app.selectbox(key="login_role").select("Analyst")
    next(button for button in app.button if button.label == "Start guided demo").click().run()
    complete_orientation(app)
    incident = app.selectbox(key="review_incident").value
    assert any("RISK UNAVAILABLE" in item.value for item in app.get("html"))
    app.selectbox(key=f"review_owner_{incident}").select("Alex Morgan")
    next(button for button in app.button if button.label == "Save review →").click().run()
    assert app.button(key="tutorial_next").disabled
    assert any("choose a review state" in item.value and "write a handover note" in item.value
               for item in app.warning)
    app.selectbox(key=f"review_status_{incident}").select("In review")
    app.text_area(key=f"review_note_{incident}").input("Follow up")
    next(button for button in app.button if button.label == "Save review →").click().run()
    assert not app.button(key="tutorial_next").disabled
    assert app.session_state["tutorial"]["index"] == 1


def test_orientation_accepts_sidebar_navigation_and_preserves_progress_on_rerun(application_data):
    app = enter_manager()
    app.button(key="tutorial_start").click().run()
    assert app.button(key="tutorial_next").disabled
    app.radio(key="page").set_value("Data quality").run()
    assert app.button(key="tutorial_next").disabled
    assert app.session_state["tutorial"]["index"] == 0
    app.radio(key="page").set_value("Incident queue").run()
    assert not app.button(key="tutorial_next").disabled
    app.run()
    assert not app.button(key="tutorial_next").disabled
    app.button(key="tutorial_continue_focus").click().run()
    assert app.session_state["tutorial"]["completed"] == ["orientation"]
    app.radio(key="page").set_value("Risk lab").run()
    assert app.button(key="tutorial_next").disabled
    assert any("Return to Overview" in item.value for item in app.warning)
    app.button(key="tutorial_go_focus").click().run()
    assert app.radio(key="page").value == "Overview"
    assert app.session_state["tutorial"]["completed"] == ["orientation"]
    assert not app.exception


def test_queue_guide_explains_filtered_empty_results(application_data):
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    next(button for button in app.button if button.label == "Start guided demo").click().run()
    complete_orientation(app)
    app.text_input(key="queue_search").input("not-an-incident").run()
    assert app.button(key="tutorial_next").disabled
    assert any("Clear the filters" in item.value for item in app.info)
    app.text_input(key="queue_search").input("").run()
    assert app.selectbox(key="review_incident").value


@pytest.mark.parametrize("mission", ["overview", "inspector"])
def test_inspection_missions_wait_for_successful_evidence_load(application_data, monkeypatch, mission):
    app = enter_manager()
    app.button(key="tutorial_start").click().run()
    complete_orientation(app)
    if mission == "inspector":
        app.button(key="inspect_overview_demo_sla_attainment").click().run()
        app.button(key="tutorial_continue_focus").click().run()
    original = intelligence_views.CalculationEngine.inspect
    monkeypatch.setattr(intelligence_views.CalculationEngine, "inspect",
                        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("Evidence unavailable")))
    key = "inspect_overview_demo_sla_attainment" if mission == "overview" else "inspector_action_excluded"
    app.button(key=key).click().run()
    assert app.button(key="tutorial_next").disabled
    assert any("Evidence unavailable" in item.value for item in app.error)
    monkeypatch.setattr(intelligence_views.CalculationEngine, "inspect", original)
    app.run()
    assert not app.button(key="tutorial_next").disabled
    assert not app.exception


def test_corrupt_model_does_not_break_other_demo_pages(application_data, tmp_path, monkeypatch):
    model_path = tmp_path / "corrupt.joblib"
    model_path.write_bytes(b"not a model")
    monkeypatch.setattr(config, "MODEL_PATH", model_path)
    app = enter_manager()
    assert not app.exception
    app.radio(key="page").set_value("Incident queue").run()
    assert not app.exception
    assert any("model could not be loaded" in item.value for item in app.warning)
    assert any("RISK UNAVAILABLE" in item.value for item in app.get("html"))


def test_tutorial_back_reuses_verified_progress_without_duplicates_and_exit_preserves_source(application_data):
    app = enter_manager()
    app.button(key="tutorial_start").click().run()
    complete_orientation(app)
    app.button(key="inspect_overview_demo_sla_attainment").click().run()
    app.button(key="tutorial_continue_focus").click().run()
    assert app.session_state["tutorial"]["completed"] == ["orientation", "overview"]
    app.button(key="tutorial_back").click().run()
    assert app.session_state["tutorial"]["index"] == 1
    assert not app.button(key="tutorial_next").disabled
    app.button(key="tutorial_continue_focus").click().run()
    assert app.session_state["tutorial"]["completed"] == ["orientation", "overview"]
    app.button(key="tutorial_exit").click().run()
    assert "tutorial" not in app.session_state
    assert app.selectbox(key="analytical_source").value == "demo"
    assert not app.exception


def test_older_self_reported_tutorial_can_restart_without_claiming_verification(application_data):
    app = enter_manager()
    app.session_state["tutorial"] = {"role": "Manager", "order": ["overview"], "index": 0,
                                     "tried": [], "skipped": [], "paused": False, "last": None}
    app.run()
    assert not app.exception
    assert any("guide was updated" in item.value for item in app.caption)
    app.button(key="tutorial_restart").click().run()
    assert app.session_state["tutorial"]["completed"] == []
    assert not app.exception


def test_quality_and_risk_missions_verify_actions_when_available(application_data, tmp_path, monkeypatch):
    with database.connect(config.DB_PATH) as connection:
        run = database.start_run(connection, "demo.csv")
        database.finish_run(connection, run, {"rows_read": 2, "rows_loaded": 2, "rows_rejected": 0,
            "duplicates_removed": 0, "new_incidents": 2, "missing_values": {"priority": 0}, "status": "success"})
    model_path = tmp_path / "test_model.joblib"
    model_path.write_bytes(b"test")
    metrics_path = tmp_path / "test_metrics.json"
    scores = {"precision": 0.5, "recall": 0.5, "f1": 0.5, "roc_auc": 0.5}
    metrics = {"model": {**scores, "confusion_matrix": {"tn": 1, "fp": 0, "fn": 0, "tp": 1}},
               "baseline_priority_rate": scores, "baseline_majority_class": scores,
               "split": {"train_rows": 2, "train_start": "2024-01-01", "train_end": "2024-02-01",
                         "test_rows": 2, "test_start": "2024-03-01", "test_end": "2024-04-01",
                         "test_breach_rate": 0.5},
               "roc_curve": {"fpr": [0, 1], "tpr": [0, 1]},
               "coefficients": [{"feature": "Priority", "coefficient": 0.1}]}
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    monkeypatch.setattr(config, "MODEL_PATH", model_path)
    monkeypatch.setattr(config, "METRICS_PATH", metrics_path)
    monkeypatch.setattr(joblib, "load", lambda path: object())
    monkeypatch.setattr(views, "predict", lambda model, data: [0.5])
    monkeypatch.setattr(views, "explain", lambda model, data: pd.DataFrame(
        [{"feature": "Priority", "contribution": 0.1}]))
    st.cache_data.clear()
    app = AppTest.from_file(str(Path(config.ROOT) / "app.py"), default_timeout=30).run()
    app.selectbox(key="login_role").select("Admin")
    next(button for button in app.button if button.label == "Start guided demo").click().run()
    complete_orientation(app)
    assert app.session_state["tutorial"]["order"][1] == "quality"
    assert not app.exception
    assert app.button(key="tutorial_next").disabled
    app.radio(key="tutorial_answer_quality").set_value("Only loaded and invalid source rows").run()
    assert app.button(key="tutorial_next").disabled
    app.radio(key="tutorial_answer_quality").set_value("Loaded, duplicate, and invalid source rows").run()
    assert not app.button(key="tutorial_next").disabled
    app.button(key="tutorial_continue_focus").click().run()
    while app.session_state["tutorial"]["order"][app.session_state["tutorial"]["index"]] != "risk":
        app.session_state["score_category"] = "Network"
        app.button(key="tutorial_skip").click().run()
        assert not app.exception
    assert app.button(key="tutorial_next").disabled
    monkeypatch.setattr(views, "predict", lambda model, data: (_ for _ in ()).throw(ValueError("Scoring failed")))
    app.selectbox(key="score_priority").select("Critical").run()
    assert not app.exception
    assert any("Scoring failed" in item.value for item in app.error)
    assert app.button(key="tutorial_next").disabled
    monkeypatch.setattr(views, "predict", lambda model, data: [0.5])
    app.selectbox(key="score_priority").select("Low").run()
    assert not app.button(key="tutorial_next").disabled
    app.button(key="tutorial_continue_focus").click().run()
    while app.session_state["tutorial"]["order"][app.session_state["tutorial"]["index"]] != "governance":
        app.button(key="tutorial_skip").click().run()
    app.radio(key="tutorial_answer_governance").set_value(
        "Personas are simulated and imports are shared locally").run()
    app.button(key="tutorial_continue_focus").click().run()
    assert app.session_state["tutorial"]["completed"] == ["orientation", "quality", "risk", "governance"]
    assert not app.exception
