"""Small independent examples catch grain, denominator, and availability errors."""
import json

import pandas as pd
import pytest

from src import database
from src.calculation_tools import TOOL_SCHEMA, execute_metric_tool
from src.calculations import (METRIC_REGISTRY, CalculationContext, CalculationEngine,
                              ThresholdConfig, calculate_demo_sla)


@pytest.fixture
def source_frame():
    return pd.DataFrame([
        {"incident_id": "A", "source_row": 2, "status": "Closed", "priority": "Critical",
         "opened_at": "2024-01-01 00:00:00", "resolved_at": "2024-01-01 02:00:00",
         "source_sla_met": True, "assignment_group": "Alpha"},
        {"incident_id": "B", "source_row": 8, "status": "Resolved", "priority": "High",
         "opened_at": "2024-01-01 00:00:00", "resolved_at": "2024-01-01 04:00:00",
         "source_sla_met": False, "assignment_group": "?"},
        # An enriched future resolution does not make this event's state closed.
        {"incident_id": "C", "source_row": 10, "status": "Active", "priority": "Medium",
         "opened_at": "2024-01-01 00:00:00", "resolved_at": "2024-01-02 00:00:00",
         "source_sla_met": True, "assignment_group": None},
        {"incident_id": "D", "source_row": 12, "status": "Closed", "priority": "Low",
         "opened_at": "2024-01-01 00:00:00", "resolved_at": None,
         "source_sla_met": None, "assignment_group": "Beta"},
        {"incident_id": "E", "source_row": 15, "status": None, "priority": "unrecognized",
         "opened_at": "2024-01-01 00:00:00", "resolved_at": "2023-12-31 00:00:00",
         "source_sla_met": None, "assignment_group": "Alpha"},
    ])


def engine_for(frame, events=None, zone="unknown"):
    return CalculationEngine(frame, events, CalculationContext(
        "test-dataset", "Hand-worked source", "event_log", "import-test", zone,
        "2024-01-01", "2024-01-31"))


def test_registry_and_results_contain_auditable_contract(source_frame):
    engine = engine_for(source_frame)
    result = engine.calculate("source_sla_attainment")
    assert result.value == 50.0
    assert result.numerator == 1 and result.denominator == 2
    assert result.eligible_count == 2 and result.excluded_count == 3
    assert result.import_id == "import-test" and result.dataset_id == "test-dataset"
    assert result.observation_window == {"start": "2024-01-01", "end": "2024-01-31", "timezone": "unknown"}
    assert result.formula_version and result.calculated_at
    assert "not independently verified" in " ".join(result.warnings)
    assert json.loads(json.dumps(result.to_dict(), allow_nan=False))["value"] == 50
    definition = METRIC_REGISTRY[result.metric_id]
    for key in ["business_purpose", "required_fields", "unit_of_analysis", "formula", "unit",
                "numerator_definition", "denominator_definition", "filters_and_exclusions",
                "missing_data_behavior", "rounding_digits", "applicable_window", "version", "validation_requirements"]:
        assert key in definition.to_dict()
    with pytest.raises(TypeError):
        METRIC_REGISTRY["invented"] = definition


def test_all_sixteen_metrics_remain_registered_without_full_source_data():
    expected = {
        "unique_incident_count", "total_event_count", "resolved_incident_rate",
        "source_sla_attainment", "demo_sla_attainment", "mean_resolution_hours",
        "median_resolution_hours", "assignment_completeness", "field_completeness",
        "unresolved_incident_count", "high_priority_incident_count",
        "time_saved_hours", "time_reduction_pct", "estimated_labor_value",
        "processing_throughput", "cost_per_incident",
    }
    assert set(METRIC_REGISTRY) == expected
    assert len(METRIC_REGISTRY) == 16


