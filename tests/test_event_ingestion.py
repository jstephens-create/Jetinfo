"""Small event histories test behavior before the optional real-file regression.

These examples deliberately disagree across events. A keep-first deduplication,
per-column nonmissing fallback, or event-weighted outcome would fail the tests.
"""
import csv
import hashlib
import json
import os
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src import database, event_ingestion
from src.event_ingestion import (
    UCI_PROFILE, MappingProfile, event_count, import_event_log, list_imports,
    list_import_attempts, read_events, read_import, read_initial_snapshots,
    read_rejections, read_snapshots,
)


def event(**changes):
    row = dict(number="INC1", sys_updated_at="04/03/2024 11:00", sys_mod_count="0",
               opened_at="04/03/2024 10:00", resolved_at="?", closed_at="?",
               incident_state="New", priority="3 - Moderate", category="Category 55",
               assignment_group="Group 1", assigned_to="?", made_sla="true", active="true",
               reassignment_count="0", reopen_count="0")
    row.update(changes)
    return row


def load(tmp_path, *rows, profile=UCI_PROFILE, **kwargs):
    path = tmp_path / "source.csv"
    pd.DataFrame(rows, columns=list(event())).to_csv(path, index=False)
    result = import_event_log(path, db_path=tmp_path / "imports.db",
                              storage_root=tmp_path / "preserved", profile=profile, **kwargs)
    return result, tmp_path / "imports.db", path


def test_history_is_preserved_and_latest_is_a_whole_row(tmp_path):
    result, db, source = load(tmp_path,
        event(assignment_group="Early team"),
        event(sys_updated_at="04/03/2024 12:00", sys_mod_count="1", incident_state="Closed",
              made_sla="false", assignment_group="?", active="false", resolved_at="04/03/2024 11:30"),
        event(number="INC2"))
    assert (result.rows_read, result.events_loaded, result.incidents_loaded) == (3, 3, 2)
    history = read_events(result.import_id, db, include_raw=True, incident_id="INC1")
    assert len(history) == 2
    latest = read_snapshots(result.import_id, db).set_index("incident_id").loc["INC1"]
    assert latest.source_row == 2 and latest.status == "Closed"
    assert not bool(latest.source_sla_met)
    assert pd.isna(latest.assignment_group)  # no old-value backfill
    earliest = read_initial_snapshots(result.import_id, db).set_index("incident_id").loc["INC1"]
    assert earliest.status == "New" and earliest.assignment_group == "Early team"
    assert Path(result.original_copy_path).read_bytes() == source.read_bytes()
    assert json.loads(history.iloc[1].raw_record_json)["assignment_group"] == "?"
    assert result.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert event_count(result.import_id, db) == 3


def test_preserved_source_uses_short_atomic_temporary_name(tmp_path, monkeypatch):
    source = tmp_path / "input.csv"
    source.write_bytes(b"example")
    original_copy = event_ingestion.shutil.copyfile
    temporary_names = []
    def capture_copy(src, dst):
        temporary_names.append(dst.name)
        return original_copy(src, dst)
    monkeypatch.setattr(event_ingestion.shutil, "copyfile", capture_copy)
    destination, digest = event_ingestion._preserve_source(source, tmp_path / "storage")
    assert destination.read_bytes() == b"example"
    assert digest == hashlib.sha256(b"example").hexdigest()
    assert len(temporary_names[0]) < len(destination.name)


def test_counter_then_source_row_break_equal_time_ties(tmp_path):
    result, db, _ = load(tmp_path,
        event(sys_mod_count="9", assignment_group="Counter 9"),
        event(sys_mod_count="2", assignment_group="Counter 2"),
        event(sys_mod_count="9", assignment_group="Last counter 9"),
        event(sys_mod_count="?", assignment_group="Unknown counter"))
    latest = read_snapshots(result.import_id, db).iloc[0]
    assert latest.source_row == 3 and latest.assignment_group == "Last counter 9"
    assert result.quality_summary["history_rows_beyond_one_per_incident"] == 3


def test_exact_visible_duplicates_are_preserved_as_events(tmp_path):
    result, db, _ = load(tmp_path, event(), event())
    assert event_count(result.import_id, db) == 2
    assert result.quality_summary["exact_duplicate_visible_rows"] == 1
    assert read_snapshots(result.import_id, db).iloc[0].source_row == 2


