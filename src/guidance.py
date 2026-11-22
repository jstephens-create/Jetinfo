"""Guided-flow rules for the Calculation Inspector, kept free of Streamlit.

The page decides how to draw widgets; this module decides which next step to
highlight, which options stay visible, and what an unavailable option means.
Plain functions make those rules testable without starting the app.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from src.calculations import AVAILABLE, NEEDS_INPUTS, UNAVAILABLE

GROUP_LABELS = {AVAILABLE: "Available from this source",
                NEEDS_INPUTS: "Needs scenario inputs",
                UNAVAILABLE: "Unavailable"}

ROLE_GOALS = {
    "Analyst": "Find the records behind a number and see what was left out.",
    "Manager": "Decide whether a number is trustworthy enough to act on.",
    "Admin": "Confirm that the source supplies what the metric needs.",
}
# One highlighted next step per role when a result is available.
ROLE_PRIMARY = {"Analyst": "excluded", "Manager": "decision", "Admin": "quality"}

CURRENCIES = {
    "USD": "US dollar", "EUR": "Euro", "GBP": "British pound", "CAD": "Canadian dollar",
    "AUD": "Australian dollar", "NZD": "New Zealand dollar", "CHF": "Swiss franc", "JPY": "Japanese yen",
    "CNY": "Chinese yuan", "INR": "Indian rupee", "SGD": "Singapore dollar", "SEK": "Swedish krona",
    "NOK": "Norwegian krone", "DKK": "Danish krone", "MXN": "Mexican peso", "BRL": "Brazilian real",
    "ZAR": "South African rand",
}
OTHER_CURRENCY = "Other…"


@dataclass(frozen=True)
class InputSpec:
    label: str
    help: str
    kind: str  # "hours", "signed_hours", "money", or "count"


# Every scenario input is typed by the user. The label says so, because OKai
# neither measures nor verifies these values.
INPUT_SPECS = {
    "baseline_hours": InputSpec("Baseline processing hours", "Hours the matched process took before the change.", "hours"),
    "observed_hours": InputSpec("Observed processing hours", "Hours the same process took afterwards.", "hours"),
    "hours_saved": InputSpec("Hours saved", "Negative hours represent capacity lost.", "signed_hours"),
    "hourly_labor_cost": InputSpec("Hourly labor cost", "Fully loaded cost of one labor hour, in the currency chosen below.", "money"),
    "processed_records": InputSpec("Processed records", "Whole records the named stage finished successfully.", "count"),
    "elapsed_seconds": InputSpec("Elapsed seconds", "Measured duration of that stage; must be above zero.", "hours"),
    "operational_cost": InputSpec("Eligible operational cost", "Total cost of the work you want to divide across incidents, in the currency chosen below.", "money"),
    "incident_count": InputSpec("Eligible incident count", "Whole number of incidents the cost covers.", "count"),
}
ASSUMPTION_TAG = "your assumption"
ORIGIN_ENTERED = "Entered by you · assumption"
ORIGIN_SOURCE = "Calculated from this source"


def validate_currency(code) -> str | None:
    """Return an uppercase three-letter code, or None if the text is not one."""
    if not isinstance(code, str):
        return None
    code = code.strip()
    return code.upper() if len(code) == 3 and code.isascii() and code.isalpha() else None


def source_incident_count(engine) -> tuple[int | None, str]:
    """Offer the source's unique incident count, never its event-row count."""
    result = engine.calculate("unique_incident_count")
    if result.status == "available" and result.value:
        return int(result.value), ""
    return None, "This source has no incident snapshots to count."


@dataclass(frozen=True)
class Action:
    action_id: str
    label: str
    note: str
    primary: bool = False
    enabled: bool = True
    kind: str = "button"  # "button" or "hint" (a highlighted instruction, not a control)
    page: str | None = None
    metric_id: str | None = None


