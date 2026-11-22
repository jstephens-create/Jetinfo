"""Turn a saved pipeline run into unambiguous chart data.

Three different units appear in a quality report:
* source rows have exactly one outcome (loaded, duplicate, or invalid);
* a rejected row may fail several validation rules;
* missing values count cells in each field, so a row may appear in several bars.

Keeping these calculations separate from Streamlit makes their denominators
explicit and lets tests verify the interpretation without opening a browser.
"""
import json
from collections import Counter
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class QualityReport:
    """Keep prepared tables beside the populations their percentages describe.

    Named attributes make report.source_rows clearer than an unexplained tuple
    position. Treat the contained DataFrames as read-only presentation inputs.
    """
    source_rows: int
    loaded_rows: int
    duplicate_rows: int
    invalid_rows: int
    outcomes: pd.DataFrame
    rule_failures: pd.DataFrame
    fields: pd.DataFrame


FIELD_LABELS = {
    "incident_id": "Incident ID", "created_at": "Created timestamp", "priority": "Priority",
    "category": "Category", "affected_service": "Affected service", "assignment_group": "Assignment group",
    "response_time_minutes": "Response time", "resolution_time_minutes": "Resolution time",
    "sla_target_minutes": "SLA target", "status": "Status", "sla_breached": "SLA outcome",
}

RULE_LABELS = {
    "missing incident_id": "Missing incident ID", "missing created_at": "Missing timestamp",
    "invalid timestamp": "Invalid timestamp", "timestamp in the future": "Future timestamp",
    "missing priority": "Missing priority", "unrecognized priority": "Unknown priority",
    "missing category": "Missing category", "unrecognized category": "Unknown category",
    "missing affected_service": "Missing service", "missing assignment_group": "Missing team",
    "response_time not a number": "Response is not numeric", "negative response_time": "Negative response time",
    "invalid status": "Invalid status", "resolved incident missing resolution_time": "Resolved without a duration",
    "open incident has resolution_time": "Open with a resolution time",
    "resolution_time shorter than response_time": "Resolution precedes response",
}


def _count(value):
    """Reject corrupt counts rather than drawing a plausible but false chart."""
    count = int(value)
    if count < 0 or count != float(value):
        raise ValueError("Quality counts must be nonnegative whole numbers.")
    return count


def _percent(count, denominator):
    # No rows is different from a successful 100% load; empty runs show 0 counts.
    return 100.0 * count / denominator if denominator else 0.0


def build_report(run, rejected: pd.DataFrame) -> QualityReport:
    """Reconcile the selected run, then prepare counts with named denominators.

    The report only uses the saved run and its rejected records. It deliberately
    does not read today's source CSV: a historical run must remain historical.
    """
    source, loaded, rejected_count, duplicates = (
        _count(run[key]) for key in ("rows_read", "rows_loaded", "rows_rejected", "duplicates_removed"))
    if loaded + rejected_count != source or duplicates > rejected_count or len(rejected) != rejected_count:
        raise ValueError("The saved row counts and rejection audit do not reconcile.")

    failures, observed_duplicates = Counter(), 0
    for reason in rejected["reason"].fillna(""):
        # A set counts a rule at most once per row. Multiple different rules on
        # that row still each count once, so totals can exceed the invalid rows.
        rules = {rule.strip() for rule in str(reason).split(";") if rule.strip()}
        if not rules:
            raise ValueError("A rejected row is missing its validation reason.")
        if "duplicate incident_id" in rules:
            observed_duplicates += 1
        else:
            failures.update(rules)
    if observed_duplicates != duplicates:
        raise ValueError("The duplicate count and rejection audit do not agree.")

    invalid = rejected_count - duplicates
    outcomes = pd.DataFrame([
        {"outcome": label, "rows": count, "source_pct": _percent(count, source), "kind": kind}
        for label, count, kind in [("Loaded", loaded, "loaded"), ("Duplicates", duplicates, "duplicate"),
                                   ("Invalid rows", invalid, "invalid")]
    ])
    rules = pd.DataFrame([
        {"rule": RULE_LABELS.get(rule, rule.replace("_", " ")), "rows": count,
         "invalid_pct": _percent(count, invalid)} for rule, count in failures.items()
    ], columns=["rule", "rows", "invalid_pct"])
    rules = rules.sort_values(["rows", "rule"], ascending=[False, True]).reset_index(drop=True)

    missing = run["missing_values"]
    missing = json.loads(missing) if isinstance(missing, str) else missing
    field_rows = []
    for field, value in missing.items():
        count = _count(value)
        if count > source:
            raise ValueError("A field cannot have more missing cells than source rows.")
        # A raw blank in these outcome fields MAY be valid for an open ticket.
        # The profile has no per-status breakdown, so we must not claim every
        # such blank is expected. Only row-level validation determines validity.
        if field in {"resolution_time_minutes", "sla_breached"}:
            kind, policy = "outcome", "May be blank while an incident is open"
        elif field == "sla_target_minutes":
            kind, policy = "derived", "Recomputed from priority during ETL"
        elif field in {"incident_id", "created_at", "priority", "category", "affected_service",
                       "assignment_group", "response_time_minutes", "status"}:
            kind, policy = "required", "Required input; missing values need validation"
        else:
            # Extra export columns are profiled but are not validated or used.
            kind, policy = "informational", "Extra source field; not used by this pipeline"
        field_rows.append({"field": field, "label": FIELD_LABELS.get(field, field.replace("_", " ")),
                           "missing_cells": count, "source_pct": _percent(count, source),
                           "kind": kind, "policy": policy})
    fields = pd.DataFrame(field_rows, columns=["field", "label", "missing_cells", "source_pct", "kind", "policy"])
    return QualityReport(source, loaded, duplicates, invalid, outcomes, rules, fields)
