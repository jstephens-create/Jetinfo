"""Check the distinctions that prevent misleading quality charts."""
import json

import pandas as pd
import pytest

from src.quality import build_report
from src import charts


def sample_run(**changes):
    run = dict(rows_read=10, rows_loaded=7, rows_rejected=3, duplicates_removed=1,
               missing_values=json.dumps({"priority": 1, "resolution_time_minutes": 4,
                                         "sla_breached": 4, "sla_target_minutes": 0}))
    run.update(changes)
    return run


def sample_rejected():
    return pd.DataFrame({"reason": ["duplicate incident_id", "missing priority; invalid timestamp",
                                    "negative response_time"]})


def test_row_outcomes_are_exclusive_while_rule_failures_can_overlap():
    report = build_report(sample_run(), sample_rejected())
    assert report.outcomes.rows.tolist() == [7, 1, 2]
    assert report.outcomes.source_pct.tolist() == [70.0, 10.0, 20.0]
    assert report.outcomes.rows.sum() == report.source_rows
    assert report.invalid_rows == 2
    assert report.rule_failures.rows.sum() == 3  # three rules failed across two invalid rows
    assert report.rule_failures.invalid_pct.tolist() == [50.0, 50.0, 50.0]
    assert not report.rule_failures.rule.str.contains("duplicate", case=False).any()


def test_outcome_blanks_are_not_automatically_reported_as_defects():
    fields = build_report(sample_run(), sample_rejected()).fields.set_index("field")
    assert fields.loc["resolution_time_minutes", "kind"] == "outcome"
    assert fields.loc["sla_breached", "source_pct"] == 40.0
    assert fields.loc["priority", "kind"] == "required"
    assert fields.loc["sla_target_minutes", "kind"] == "derived"
    assert fields.missing_cells.sum() == 9  # cells across fields, not nine unique bad rows


def test_extra_source_columns_are_informational_not_required_inputs():
    run = sample_run(missing_values=json.dumps({"optional_export_note": 5}))
    field = build_report(run, sample_rejected()).fields.iloc[0]
    assert field["kind"] == "informational"
    assert field["source_pct"] == 50.0


def test_one_rule_is_counted_once_per_row_and_clean_runs_have_no_failures():
    rejected = sample_rejected()
    rejected.loc[1, "reason"] = "missing priority; missing priority"
    assert build_report(sample_run(), rejected).rule_failures.rows.sum() == 2
    clean = sample_run(rows_loaded=10, rows_rejected=0, duplicates_removed=0)
    assert build_report(clean, pd.DataFrame(columns=["reason"])).rule_failures.empty


def test_empty_run_is_finite_and_does_not_claim_a_perfect_load():
    run = sample_run(rows_read=0, rows_loaded=0, rows_rejected=0, duplicates_removed=0,
                     missing_values=json.dumps({"priority": 0}))
    report = build_report(run, pd.DataFrame(columns=["reason"]))
    assert report.outcomes.source_pct.eq(0).all()
    assert report.fields.source_pct.eq(0).all()


@pytest.mark.parametrize("changes", [
    {"rows_loaded": 8}, {"duplicates_removed": 4}, {"duplicates_removed": 0},
    {"rows_loaded": -1}, {"missing_values": json.dumps({"priority": 11})},
])
def test_inconsistent_profiles_are_not_silently_visualized(changes):
    with pytest.raises(ValueError):
        build_report(sample_run(**changes), sample_rejected())


def test_chart_hover_uses_the_correct_population_for_each_measure():
    report = build_report(sample_run(), sample_rejected())
    outcomes = charts.row_outcomes(report)
    rules = charts.validation_rules(report)
    missing = charts.missing_fields(report)
    assert all(item[1] == 10 for item in outcomes.data[0].customdata)
    assert all(item[1] == 2 for item in rules.data[0].customdata)
    assert all(item[1] == 10 for item in missing.data[0].customdata)
    assert outcomes.layout.xaxis.range[0] == rules.layout.xaxis.range[0] == 0
    assert outcomes.layout.height == rules.layout.height == missing.layout.height


def test_missing_chart_keeps_possible_outcomes_visually_distinct_from_required_inputs():
    report = build_report(sample_run(), sample_rejected())
    chart = charts.missing_fields(report)
    labels = list(chart.data[0].y)
    colors = list(chart.data[0].marker.color)
    assert colors[labels.index("Priority")] != colors[labels.index("SLA outcome")]
    assert "SLA target" not in labels  # zero counts remain in the field-audit table


def test_small_count_chart_never_introduces_fractional_row_ticks():
    report = build_report(sample_run(), sample_rejected())
    chart = charts.validation_rules(report)
    assert chart.layout.xaxis.dtick >= 1
    assert chart.layout.xaxis.dtick == int(chart.layout.xaxis.dtick)