def next_step(metric_id: str, source_kind: str) -> Action:
    """The remedy for a metric the selected source cannot currently provide."""
    if metric_id == "total_event_count" and source_kind == "demo":
        return Action("import", "Open Import Desk →", "Import an event log, then choose it as the Analysis source.",
                      page="Import Desk")
    if metric_id == "demo_sla_attainment" and source_kind != "demo":
        return Action("alternate", "Inspect source-reported SLA →",
                      "This source reports its own SLA outcome. Inspect that instead.",
                      metric_id="source_sla_attainment")
    if metric_id == "source_sla_attainment" and source_kind == "demo":
        return Action("alternate", "Inspect demo-policy SLA →",
                      "The synthetic demo has no source SLA flag. Inspect its demo policy instead.",
                      metric_id="demo_sla_attainment")
    return Action("quality", "Review field coverage →",
                  "Check which fields this source provides, or choose another Analysis source.",
                  page="Data quality")


def inspector_actions(role: str | None, group: str, source_kind: str, metric_id: str,
                      result_available: bool) -> list[Action]:
    """Choose the highlighted action; keep the others visible and explain any that are off."""
    if result_available:
        scenario = group == NEEDS_INPUTS
        primary = ROLE_PRIMARY.get(role, "decision")
        actions = [
            Action("excluded", "Review excluded records",
                   "Scenario results have no excluded rows; the inputs table shows what was used."
                   if scenario else "Filters the evidence table to the rows left out of this result.",
                   enabled=not scenario),
            Action("decision", "Review decision evidence →", "Apply this source's evidence to investigation rules.",
                   page="Decision Support"),
            Action("quality", "Check data quality →", "See how complete the source fields are.", page="Data quality"),
            Action("export", "Export evidence ↓", "Downloads every evidence row as CSV."),
        ]
        # Never highlight an option that is switched off.
        enabled = {a.action_id for a in actions if a.enabled}
        primary = primary if primary in enabled else "export"
        return [replace(a, primary=a.action_id == primary) for a in actions]

    if group == NEEDS_INPUTS:
        remedy = Action("inputs", "Enter the required inputs above",
                        "The result, evidence, and export unlock once every input is valid.",
                        primary=True, kind="hint")
    else:
        remedy = replace(next_step(metric_id, source_kind), primary=True)
    waiting = "Available once this metric has a result."
    actions = [remedy,
               Action("excluded", "Review excluded records", waiting, enabled=False),
               Action("decision", "Review decision evidence →", waiting, enabled=False, page="Decision Support"),
               Action("export", "Export evidence ↓", "Nothing to export until there is a result.", enabled=False)]
    if remedy.action_id != "quality":
        actions.insert(1, Action("quality", "Check data quality →", "See which source fields exist.", page="Data quality"))
    return actions


def _number(value) -> str:
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def worked_formula(metric_id: str, result: Mapping) -> str | None:
    """Substitute the result's own values into its formula; no new arithmetic."""
    value, numerator, denominator = result.get("value"), result.get("numerator"), result.get("denominator")
    if result.get("status") != "available" or value is None:
        return None
    unit, parameters = result.get("unit", ""), result.get("parameters") or {}
    if metric_id in {"resolved_incident_rate", "source_sla_attainment", "demo_sla_attainment",
                     "assignment_completeness", "field_completeness"}:
        return f"100 × {_number(numerator)} / {_number(denominator)} = {_number(value)}%"
    if metric_id == "mean_resolution_hours":
        return f"{_number(numerator)} hours / {_number(denominator)} incidents = {_number(value)} hours"
    if metric_id == "time_saved_hours":
        return f"{_number(parameters['baseline_hours'])} − {_number(parameters['observed_hours'])} = {_number(value)} hours"
    if metric_id == "time_reduction_pct":
        return (f"100 × ({_number(parameters['baseline_hours'])} − {_number(parameters['observed_hours'])}) / "
                f"{_number(parameters['baseline_hours'])} = {_number(value)}%")
    if metric_id == "estimated_labor_value":
        return (f"{_number(parameters['hours_saved'])} × {_number(parameters['hourly_labor_cost'])} = "
                f"{_number(value)} {str(parameters['currency']).upper()}")
    if metric_id in {"processing_throughput", "cost_per_incident"}:
        return f"{_number(numerator)} / {_number(denominator)} = {_number(value)} {unit}"
    return None