def test_event_history_and_incident_counts_are_separate(source_frame):
    events = pd.DataFrame({"incident_id": ["A", "A", "B", "C", "D", None],
                           "source_row": range(1, 7),
                           "event_at": ["2024-01-01"] * 4 + ["invalid", "2024-01-01"]})
    engine = engine_for(source_frame, events)
    assert engine.calculate("unique_incident_count").value == 5
    event_result = engine.calculate("total_event_count")
    assert event_result.value == 4 and event_result.excluded_count == 2
    evidence = engine.inspect("total_event_count")["records"]
    assert len(evidence) == 6 and evidence.included.sum() == 4
    with pytest.raises(ValueError, match="one snapshot"):
        engine_for(pd.concat([source_frame, source_frame.iloc[[0]]]))
    with pytest.raises(ValueError, match="one snapshot"):
        engine_for(source_frame.assign(incident_id=None))


def test_resolved_rate_uses_status_not_enriched_timestamps(source_frame):
    engine = engine_for(source_frame)
    result = engine.calculate("resolved_incident_rate")
    assert (result.value, result.numerator, result.denominator, result.excluded_count) == (75, 3, 4, 1)
    assert engine.calculate("unresolved_incident_count").value == 1
    assert engine.calculate("high_priority_incident_count").value == 2
    evidence = engine.inspect("resolved_incident_rate")["records"].set_index("incident_id")
    assert evidence.loc["C", "included"] and not evidence.loc["C", "numerator_member"]
    assert not evidence.loc["E", "included"]


def test_duration_exclusions_and_mean_median_share_exact_population(source_frame):
    engine = engine_for(source_frame)
    mean, median = engine.calculate("mean_resolution_hours"), engine.calculate("median_resolution_hours")
    assert mean.value == median.value == 3
    assert mean.numerator == 6 and mean.denominator == median.denominator == 2
    assert mean.eligible_count == 2 and mean.excluded_count == 3
    evidence = engine.inspect("mean_resolution_hours")["records"].set_index("incident_id")
    assert evidence.loc[["A", "B"], "included"].all()
    assert not evidence.loc[["C", "D", "E"], "included"].any()
    assert "timezone is unknown" in " ".join(mean.warnings)
    assert "Gross elapsed" in " ".join(mean.assumptions)


@pytest.mark.parametrize("resolved_at,expected", [
    ("2024-01-01 00:00:00", 0.0),
    ("2023-12-31 23:59:00", None),
    ("not-a-date", None),
    (None, None),
])
def test_duration_zero_missing_invalid_and_negative_are_distinct(resolved_at, expected):
    frame = pd.DataFrame([{"incident_id": "A", "status": "Closed", "opened_at": "2024-01-01 00:00:00",
                           "resolved_at": resolved_at}])
    result = engine_for(frame).calculate("mean_resolution_hours")
    assert result.value == expected
    assert result.status == ("available" if expected is not None else "unavailable")


def test_percentile_method_and_large_intervals_are_documented():
    frame = pd.DataFrame([{"incident_id": str(index), "status": "Closed", "opened_at": "2020-01-01",
                           "resolved_at": date} for index, date in enumerate([
                               "2020-01-01", "2020-01-01 02:00:00", "2020-01-01 10:00:00", "2050-01-01"])])
    result = engine_for(frame).calculate("median_resolution_hours")
    assert result.value == 6  # midpoint of the two middle values: (2 + 10) / 2
    assert "linear" in METRIC_REGISTRY[result.metric_id].formula
    assert engine_for(frame).calculate("mean_resolution_hours").value > 60000


def test_timezones_convert_offsets_and_reject_ambiguous_local_time():
    offset_frame = pd.DataFrame([{"incident_id": "DST", "status": "Closed",
                                 "opened_at": "2024-03-10T01:00:00-05:00",
                                 "resolved_at": "2024-03-10T03:00:00-04:00"}])
    assert engine_for(offset_frame, zone="UTC").calculate("mean_resolution_hours").value == 1
    local_frame = offset_frame.assign(opened_at="2024-03-10 01:00:00", resolved_at="2024-03-10 03:00:00")
    assert engine_for(local_frame, zone="America/New_York").calculate("mean_resolution_hours").value == 1
    ambiguous = local_frame.assign(opened_at="2024-11-03 01:30:00", resolved_at="2024-11-03 03:00:00")
    assert engine_for(ambiguous, zone="America/New_York").calculate("mean_resolution_hours").status == "unavailable"
    mixed = offset_frame.assign(opened_at="2024-03-10 01:00:00")
    evidence = engine_for(mixed).inspect("mean_resolution_hours")
    assert evidence["result"]["status"] == "unavailable"
    assert "Incompatible" in evidence["records"].iloc[0].reason
    with pytest.raises(ValueError, match="timezone"):
        engine_for(local_frame, zone="not/a/zone")