def test_question_marks_are_unknown_without_fabricated_inputs(tmp_path):
    result, db, _ = load(tmp_path, event(made_sla=" ? ", assignment_group="", assigned_to="?"))
    row = read_snapshots(result.import_id, db).iloc[0]
    assert pd.isna(row.source_sla_met) and pd.isna(row.assignment_group)
    assert row.priority == "Medium" and row.category == "Category 55"
    assert row.opened_at == "2024-03-04T10:00:00"  # explicit day-first parsing
    assert row.timestamp_timezone == "unknown" and not row.opened_at.endswith("Z")
    assert result.quality_summary["missing_source_cells"]["made_sla"] == 1
    assert "response_time_minutes" not in row.index
    assert "sla_target_minutes" not in row.index


def test_invalid_core_rows_rejected_optional_errors_retained_and_exported(tmp_path):
    result, db, _ = load(tmp_path,
        event(number="?"), event(number="BAD_TIME", sys_updated_at="99/03/2024 10:00"),
        event(number="OPTIONAL", resolved_at="not a date", made_sla="perhaps", reassignment_count="-1"))
    assert (result.events_loaded, result.rows_rejected) == (1, 2)
    rejected = read_rejections(result.import_id, db)
    assert rejected.source_row.tolist() == [1, 2]
    assert "missing incident_id" in rejected.iloc[0].reason
    assert "invalid event_at" in rejected.iloc[1].reason
    row = read_snapshots(result.import_id, db).iloc[0]
    assert pd.isna(row.resolved_at) and pd.isna(row.source_sla_met) and pd.isna(row.reassignment_count)
    assert set(row.validation_warnings) == {"invalid resolved_at", "invalid source_sla_met", "invalid reassignment_count"}
    warnings = pd.read_csv(result.warnings_csv_path)
    assert warnings.source_row.tolist() == [3]
    assert len(pd.read_csv(result.rejection_csv_path)) == 2
    assert result.quality_summary["invalid_field_counts"]["invalid resolved_at"] == 1


def test_outcome_after_event_is_explicit_not_a_prediction_input(tmp_path):
    result, db, _ = load(tmp_path, event(resolved_at="05/03/2024 10:00", closed_at="06/03/2024 10:00"))
    row = read_events(result.import_id, db).iloc[0]
    assert row.resolved_after_event and row.closed_after_event
    assert result.quality_summary["resolved_after_event"] == 1
    assert any("point-in-time" in warning for warning in result.warnings)


def test_negative_interval_keeps_source_evidence_and_validation_warning(tmp_path):
    result, db, _ = load(tmp_path, event(resolved_at="04/03/2024 09:00"))
    row = read_snapshots(result.import_id, db).iloc[0]
    assert row.resolved_at == "2024-03-04T09:00:00"
    assert "resolved_at before opened_at" in row.validation_warnings
    assert result.quality_summary["invalid_field_counts"]["resolved_at before opened_at"] == 1


def test_explicit_time_zone_normalizes_to_utc(tmp_path):
    profile = replace(UCI_PROFILE, source_timezone="America/New_York")
    result, db, _ = load(tmp_path, event(), profile=profile)
    row = read_snapshots(result.import_id, db).iloc[0]
    assert row.opened_at == "2024-03-04T15:00:00Z"
    assert row.event_at == "2024-03-04T16:00:00Z"
    assert row.timestamp_timezone == "UTC"
    assert result.source_timezone == "America/New_York"


@pytest.mark.parametrize("timestamp", ["10/03/2024 02:30", "03/11/2024 01:30"])
def test_ambiguous_or_nonexistent_dst_event_is_rejected(tmp_path, timestamp):
    result, db, _ = load(tmp_path, event(sys_updated_at=timestamp),
                          profile=replace(UCI_PROFILE, source_timezone="America/New_York"))
    assert result.events_loaded == 0 and result.rows_rejected == 1
    assert read_rejections(result.import_id, db).iloc[0].reason == "invalid event_at"
    assert read_snapshots(result.import_id, db).empty


def test_identical_file_and_profile_are_idempotent_but_changed_profile_is_separate(tmp_path):
    result, db, path = load(tmp_path, event())
    second = import_event_log(path, db, tmp_path / "preserved")
    assert second.import_id == result.import_id and second.idempotent_reuse
    assert event_count(result.import_id, db) == 1 and len(list_imports(db)) == 1
    third = import_event_log(path, db, tmp_path / "preserved",
                             profile=replace(UCI_PROFILE, source_timezone="UTC"))
    assert third.import_id != result.import_id
    assert len(list_imports(db)) == 2
    assert read_import(third.import_id, db)["mapping_profile"]["source_timezone"] == "UTC"
    assert read_import(result.import_id, db)["timings_seconds"] == result.timings_seconds


