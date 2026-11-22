"""The guided-flow rules decide what is highlighted, what stays visible, and why an option is off."""
import pandas as pd
import pytest

from src.calculations import CalculationContext, CalculationEngine
from src.guidance import (inspector_actions, next_step, source_incident_count, validate_currency,
                          worked_formula)


def engine(frame, kind="event_log"):
    return CalculationEngine(frame, context=CalculationContext("ds", "Test source", kind))


@pytest.mark.parametrize("text,expected", [("usd", "USD"), (" eur ", "EUR"), ("US", None), ("US1", None),
                                           ("", None), (None, None), ("ÉUR", None)])
def test_currency_codes_are_three_ascii_letters(text, expected):
    assert validate_currency(text) == expected


def test_source_count_is_unique_incidents_not_events():
    frame = pd.DataFrame({"incident_id": ["A", "B", "C"]})
    events = pd.DataFrame({"incident_id": ["A", "A", "A", "B"], "event_at": ["2024-01-01"] * 4})
    with_events = CalculationEngine(frame, events, CalculationContext("ds", "Test", "event_log"))
    assert source_incident_count(with_events) == (3, "")
    count, why = source_incident_count(engine(pd.DataFrame({"incident_id": []})))
    assert count is None and "no incident snapshots" in why


@pytest.mark.parametrize("role,primary", [("Analyst", "excluded"), ("Manager", "decision"), ("Admin", "quality")])
def test_each_role_gets_one_highlighted_action_when_a_result_exists(role, primary):
    actions = inspector_actions(role, "available", "event_log", "source_sla_attainment", True)
    assert [a.action_id for a in actions if a.primary] == [primary]
    assert all(a.enabled for a in actions)


def test_scenario_results_keep_excluded_records_visible_but_explained_off():
    actions = {a.action_id: a for a in inspector_actions("Analyst", "needs_inputs", "demo", "cost_per_incident", True)}
    assert not actions["excluded"].enabled and "no excluded rows" in actions["excluded"].note
    assert not actions["excluded"].primary and actions["export"].primary and actions["export"].enabled


def test_missing_scenario_inputs_highlight_the_inputs_and_explain_disabled_actions():
    actions = inspector_actions("Manager", "needs_inputs", "demo", "cost_per_incident", False)
    assert actions[0].primary and actions[0].kind == "hint"
    disabled = [a for a in actions if not a.enabled]
    assert {a.action_id for a in disabled} == {"excluded", "decision", "export"} and all(a.note for a in disabled)


def test_unavailable_metrics_point_to_the_fix_for_the_selected_source():
    events = next_step("total_event_count", "demo")
    assert (events.page, events.action_id) == ("Import Desk", "import")
    assert next_step("demo_sla_attainment", "event_log").metric_id == "source_sla_attainment"
    assert next_step("source_sla_attainment", "demo").metric_id == "demo_sla_attainment"
    actions = inspector_actions("Admin", "unavailable", "demo", "total_event_count", False)
    assert actions[0].primary and actions[0].page == "Import Desk"
    assert [a.action_id for a in actions].count("quality") == 1


def test_worked_formula_substitutes_the_results_own_values():
    result = {"status": "available", "value": 50.0, "numerator": 12500.0, "denominator": 250, "unit": "USD/incident",
              "parameters": {}}
    assert worked_formula("cost_per_incident", result) == "12,500 / 250 = 50 USD/incident"
    result = {"status": "available", "value": 50.0, "numerator": 1, "denominator": 2, "unit": "%", "parameters": {}}
    assert worked_formula("source_sla_attainment", result) == "100 × 1 / 2 = 50%"
    assert worked_formula("cost_per_incident", {"status": "unavailable", "value": None}) is None
