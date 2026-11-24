"""Controlled baseline and isolated negative fixtures for the demo source contract."""
from pathlib import Path

import pytest

from src.calculations import CalculationContext, CalculationEngine
from src.config import RAW_CSV
from src.etl import clean_incidents, load_raw, profile

FIXTURES = Path(__file__).parent / "fixtures" / "negative"


def test_supplied_incident_csv_has_a_pinned_quality_and_metric_contract():
    raw = load_raw(RAW_CSV)
    quality = profile(raw)
    incidents, rejected, duplicate_rows = clean_incidents(raw)

    assert quality["rows"] == 510
    assert quality["exact_duplicate_rows"] == 10
    assert quality["duplicate_incident_ids"] == 10
    assert duplicate_rows == 10
    assert len(incidents) == 478
    assert len(rejected) == 32
    assert int(incidents.sla_breached.eq(0).sum()) == 361
    assert int(incidents.sla_breached.eq(1).sum()) == 92
    assert int(incidents.sla_breached.isna().sum()) == 25
    assert round(100 * int(incidents.sla_breached.eq(1).sum()) / 453, 1) == 20.3

    context = CalculationContext(
        dataset_id="supplied-synthetic-baseline",
        source_name=RAW_CSV.name,
        source_kind="demo",
        timezone="unknown",
        observation_start=incidents.created_at.min(),
        observation_end=incidents.created_at.max(),
    )
    inspection = CalculationEngine(incidents, context=context).inspect("demo_sla_attainment")
    result = inspection["result"]
    evidence = inspection["records"]

    assert result["value"] == 79.7
    assert (result["numerator"], result["denominator"]) == (361, 453)
    assert (result["eligible_count"], result["excluded_count"]) == (453, 25)
    assert result["dataset_id"] == "supplied-synthetic-baseline"
    assert result["source_kind"] == "demo"
    assert result["observation_window"] == {
        "start": incidents.created_at.min(),
        "end": incidents.created_at.max(),
        "timezone": "unknown",
    }
    assert result["formula_version"] == inspection["definition"]["version"]
    assert "Simplified synthetic demo policy" in " ".join(result["warnings"])
    assert len(evidence) == 478
    assert int(evidence.included.sum()) == 453
    assert int(evidence.numerator_member.sum()) == 361
    assert int((~evidence.included).sum()) == 25


@pytest.mark.parametrize(
    ("fixture_name", "reason", "expected_clean", "expected_duplicates"),
    [
        ("malformed_timestamp.csv", "invalid timestamp", 0, 0),
        ("missing_identifier.csv", "missing incident_id", 0, 0),
        ("duplicate_records.csv", "duplicate incident_id", 1, 1),
        ("contradictory_values.csv", "resolution_time shorter than response_time", 0, 0),
    ],
)
def test_negative_data_quality_fixtures_are_isolated(
    fixture_name, reason, expected_clean, expected_duplicates
):
    raw = load_raw(FIXTURES / fixture_name)
    clean, rejected, duplicate_rows = clean_incidents(raw)

    assert len(clean) == expected_clean
    assert len(rejected) == 1
    assert duplicate_rows == expected_duplicates
    assert rejected.iloc[0].rejection_reason.find(reason) >= 0