def test_failed_commit_is_atomic_recorded_and_retryable(tmp_path, monkeypatch):
    path = tmp_path / "source.csv"
    pd.DataFrame([event()], columns=list(event())).to_csv(path, index=False)
    db = tmp_path / "imports.db"
    storage = tmp_path / "preserved"

    def fail_commit(*args, **kwargs):
        raise sqlite3.OperationalError("simulated interrupted commit")

    with monkeypatch.context() as patch:
        patch.setattr(event_ingestion, "_commit_import", fail_commit)
        with pytest.raises(sqlite3.OperationalError, match="simulated interrupted commit"):
            import_event_log(path, db, storage)

    attempts = list_import_attempts(db)
    assert len(attempts) == 1
    assert attempts.iloc[0].status == "failed"
    assert "simulated interrupted commit" in attempts.iloc[0].error_message
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source_incidents").fetchone()[0] == 0

    retried = import_event_log(path, db, storage)
    assert retried.idempotent_reuse is False
    assert retried.events_loaded == 1
    retried_attempts = list_import_attempts(db)
    assert retried_attempts.iloc[0].status == "committed"
    assert retried_attempts.iloc[0].import_id == retried.import_id
    repeated = import_event_log(path, db, storage)
    assert repeated.import_id == retried.import_id and repeated.idempotent_reuse
    assert event_count(retried.import_id, db) == 1


def test_failed_second_import_does_not_change_existing_commit(tmp_path, monkeypatch):
    first = tmp_path / "first.csv"
    pd.DataFrame([event(number="FIRST")], columns=list(event())).to_csv(first, index=False)
    db = tmp_path / "imports.db"
    storage = tmp_path / "preserved"
    committed = import_event_log(first, db, storage)

    second = tmp_path / "second.csv"
    pd.DataFrame([event(number="SECOND")], columns=list(event())).to_csv(second, index=False)

    def fail_commit(*args, **kwargs):
        raise sqlite3.OperationalError("simulated database failure")

    with monkeypatch.context() as patch:
        patch.setattr(event_ingestion, "_commit_import", fail_commit)
        with pytest.raises(sqlite3.OperationalError):
            import_event_log(second, db, storage)

    assert event_count(committed.import_id, db) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM source_events").fetchone()[0] == 1


def test_read_indexes_are_registered_and_snapshot_join_stays_indexed(tmp_path):
    db = tmp_path / "imports.db"
    storage = tmp_path / "preserved"
    path = tmp_path / "source.csv"
    pd.DataFrame([event(number="IDX")], columns=list(event())).to_csv(path, index=False)
    result = import_event_log(path, db, storage)

    with sqlite3.connect(db) as conn:
        indexes = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
        assert "source_event_timeline" in indexes
        assert "source_incident_snapshot_order" in indexes

        timeline = list(conn.execute(
            "EXPLAIN QUERY PLAN SELECT incident_id, source_row, event_at "
            "FROM source_events WHERE import_id=? AND incident_id=? ORDER BY source_row",
            (result.import_id, "IDX"),
        ))
        snapshots = list(conn.execute(
            "EXPLAIN QUERY PLAN SELECT e.incident_id, e.source_row "
            "FROM source_events e "
            "JOIN source_incidents i ON e.import_id=i.import_id AND e.source_row=i.source_row "
            "WHERE e.import_id=? ORDER BY i.incident_id",
            (result.import_id,),
        ))

    timeline_detail = " ".join(str(row) for row in timeline)
    snapshot_detail = " ".join(str(row) for row in snapshots)
    assert "source_event_timeline" in timeline_detail
    assert "source_incident_snapshot_order" in snapshot_detail
    assert "USE TEMP B-TREE FOR ORDER BY" not in snapshot_detail


def test_import_never_replaces_demo_tables(tmp_path):
    db = tmp_path / "imports.db"
    database.init_db(db)
    with database.connect(db) as conn:
        conn.execute("INSERT INTO pipeline_runs(started_at,status) VALUES('existing','success')")
    result, db, _ = load(tmp_path, event())
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source_events").fetchone()[0] == 1


def test_selective_read_and_missing_import_validation(tmp_path):
    result, db, _ = load(tmp_path, event(), event(number="OTHER"))
    selected = read_events(result.import_id, db, columns=["incident_id", "source_row", "event_at"], incident_id="OTHER")
    assert list(selected) == ["incident_id", "source_row", "event_at"] and len(selected) == 1
    default = read_events(result.import_id, db)
    assert "raw_record_json" not in default.columns
    with pytest.raises(ValueError, match="Unknown import"):
        event_count("unknown", db)
    with pytest.raises(ValueError, match="columns"):
        read_events(result.import_id, db, columns=["raw_record_json; DROP TABLE source_events"])