def test_completeness_keeps_unknown_in_denominator_and_groups(source_frame):
    engine = engine_for(source_frame)
    result = engine.calculate("assignment_completeness")
    assert (result.value, result.numerator, result.denominator) == (60, 3, 5)
    assert result.eligible_count == 5 and result.excluded_count == 0
    evidence = engine.inspect("assignment_completeness")["records"]
    assert evidence.included.all() and evidence.numerator_member.sum() == 3
    status = engine.calculate("field_completeness", {"field": "status"})
    assert status.value == 80
    groups = engine.by_dimension("assignment_group").set_index("dimension")
    assert groups.loc["Unknown", "incidents"] == 2
    assert groups.loc["Unknown", "eligible_outcomes"] == 1
    assert groups.loc["Unknown", "excluded_outcomes"] == 1
    assert groups.loc["Unknown", "valid_duration_count"] == 1
    assert engine.calculate("field_completeness", {"field": "affected_service"}).status == "unavailable"
    with pytest.raises(ValueError, match="supported completeness"):
        engine.calculate("field_completeness", {"field": "raw_json"})


def test_empty_and_unknown_populations_do_not_become_perfect_rates():
    empty = engine_for(pd.DataFrame(columns=["incident_id", "status", "opened_at", "resolved_at"]))
    assert empty.calculate("unique_incident_count").value == 0
    assert empty.calculate("total_event_count").value is None
    for metric in ["resolved_incident_rate", "source_sla_attainment", "mean_resolution_hours", "assignment_completeness"]:
        result = empty.calculate(metric)
        assert result.value is None and result.status == "unavailable"
    unknown = engine_for(pd.DataFrame([{"incident_id": "A", "status": "Closed", "source_sla_met": "?"}]))
    assert unknown.calculate("source_sla_attainment").denominator == 0
    assert unknown.calculate("source_sla_attainment").value is None


def test_demo_policy_is_explicit_and_shared_with_etl(make_raw):
    from src.etl import calculate_sla, clean_incidents
    demo = clean_incidents(make_raw({"incident_id": "A", "resolution_time_minutes": "100"},
                                    {"incident_id": "B", "resolution_time_minutes": "900"},
                                    {"incident_id": "C", "status": "Open", "resolution_time_minutes": None}))[0]
    engine = CalculationEngine(demo)
    assert engine.calculate("demo_sla_attainment").value == 50
    assert engine.calculate("mean_resolution_hours").value == 8.3
    assert engine.calculate("source_sla_attainment").value is None
    assert engine_for(demo).calculate("demo_sla_attainment").value is None
    resolution = pd.Series([10.0, 20, None, float("inf"), -1])
    targets = pd.Series([10, 10, 10, 10, 10])
    breached, margin = calculate_sla(resolution, targets)
    shared_breached, shared_margin = calculate_demo_sla(resolution, targets)
    pd.testing.assert_series_equal(breached, shared_breached)
    pd.testing.assert_series_equal(margin, shared_margin)
    assert breached.tolist()[:2] == [0, 1] and breached.iloc[2:].isna().all()


