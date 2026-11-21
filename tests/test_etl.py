"""Data cleaning, standardization, duplicate handling and SLA calculation."""
import pandas as pd

from src.etl import calculate_sla, clean_incidents, standardize_category, standardize_priority


# ---------------------------------------------------------------- standardization
def test_priority_variants_map_to_official_values():
    assert standardize_priority("P1") == "Critical"
    assert standardize_priority(" critical ") == "Critical"
    assert standardize_priority("med") == "Medium"
    assert standardize_priority("LOW") == "Low"
    assert standardize_priority("urgent-ish") is None
    assert standardize_priority(None) is None


def test_category_variants_map_to_official_values():
    assert standardize_category("H/W") == "Hardware"
    assert standardize_category("e-mail") == "Email"
    assert standardize_category("DB") == "Database"
    assert standardize_category("NETWORK ") == "Network"
    assert standardize_category("Plumbing") is None


# ---------------------------------------------------------------- cleaning
def test_valid_row_is_cleaned_and_typed(make_raw):
    clean, rejected, _ = clean_incidents(make_raw({"priority": "p2", "category": "networking",
                                                   "assignment_group": "  Network Operations "}))
    assert rejected.empty
    row = clean.iloc[0]
    assert row["priority"] == "High" and row["category"] == "Network"
    assert row["assignment_group"] == "Network Operations"
    assert row["response_time_minutes"] == 20.0


def test_invalid_rows_are_rejected_with_reasons(make_raw):
    raw = make_raw(
        {"incident_id": "OK"},
        {"incident_id": "BAD_TS", "created_at": "2024-13-45 10:00:00"},
        {"incident_id": "NO_PRIO", "priority": None},
        {"incident_id": "NEG", "response_time_minutes": "-5"},
        {"incident_id": "NAN", "response_time_minutes": "N/A"},
        {"incident_id": "FAST", "resolution_time_minutes": "1"},
        {"incident_id": "OPEN_WITH_RES", "status": "Open"},
    )
    clean, rejected, _ = clean_incidents(raw)
    assert list(clean["incident_id"]) == ["OK"]
    reasons = dict(zip(rejected["incident_id"], rejected["rejection_reason"]))
    assert reasons["BAD_TS"] == "invalid timestamp"
    assert reasons["NO_PRIO"] == "missing priority"
    assert reasons["NEG"] == "negative response_time"
    assert reasons["NAN"] == "response_time not a number"
    assert "shorter than response_time" in reasons["FAST"]
    assert reasons["OPEN_WITH_RES"] == "open incident has resolution_time"


def test_open_incident_without_resolution_is_valid(make_raw):
    clean, rejected, _ = clean_incidents(make_raw({"status": "In Progress",
                                                   "resolution_time_minutes": None}))
    assert rejected.empty
    assert pd.isna(clean.iloc[0]["sla_breached"])  # outcome unknown, not "met"


# ---------------------------------------------------------------- duplicates
def test_duplicate_incident_ids_are_removed_within_a_file(make_raw):
    clean, rejected, n_dupes = clean_incidents(make_raw({"incident_id": "A"}, {"incident_id": "A"},
                                                        {"incident_id": "B"}))
    assert n_dupes == 1
    assert sorted(clean["incident_id"]) == ["A", "B"]
    assert rejected.iloc[0]["rejection_reason"] == "duplicate incident_id"


# ---------------------------------------------------------------- SLA
def test_calculate_sla_breach_and_margin():
    resolution = pd.Series([100.0, 480.0, 481.0, None])
    target = pd.Series([480, 480, 480, 480])
    breached, margin = calculate_sla(resolution, target)
    assert breached.tolist()[:3] == [0, 0, 1]  # exactly on target counts as met
    assert pd.isna(breached.iloc[3])
    assert margin.tolist()[:3] == [380.0, 0.0, -1.0]


def test_sla_target_comes_from_policy_not_raw_file(make_raw):
    clean, _, _ = clean_incidents(make_raw({"priority": "Critical", "sla_target_minutes": "99999",
                                            "resolution_time_minutes": "300"}))
    row = clean.iloc[0]
    assert row["sla_target_minutes"] == 240
    assert row["sla_breached"] == 1