def test_mapping_profile_is_reusable_and_validated(tmp_path):
    profile = MappingProfile("example", "1", "Example", {"incident_id": "ticket", "event_at": "updated"},
                              timestamp_format="%Y-%m-%d %H:%M:%S")
    path = tmp_path / "example.csv"
    pd.DataFrame([{"ticket": "A", "updated": "2024-03-04 12:00:00"}]).to_csv(path, index=False)
    result = import_event_log(path, tmp_path / "imports.db", tmp_path / "preserved", profile=profile)
    assert result.events_loaded == 1 and result.profile_id == "example"
    assert profile.to_dict()["field_mapping"]["incident_id"] == "ticket"
    with pytest.raises(ValueError, match="missing source columns"):
        import_event_log(path, tmp_path / "other.db", tmp_path / "preserved")
    with pytest.raises(ValueError, match="Unsupported target"):
        import_event_log(path, tmp_path / "other.db", tmp_path / "preserved",
                          profile=replace(profile, field_mapping={**profile.field_mapping, "invented": "ticket"}))


def test_preserved_source_integrity_is_checked_on_reuse(tmp_path):
    result, db, path = load(tmp_path, event())
    Path(result.original_copy_path).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        import_event_log(path, db, tmp_path / "preserved")


def test_large_invalid_counter_is_unknown_not_overflow(tmp_path):
    result, db, _ = load(tmp_path, event(sys_mod_count="999999999999999999999999999999999"))
    row = read_snapshots(result.import_id, db).iloc[0]
    assert pd.isna(row.source_sequence)
    assert "invalid source_sequence" in row.validation_warnings


def test_signed_sqlite_integer_boundary_is_exact_with_unknown_values(tmp_path):
    result, db, _ = load(tmp_path,
        event(number="MAX", sys_mod_count=str(2**63 - 1)),
        event(number="OVER", sys_mod_count=str(2**63)),
        event(number="UNKNOWN", sys_mod_count="?"))
    rows = read_snapshots(result.import_id, db).set_index("incident_id")
    assert int(rows.loc["MAX", "source_sequence"]) == 2**63 - 1
    assert pd.isna(rows.loc["OVER", "source_sequence"])
    assert pd.isna(rows.loc["UNKNOWN", "source_sequence"])


def test_invalid_time_zone_has_an_actionable_validation_error(tmp_path):
    with pytest.raises(ValueError, match="source time zone"):
        load(tmp_path, event(), profile=replace(UCI_PROFILE, source_timezone="Invalid/Place"))


def test_empty_valid_header_import_has_explicit_zero_counts(tmp_path):
    result, db, _ = load(tmp_path)
    assert result.rows_read == result.events_loaded == result.incidents_loaded == result.rows_rejected == 0
    assert read_events(result.import_id, db).empty
    assert read_snapshots(result.import_id, db).empty


def test_real_csv_counts_match_independent_standard_library_reference(tmp_path):
    """Opt in: OKAI_UCI_CSV points at the user's real source, never a CI fixture."""
    configured = os.environ.get("OKAI_UCI_CSV")
    if not configured:
        pytest.skip("Set OKAI_UCI_CSV to run the real-file integration test")
    path = Path(configured)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    latest, keys = {}, {}
    rows = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for source_row, row in enumerate(csv.DictReader(handle), 1):
            rows += 1
            key = (datetime.strptime(row["sys_updated_at"], "%d/%m/%Y %H:%M"),
                   int(row["sys_mod_count"]), source_row)
            if row["number"] not in keys or key > keys[row["number"]]:
                latest[row["number"]], keys[row["number"]] = row, key
    result = import_event_log(path, tmp_path / "imports.db", tmp_path / "preserved")
    snapshots = read_snapshots(result.import_id, tmp_path / "imports.db")
    assert result.events_loaded == rows == 141712
    assert result.incidents_loaded == len(latest) == 24918
    assert snapshots.resolved_at.isna().sum() == sum(row["resolved_at"] == "?" for row in latest.values()) == 1556
    assert snapshots.assignment_group.isna().sum() == sum(row["assignment_group"] == "?" for row in latest.values()) == 2157
    assert int(snapshots.source_sla_met.sum()) == sum(row["made_sla"] == "true" for row in latest.values()) == 15803
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before == result.source_sha256
    repeated = import_event_log(path, tmp_path / "imports.db", tmp_path / "preserved")
    assert repeated.import_id == result.import_id and repeated.idempotent_reuse
    assert event_count(result.import_id, tmp_path / "imports.db") == rows