@pytest.mark.parametrize("metric,parameters,expected", [
    ("time_saved_hours", {"baseline_hours": 10, "observed_hours": 6}, 4),
    ("time_saved_hours", {"baseline_hours": 10, "observed_hours": 12}, -2),
    ("time_reduction_pct", {"baseline_hours": 10, "observed_hours": 6}, 40),
    ("time_reduction_pct", {"baseline_hours": 10, "observed_hours": 12}, -20),
    ("estimated_labor_value", {"hours_saved": 4, "hourly_labor_cost": 25, "currency": "USD"}, 100),
    ("estimated_labor_value", {"hours_saved": -4, "hourly_labor_cost": 25, "currency": "USD"}, -100),
    ("processing_throughput", {"processed_records": 250, "elapsed_seconds": 2}, 125),
    ("processing_throughput", {"processed_records": 0, "elapsed_seconds": 2}, 0),
    ("cost_per_incident", {"operational_cost": 1000, "incident_count": 4, "currency": "USD"}, 250),
])
def test_scenario_arithmetic_requires_explicit_observations(source_frame, metric, parameters, expected):
    result = engine_for(source_frame).calculate(metric, parameters)
    assert result.value == expected and result.status == "available"
    assert "supplied by the caller" in " ".join(result.assumptions)
    if metric == "estimated_labor_value":
        assert "not evidence of realized cash savings" in " ".join(result.assumptions)


@pytest.mark.parametrize("metric,parameters", [
    ("time_saved_hours", {}),
    ("time_saved_hours", {"baseline_hours": float("inf"), "observed_hours": 1}),
    ("time_saved_hours", {"baseline_hours": True, "observed_hours": 1}),
    ("time_saved_hours", {"baseline_hours": -1, "observed_hours": 1}),
    ("time_reduction_pct", {"baseline_hours": 0, "observed_hours": 1}),
    ("estimated_labor_value", {"hours_saved": 4, "hourly_labor_cost": 25}),
    ("estimated_labor_value", {"hours_saved": 4, "hourly_labor_cost": -25, "currency": "USD"}),
    ("processing_throughput", {"processed_records": 250, "elapsed_seconds": 0}),
    ("processing_throughput", {"processed_records": 2.5, "elapsed_seconds": 1}),
    ("cost_per_incident", {"operational_cost": 1000, "incident_count": 0, "currency": "USD"}),
    ("cost_per_incident", {"operational_cost": 1000, "incident_count": 4, "currency": ""}),
])
def test_invalid_missing_and_zero_scenario_inputs_are_unavailable(source_frame, metric, parameters):
    result = engine_for(source_frame).calculate(metric, parameters)
    assert result.status == "unavailable" and result.value is None and result.unavailable_reason
    json.dumps(result.to_dict(), allow_nan=False)


@pytest.mark.parametrize("metric,parameters", [
    ("estimated_labor_value", {"hours_saved": 1e308, "hourly_labor_cost": 1e308, "currency": "USD"}),
    ("time_reduction_pct", {"baseline_hours": 1e-308, "observed_hours": 1e308}),
    ("cost_per_incident", {"operational_cost": 1e308, "incident_count": 10 ** 1000, "currency": "USD"}),
])
def test_large_finite_scenario_operands_never_emit_infinity(source_frame, metric, parameters):
    result = engine_for(source_frame).calculate(metric, parameters)
    assert result.value is None and result.status == "unavailable"
    assert result.unavailable_reason
    json.dumps(result.to_dict(), allow_nan=False)


def test_large_duration_sum_is_explicitly_unavailable_and_json_safe():
    frame = pd.DataFrame({"incident_id": [str(i) for i in range(1000)], "status": "Closed",
                          "resolution_time_minutes": 1e308})
    result = CalculationEngine(frame).calculate("mean_resolution_hours")
    assert result.value is None and result.numerator is None
    assert result.status == "unavailable" and result.unavailable_reason
    json.dumps(result.to_dict(), allow_nan=False)


def test_result_midpoint_rounding_preserves_legacy_sql_and_large_finite_values(source_frame):
    engine = engine_for(source_frame)
    assert engine.calculate("time_saved_hours", {"baseline_hours": 1.25, "observed_hours": 0}).value == 1.3
    assert engine.calculate("time_saved_hours", {"baseline_hours": 0, "observed_hours": 1.25}).value == -1.3
    result = engine.calculate("estimated_labor_value", {"hours_saved": 2.675, "hourly_labor_cost": 1, "currency": "USD"})
    assert result.value == 2.68
    huge = engine.calculate("cost_per_incident", {"operational_cost": 1e308, "incident_count": 1, "currency": "USD"})
    assert huge.value == 1e308 and huge.status == "available"
    json.dumps(huge.to_dict(), allow_nan=False)


def test_thresholds_are_configurable_and_temporal_rules_require_explicit_as_of(source_frame):
    frame = source_frame.copy()
    frame.loc[frame.incident_id.eq("C"), "priority"] = "Critical"
    context = CalculationContext("test", "Test snapshot", "event_log", observation_end="2024-01-01 00:00:00")
    engine = CalculationEngine(frame, context=context)
    config = ThresholdConfig(age_hours=12, backlog_threshold=0)
    without_time = engine.alerts(config)
    assert set(without_time.rule_id) == {"unresolved_backlog", "high_priority_unassigned"}
    with_time = engine.alerts(config, as_of="2024-01-02 00:00:00")
    assert set(with_time.rule_id) == {"unresolved_backlog", "high_priority_unassigned", "incident_age"}
    assert not with_time.rule_id.eq("provided_sla_deadline").any()
    assert with_time.rule_basis.str.contains("not verified").all()
    frame.loc[frame.incident_id.eq("C"), "sla_deadline_at"] = "2024-01-02 00:30:00"
    provided = CalculationEngine(frame, context=context).alerts(config, as_of="2024-01-02 00:00:00")
    assert provided.loc[provided.rule_id.eq("provided_sla_deadline"), "observed_value"].item() == 30
    with pytest.raises(ValueError, match="valid timestamp"):
        engine.alerts(config, as_of="not-a-date")
    with pytest.raises(ValueError, match="finite nonnegative"):
        ThresholdConfig(age_hours=float("nan"))


def test_temporal_alerts_do_not_replay_final_snapshots_into_the_past(source_frame):
    engine = engine_for(source_frame)
    with pytest.raises(ValueError, match="point-in-time replay"):
        engine.alerts(as_of="2024-01-02 00:00:00")
    frame = source_frame.assign(event_at="2024-02-01 00:00:00")
    no_window = CalculationContext("test", "Latest snapshot", "event_log")
    with pytest.raises(ValueError, match="point-in-time replay"):
        CalculationEngine(frame, context=no_window).alerts(as_of="2024-01-31 00:00:00")
    with pytest.raises(ValueError, match="observation_end"):
        CalculationEngine(source_frame, context=no_window).alerts(as_of="2024-02-01 00:00:00")
    demo_frame = pd.DataFrame([{"incident_id": "FUTURE", "created_at": "2024-03-01", "status": "Open"}])
    with pytest.raises(ValueError, match="point-in-time replay"):
        CalculationEngine(demo_frame).alerts(as_of="2024-02-01")


def test_read_only_tools_validate_requests_paginate_membership_and_use_backend_results(source_frame):
    engine = engine_for(source_frame)
    before = source_frame.copy(deep=True)
    response = execute_metric_tool(engine, {"action": "inspect", "metric_id": "source_sla_attainment", "offset": 1, "limit": 2})
    assert response["ok"] and response["result"]["value"] == 50
    assert response["total_records"] == 5 and len(response["records"]) == 2
    assert response["records"][0]["incident_id"] == "B"
    assert "50.0 %" in response["explanation"]
    assert len(execute_metric_tool(engine, {"action": "list_metrics"})["metrics"]) == len(METRIC_REGISTRY)
    assert TOOL_SCHEMA["permissions"] == ["read:authorized_calculations"]
    json.dumps(response, allow_nan=False)
    pd.testing.assert_frame_equal(source_frame, before)
    engine.incidents.loc[0, "status"] = "Open"
    pd.testing.assert_frame_equal(source_frame, before)


@pytest.mark.parametrize("tool_request", [
    None,
    {"action": "execute_sql", "sql": "DELETE FROM incidents"},
    {"action": "list_metrics", "db_path": "private.db"},
    {"action": "calculate", "metric_id": "invented"},
    {"action": "calculate", "metric_id": "unique_incident_count", "parameters": {"where": "1=1"}},
    {"action": "calculate", "metric_id": "field_completeness", "parameters": {"field": "raw_json"}},
    {"action": "calculate", "metric_id": "time_saved_hours", "parameters": {"baseline_hours": float("nan")}},
    {"action": "calculate", "metric_id": "time_saved_hours", "parameters": {"baseline_hours": [1, 2]}},
    {"action": "inspect", "metric_id": "unique_incident_count", "limit": 1001},
    {"action": "inspect", "metric_id": "unique_incident_count", "offset": -1},
    {"action": "inspect", "metric_id": "unique_incident_count", "limit": True},
    {"action": "alerts", "thresholds": {"invented": 1}},
    {"action": "alerts", "as_of": 2024},
])
def test_tool_interface_rejects_unsupported_or_unsafe_inputs(source_frame, tool_request):
    result = execute_metric_tool(engine_for(source_frame), tool_request)
    assert result["ok"] is False and result["error"]["code"] == "invalid_request"


def test_historical_compatibility_wrappers_use_shared_engine(make_raw, db_path):
    from src.etl import clean_incidents
    database.init_db(db_path)
    clean = clean_incidents(make_raw({"incident_id": "A", "resolution_time_minutes": "100"},
                                    {"incident_id": "B", "resolution_time_minutes": "900"},
                                    {"incident_id": "C", "status": "Open", "resolution_time_minutes": None}))[0]
    with database.connect(db_path) as conn:
        database.upsert_incidents(conn, clean)
    engine = database.calculation_engine(db_path)
    kpis = database.kpi_summary(db_path)
    assert kpis["sla_compliance_pct"] == engine.calculate("demo_sla_attainment").value == 50
    pd.testing.assert_frame_equal(database.sla_by_dimension("priority", db_path), engine.by_dimension("priority"))
    pd.testing.assert_frame_equal(database.monthly_trend(db_path), engine.monthly_trend())
    with pytest.raises(ValueError, match="Unsupported"):
        database.sla_by_dimension("priority; DROP TABLE incidents", db_path)


def _non_scenario(engine):
    return {metric_id: row for metric_id, row in engine.metric_availability().items() if row.group != "needs_inputs"}


def _calculated(engine, metric_id):
    return engine.calculate(metric_id, {"field": "status"} if metric_id == "field_completeness" else None)


def test_availability_groups_match_real_calculations_for_an_event_log(source_frame):
    events = pd.DataFrame({"incident_id": ["A", "B"], "source_row": [1, 2], "event_at": ["2024-01-01"] * 2})
    for engine, absent in [(engine_for(source_frame, events), {"demo_sla_attainment"}),
                           (engine_for(source_frame[["incident_id", "status"]]), {
                               "total_event_count", "demo_sla_attainment", "source_sla_attainment",
                               "mean_resolution_hours", "median_resolution_hours", "assignment_completeness",
                               "high_priority_incident_count"})]:
        rows = _non_scenario(engine)
        for metric_id, row in rows.items():
            assert (row.group == "unavailable") == (metric_id in absent), metric_id
            assert (_calculated(engine, metric_id).status == "unavailable") == (row.group == "unavailable"), metric_id
            assert row.reason if row.group == "unavailable" else row.reason is None


def test_availability_groups_match_real_calculations_for_the_demo(make_raw, db_path):
    from src.etl import clean_incidents
    database.init_db(db_path)
    with database.connect(db_path) as conn:
        database.upsert_incidents(conn, clean_incidents(make_raw({"incident_id": "A"}))[0])
    engine = database.calculation_engine(db_path)
    rows = _non_scenario(engine)
    assert {m for m, row in rows.items() if row.group == "unavailable"} == {"total_event_count", "source_sla_attainment"}
    for metric_id, row in rows.items():
        assert (_calculated(engine, metric_id).status == "unavailable") == (row.group == "unavailable"), metric_id


def test_scenario_metrics_need_inputs_and_list_them(source_frame):
    rows = engine_for(source_frame).metric_availability()
    assert rows["cost_per_incident"].group == "needs_inputs"
    assert rows["cost_per_incident"].required_inputs == ("operational_cost", "incident_count", "currency")
    assert {m for m, row in rows.items() if row.group == "needs_inputs"} == {
        "time_saved_hours", "time_reduction_pct", "estimated_labor_value",
        "processing_throughput", "cost_per_incident"}
