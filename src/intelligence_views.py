"""Operational analysis pages backed by the shared calculation contracts.

These functions arrange backend results; they do not reimplement formulas. A
button callback changes navigation before the next Streamlit rerun, avoiding a
write to a widget's state after that widget has already been rendered.
"""
from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple
import json
import sqlite3

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import demo, investigations as casework, tutorial, ui
from src.calculations import (AVAILABLE, NEEDS_INPUTS, SCENARIO_PARAMETERS, UNAVAILABLE,
                              CalculationContext, CalculationEngine, ThresholdConfig,
                              COMPLETENESS_FIELDS)
from src.calculation_tools import (TOOL_SCHEMA, build_calculation_evidence_export,
                                   execute_metric_tool)
from src import event_ingestion as imports
from src.config import ROOT
from src.guidance import (ASSUMPTION_TAG, CURRENCIES, GROUP_LABELS, INPUT_SPECS, ORIGIN_ENTERED, ORIGIN_SOURCE,
                          OTHER_CURRENCY, ROLE_GOALS, inspector_actions, next_step, source_incident_count,
                          validate_currency, worked_formula)

GROUP_COLUMN_LABELS = {
    "dimension": "Group", "incidents": "Unique incidents", "breaches": "Outcomes reported or calculated as missed",
    "compliance_pct": st.column_config.NumberColumn("SLA attainment (%)", format="%.1f"),
    "avg_resolution_hours": st.column_config.NumberColumn("Mean gross resolution (hours)", format="%.1f"),
    "eligible_outcomes": "Known eligible outcomes", "excluded_outcomes": "Excluded outcomes",
    "valid_duration_count": "Valid duration records",
}


def navigate(page, metric_id=None, incident_id=None):
    if page == "Calculation Inspector" and metric_id == "demo_sla_attainment":
        tutorial.inspection_requested("overview")
    st.session_state["page"] = page
    if metric_id is not None:
        st.session_state["inspector_metric"] = metric_id
        st.session_state.pop("inspector_search", None)
    if page == "Investigations":
        st.session_state["investigation_seed_source"] = st.session_state.get("analytical_source", "demo")
        if metric_id is not None:
            st.session_state["investigation_seed_metric"] = metric_id
        if incident_id is not None:
            st.session_state["investigation_seed_incident"] = incident_id


def _metric_name(engine, metric_id):
    return ("Processing time saved and reduction" if metric_id == "time_saved_hours"
            else engine.registry[metric_id].name)


def demo_engine(incidents, runs):
    successes = runs[runs.status.eq("success")]
    run = successes.iloc[0] if not successes.empty else None
    run_id = f"demo-run-{int(run.run_id)}" if run is not None else "synthetic-demo"
    # The synthetic source is a snapshot export, not an event log. Passing no
    # events makes event count explicitly unavailable instead of relabelling rows.
    return CalculationEngine(incidents, context=CalculationContext(
        dataset_id=run_id, import_id=run_id, source_kind="demo",
        source_name="Seeded synthetic incident snapshot", timezone="unknown",
        observation_start=str(incidents.created_at.min()) if not incidents.empty else None,
        observation_end=str(incidents.created_at.max()) if not incidents.empty else None))


@st.cache_data(show_spinner=False)
def imported_payload(import_id):
    """Imports are immutable, so their ID is a safe cache key across reruns."""
    metadata = imports.read_import(import_id)
    snapshots = imports.read_snapshots(import_id)
    # Only the three fields used for event counts/window/lineage are needed for
    # the engine. Raw JSON for 141k events would waste memory on every page.
    events = imports.read_events(import_id, columns=["incident_id", "source_row", "event_at"])
    return metadata, snapshots, events


def imported_engine(import_id):
    metadata, snapshots, events = imported_payload(import_id)
    context = CalculationContext(
        dataset_id=import_id, import_id=import_id, source_kind="event_log",
        source_name=metadata.get("source_name", "Imported incident event log"),
        timezone=metadata.get("timestamp_timezone") or "unknown",
        observation_start=str(events.event_at.min()) if not events.empty else None,
        observation_end=str(events.event_at.max()) if not events.empty else None,
        warnings=tuple(metadata.get("warnings", [])))
    return CalculationEngine(snapshots, events=events, context=context), metadata


def source_selector():
    """Keep the selected analytical source separate from the mock review queue."""
    history = imports.list_imports()
    labels = {"demo": "Synthetic demo · Jan–Jun 2024"}
    if not history.empty:
        for row in history.to_dict("records"):
            key = str(row["import_id"])
            labels[key] = f"{row.get('source_name', 'Event log')} · {key[:8]}"
    pending = st.session_state.pop("pending_dataset", None)
    if pending in labels:
        st.session_state["analytical_source"] = pending
    if st.session_state.get("analytical_source") not in labels:
        st.session_state["analytical_source"] = "demo"
    selected = st.selectbox("Analysis source", list(labels),
                            format_func=labels.get, key="analytical_source")
    st.caption("Metrics and investigations follow this source. Legacy demo reviews stay on the synthetic queue.")
    st.button("Import a source", key="source_import", on_click=navigate,
              args=("Import Desk",), width="stretch")
    return selected


def format_value(result):
    if result.status != "available" or result.value is None:
        return "Unavailable"
    value = result.value
    if result.unit in {"percent", "%"}:
        return f"{value:,.1f}%"
    if result.unit in {"hours", "hour", "h"}:
        return f"{value:,.1f}h"
    if isinstance(value, (int, float)):
        currency = result.unit.split("/")[0].split(" ")[0]
        if len(currency) == 3 and currency.isalpha() and currency.isupper():
            return f"{value:,.2f} {currency}"
        return f"{value:,}" if float(value).is_integer() else f"{value:,.2f}"
    return str(value)


def metric_card(engine, metric_id, key, color=ui.INK):
    result = engine.calculate(metric_id)
    definition = engine.registry[metric_id]
    note = f"{result.eligible_count:,} eligible · {result.excluded_count:,} excluded"
    if result.status != "available":
        note = "Required evidence is unavailable · inspect the reason"
    ui.metric(definition.name, format_value(result), note, color)
    st.button(f"Explore {definition.name}", key=f"inspect_{key}_{metric_id}",
              help=f"{definition.business_purpose} See the definition, eligibility and evidence.",
              type="primary" if metric_id == "demo_sla_attainment" and tutorial.is_current("overview") else "secondary",
              on_click=navigate, args=("Calculation Inspector", metric_id), width="stretch")
    return result


def source_scope(engine):
    context = engine.context
    st.caption(f"{context.source_name} · Source ID: {context.dataset_id} · "
               f"Timestamp zone: {context.timezone}")
    st.caption(f"Source observation window: {context.observation_start or 'unavailable'} → "
               f"{context.observation_end or 'unavailable'}. This is distinct from the import date.")
    if context.source_kind == "event_log":
        ui.note("Historical events and final incident snapshots are separate populations. "
                "SLA outcomes are source-reported; elapsed resolution time is not business-calendar SLA time. "
                "The synthetic prediction model is not applied to imported incidents.")


def operational_overview(engine, workspace_id=None):
    ui.section("OPERATIONAL OVERVIEW", "Make every metric meaningful.",
               "Inspect the evidence, understand the exclusions, and choose a defensible next step.")
    source_scope(engine)
    sla_id = "demo_sla_attainment" if engine.context.source_kind == "demo" else "source_sla_attainment"
    columns = st.columns(4)
    for column, metric_id, color in zip(columns,
            ["unique_incident_count", "total_event_count", sla_id, "median_resolution_hours"],
            [ui.INK, ui.CYAN, ui.ORANGE, ui.PURPLE]):
        with column:
            metric_card(engine, metric_id, "overview", color)

    left, right = st.columns(2, gap="large")
    with left:
        with ui.chart_panel("operational_priority", "01 / UNIQUE INCIDENTS", "Outcomes by priority",
                            "Each percentage uses incidents with a known eligible outcome within that priority.",
                            "Compare counts and denominators before drawing conclusions from a percentage."):
            groups = engine.by_dimension("priority")
            if groups.empty or groups.compliance_pct.notna().sum() == 0:
                ui.chart_empty("No known outcomes are available for this comparison.")
            else:
                figure = ui.bar(groups, "compliance_pct", "dimension", "SLA attainment (%)",
                                "%{y}: %{x:.1f}%<extra></extra>")
                figure.update_xaxes(range=[0, 100], title="Known-outcome incidents reported or calculated as met (%)")
                st.plotly_chart(figure, width="stretch")
            st.dataframe(groups, hide_index=True, width="stretch", column_config=GROUP_COLUMN_LABELS)
    with right:
        with ui.chart_panel("operational_trend", "02 / OPENED-MONTH COHORTS", "Compare incident cohorts",
                            "One final record per incident · grouped by opened month, not event update month.",
                            "Unknown outcomes are excluded from each cohort's SLA percentage. Small cohorts can vary substantially."):
            trend = engine.monthly_trend()
            if trend.empty:
                ui.chart_empty("No valid opened timestamps are available.")
            else:
                figure = go.Figure(go.Scatter(x=trend.month, y=trend.compliance_pct, mode="lines+markers",
                    line=dict(color=ui.INK, width=2), marker=dict(color=ui.ORANGE, size=7),
                    connectgaps=False, hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
                figure = ui.style(figure)
                figure.update_xaxes(type="category", title="Incident opened month")
                figure.update_yaxes(range=[0, 100], title="SLA attainment (%)")
                st.plotly_chart(figure, width="stretch")
                st.dataframe(trend, hide_index=True, width="stretch")

    a, b, c = st.columns(3)
    for column, metric_id, color in zip([a, b, c],
            ["resolved_incident_rate", "assignment_completeness", "mean_resolution_hours"],
            [ui.CYAN, ui.PURPLE, ui.INK]):
        with column:
            metric_card(engine, metric_id, "overview_quality", color)
    st.button("Review decision evidence →", on_click=navigate,
              args=("Decision Support",), key="overview_decisions")

    if engine.context.source_kind == "demo" and workspace_id:
        team_tab, activity_tab = st.tabs(["Demo team workload", "Workspace activity"])
        with team_tab:
            st.caption("Saved assignments are a separate demo overlay; they do not rewrite historical metrics.")
            st.dataframe(demo.team_summary(workspace_id), hide_index=True, width="stretch")
            st.button("Open demo incident queue →", on_click=navigate,
                      args=("Incident queue",), key="overview_queue")
        with activity_tab:
            ui.timeline(demo.read_events(workspace_id), owner_labels=demo.OWNER_LABELS)


def import_desk():
    ui.section("IMPORT DESK", "Give the source a clear contract.",
               "Import an incident event history while preserving the original file and every source row.")
    ui.note("Supported profile: UCI Incident Management event log. Columns are mapped explicitly; "
            "unknown values stay unknown. Imports are stored locally and shared between demo personas.")
    source_mode = st.radio("CSV location", ["Upload CSV", "Local file on this machine"], horizontal=True)
    with st.form("event_import_form"):
        upload = None
        local_path = ""
        if source_mode == "Upload CSV":
            upload = st.file_uploader("Incident event log", type=["csv"])
        else:
            local_path = st.text_input("Local CSV path", placeholder="C:/path/to/incident_event_log.csv")
        zone = st.selectbox("Source timestamp timezone", ["unknown", "UTC", "America/Los_Angeles",
                            "America/New_York", "Europe/London"],
                            help="Choose a zone only when the source owner confirms it. Unknown preserves local times without claiming UTC.")
        st.caption("Repeated incident IDs are lifecycle events. Final snapshots are ordered by event time, "
                   "source update counter, then source row. No response time or contractual SLA deadline is invented.")
        submitted = st.form_submit_button("Validate and import →", type="primary")
    with st.expander("Inspect the reusable mapping profile"):
        st.json(replace(imports.UCI_PROFILE, source_timezone=None if zone == "unknown" else zone).to_dict())
    if submitted:
        try:
            if source_mode == "Upload CSV":
                if upload is None:
                    raise ValueError("Choose a CSV file before importing.")
                payload = upload.getvalue()
                staging = ROOT / "data" / "imports" / "staging"
                staging.mkdir(parents=True, exist_ok=True)
                source = staging / (sha256(payload).hexdigest() + ".csv")
                if not source.exists():
                    source.write_bytes(payload)
                source_name = Path(upload.name).name
            else:
                if not local_path.strip():
                    raise ValueError("Enter the local CSV path before importing.")
                source = Path(local_path.strip().strip('"'))
                source_name = source.name
            profile = replace(imports.UCI_PROFILE, source_timezone=None if zone == "unknown" else zone)
            with st.spinner("Preserving, validating, and importing the event history…"):
                result = imports.import_event_log(source, profile=profile, source_name=source_name)
            st.session_state["pending_dataset"] = result.import_id
            st.session_state["import_notice"] = result.to_dict()
            st.rerun()
        except (ValueError, OSError, sqlite3.DatabaseError) as exc:
            st.error(f"Import could not be completed: {exc}")
    if notice := st.session_state.get("import_notice"):
        st.success("Import evidence is saved. Choose it in Analysis source to inspect its metrics.")
        st.json(notice, expanded=False)
        st.button("Open imported overview →", on_click=navigate,
                  args=("Overview",), key="import_overview")
    history = imports.list_imports()
    if not history.empty:
        ui.section("SOURCE HISTORY", "Every import has an identity.",
                   "Identical bytes and mapping settings reuse the same import; the synthetic demo remains a separate source.")
        st.dataframe(history, hide_index=True, width="stretch")


class ScenarioInputs(NamedTuple):
    parameters: dict
    origins: dict
    evidence_metric: str | None = None


def _currency_input(metric_id):
    choice = st.selectbox("Currency · selected by you", [*CURRENCIES, OTHER_CURRENCY], index=None,
                          key=f"currency_{metric_id}", placeholder="Choose a currency",
                          on_change=tutorial.scenario_changed,
                          format_func=lambda code: f"{code} — {CURRENCIES[code]}" if code in CURRENCIES else code)
    if choice != OTHER_CURRENCY:
        return choice
    typed = st.text_input("Three-letter currency code", max_chars=3, key=f"currency_other_{metric_id}",
                          placeholder="For example, THB")
    code = validate_currency(typed)
    if typed and code is None:
        st.error("Use a three-letter currency code made of letters, such as THB.")
    return code


def _incident_count_input(engine, metric_id):
    """Offer the source count only as an explicit claim that the cost covers the same incidents."""
    count, why = source_incident_count(engine)
    manual = "Cost covers a different set of incidents (enter the count)"
    options = [manual]
    if count:
        options.insert(0, f"Cost covers all {count:,} unique incidents in this source")
    else:
        st.caption(f"Source incident count unavailable: {why}")
    # The dataset ID in the key drops a stale confirmation when the source changes.
    choice = st.radio("Eligible incident count", options, key=f"count_basis_{metric_id}_{engine.context.dataset_id}",
                      index=None if count else 0,
                      on_change=tutorial.scenario_changed,
                      help="Choose the source count only if the cost you entered covers every incident counted here. "
                           "Events are not incidents: one incident can have many events.")
    if count and choice == options[0]:
        st.caption(f"Using {count:,} unique incidents from {engine.context.source_name}.")
        return count, ORIGIN_SOURCE + " · you confirmed the cost covers all of them", "unique_incident_count"
    if choice == manual:
        spec = INPUT_SPECS["incident_count"]
        value = st.number_input(f"{spec.label} · {ASSUMPTION_TAG}", min_value=1, step=1, value=None,
                                key=f"scenario_{metric_id}_incident_count", placeholder="Required input", help=spec.help,
                                on_change=tutorial.scenario_changed)
        return value, ORIGIN_ENTERED, None
    return None, "Not chosen yet", None


def _scenario_parameters(engine, metric_id):
    """Collect scenario inputs, labelling each as measured from the source or assumed by the user."""
    names = [name for name in engine.registry[metric_id].required_fields]
    if metric_id not in SCENARIO_PARAMETERS:
        return ScenarioInputs({}, {})
    st.caption("Values typed here are your assumptions. OKai does not measure or verify them; "
               "they stay labelled as assumptions in the result.")
    if metric_id == "cost_per_incident":
        with st.expander("What belongs in eligible operational cost?", expanded=True):
            st.write("Enter one total for the same incidents and period as your incident count. "
                     "This metric does not read an operational cost field from the source; this is your allocation, not a measured source value.")
            st.markdown(
                "**Possible inclusions:** incident-handling labor, tooling or support costs attributable to those incidents, "
                "if your cost policy includes them.\n\n"
                "**Exclude:** costs outside that population or period, unrelated operations, and amounts already counted elsewhere. "
                "Do not mix currencies. These are examples, not an automatic eligibility determination."
            )
            st.caption("Choose and document your own cost categories and allocation method. "
                       "The app cannot verify the amount, its categories, or a manually entered incident count.")
    parameters, origins, evidence_metric = {}, {}, None
    for name in names:
        if name == "currency":
            parameters[name] = _currency_input(metric_id)
            origins[name] = "Selected by you"
        elif metric_id == "cost_per_incident" and name == "incident_count":
            parameters[name], origins[name], evidence_metric = _incident_count_input(engine, metric_id)
        else:
            spec = INPUT_SPECS[name]
            kind = spec.kind
            parameters[name] = st.number_input(
                f"{spec.label} · {ASSUMPTION_TAG}", help=spec.help, key=f"scenario_{metric_id}_{name}",
                value=None, placeholder="Required input",
                on_change=tutorial.scenario_changed,
                min_value=None if kind == "signed_hours" else (0 if kind == "count" else 0.0),
                step=1 if kind == "count" else None, format="%.2f" if kind == "money" else None)
            origins[name] = ORIGIN_ENTERED
    return ScenarioInputs(parameters, origins, evidence_metric)


def _group_table(engine, group, ids, availability):
    rows = []
    for metric_id in ids:
        definition = engine.registry[metric_id]
        if group == AVAILABLE:
            rows.append({"Metric": definition.name, "Source fields used": ", ".join(definition.required_fields),
                         "Counts": definition.unit_of_analysis})
        elif group == NEEDS_INPUTS:
            rows.append({"Metric": _metric_name(engine, metric_id), "Inputs you provide": ", ".join(
                INPUT_SPECS[name].label if name in INPUT_SPECS else name.replace("_", " ").title()
                for name in availability[metric_id].required_inputs)})
        else:
            rows.append({"Metric": definition.name, "Why unavailable": availability[metric_id].reason,
                         "What to do next": next_step(metric_id, engine.context.source_kind).note})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _choose_group(groups):
    ids = groups.get(st.session_state["inspector_group"])
    if ids:
        st.session_state["inspector_metric"] = ids[0]


def _show_excluded():
    if st.session_state.get("inspector_metric") == "demo_sla_attainment":
        tutorial.inspection_requested("inspector")
    st.session_state["inspector_evidence"] = "Excluded"


def _render_action(action, evidence_csv, metric_id):
    kind = "primary" if action.primary or (action.action_id == "excluded"
                                            and tutorial.is_current("inspector")) else "secondary"
    if action.kind == "hint":
        st.info(f"**Next:** {action.label}")
    elif action.action_id == "export":
        st.download_button(action.label, evidence_csv, f"okai_{metric_id}_evidence.csv", "text/csv",
                           key="inspector_export", type=kind, disabled=not action.enabled, width="stretch")
    else:
        callback, args = (_show_excluded, ()) if action.action_id == "excluded" else (
            navigate, (action.page or "Calculation Inspector", action.metric_id))
        st.button(action.label, key=f"inspector_action_{action.action_id}", type=kind,
                  disabled=not action.enabled, on_click=callback, args=args, width="stretch")
    st.caption(action.note)


def calculation_inspector(engine, role=None):
    ui.section("CALCULATION INSPECTOR", "Follow the number to its evidence.",
               "Definitions, results, and contributing records come from the same backend used by the dashboard.")
    source_scope(engine)
    if role in ROLE_GOALS:
        st.caption(f"Your goal as {role}: {ROLE_GOALS[role]}")
    availability = engine.metric_availability()
    groups = {group: [metric_id for metric_id, row in availability.items() if row.group == group]
              for group in GROUP_LABELS}
    # Both measures use the same inputs; present one scenario without removing either backend contract.
    for ids in groups.values():
        if "time_reduction_pct" in ids:
            ids.remove("time_reduction_pct")
    groups = {group: ids for group, ids in groups.items() if ids}
    if st.session_state.get("inspector_metric") == "time_reduction_pct":
        st.session_state["inspector_metric"] = "time_saved_hours"
    if st.session_state.get("inspector_metric") not in availability:
        st.session_state["inspector_metric"] = "unique_incident_count"
    # A source change or a link from another page can move the metric to another group.
    st.session_state["inspector_group"] = availability[st.session_state["inspector_metric"]].group
    group = st.session_state["inspector_group"]
    st.radio("Metric group", list(groups), key="inspector_group", horizontal=True, on_change=_choose_group,
             args=(groups,), format_func=lambda key: f"{GROUP_LABELS[key]} ({len(groups[key])})")
    with st.expander(f"Metrics in “{GROUP_LABELS[group]}”", expanded=group == UNAVAILABLE):
        _group_table(engine, group, groups[group], availability)
    search = st.text_input("Find a metric", key="inspector_search",
                           placeholder="Search by name, question, field, or keyword")
    keywords = {"time_saved_hours": "time reduction percent baseline observed processing",
                "cost_per_incident": "operational cost labor expenses eligible allocation currency"}
    terms = search.casefold().split()
    matching = [key for key in groups[group] if all(term in " ".join([
        _metric_name(engine, key), engine.registry[key].business_purpose,
        " ".join(engine.registry[key].required_fields), keywords.get(key, "")
    ]).casefold() for term in terms)]
    if not matching:
        st.info("No metrics in this group match those keywords. Try another group or search.")
        return
    if st.session_state["inspector_metric"] not in matching:
        st.session_state["inspector_metric"] = matching[0]
    selected = st.selectbox("Metric", matching, key="inspector_metric",
                            format_func=lambda key: _metric_name(engine, key))
    if group == UNAVAILABLE:
        step = next_step(selected, engine.context.source_kind)
        st.warning(f"Unavailable from this source: {availability[selected].reason} {step.note}")
    inputs = _scenario_parameters(engine, selected)
    parameters = inputs.parameters
    if selected == "field_completeness":
        parameters["field"] = st.selectbox("Incident field", [column for column in engine.incidents.columns
                                                               if column in COMPLETENESS_FIELDS], key="inspector_field")
    try:
        inspection = engine.inspect(selected, parameters=parameters)
    except ValueError as exc:
        st.error(str(exc))
        return
    definition, result, records = inspection["definition"], inspection["result"], inspection["records"]
    if tutorial.inspection_loaded(selected, result, records):
        st.rerun()
    if (selected == "cost_per_incident" and result["status"] == "available"
            and parameters.get("currency") == "USD" and parameters.get("operational_cost") == 1000
            and parameters.get("incident_count") == 10 and inputs.origins.get("incident_count") == ORIGIN_ENTERED
            and st.session_state.get("tutorial", {}).get("scenario_touched")
            and tutorial.observe("scenario")):
        st.rerun()
    if (selected == "time_saved_hours" and result["status"] == "available"
            and parameters.get("baseline_hours") == 10 and parameters.get("observed_hours") == 6
            and st.session_state.get("tutorial", {}).get("time_touched")
            and tutorial.observe("time")):
        st.rerun()
    a, b, c = st.columns([2, 1, 1])
    population_label = "scenarios" if selected in SCENARIO_PARAMETERS else "records"
    with a:
        ui.metric(definition.get("name", selected), format_value(engine.calculate(selected, parameters=parameters)),
                  result.get("unit", ""), ui.ORANGE)
    with b:
        ui.metric(f"Eligible {population_label}", f"{result.get('eligible_count', 0):,}", "Backend-defined population", ui.CYAN)
    with c:
        ui.metric(f"Excluded {population_label}", f"{result.get('excluded_count', 0):,}", "Inspect the reasons below", ui.PURPLE)
    st.write(definition.get("business_purpose", definition.get("purpose", "")))
    st.markdown("**What this value means**")
    st.write(f"**Population:** {definition['unit_of_analysis']}  \n"
             f"**Required fields or inputs:** {', '.join(definition['required_fields'])}  \n"
             f"**Numerator:** {definition['numerator_definition']}  \n"
             f"**Denominator:** {definition['denominator_definition']}  \n"
             f"**Eligibility and exclusions:** {definition['filters_and_exclusions']}  \n"
             f"**When data is missing:** {definition['missing_data_behavior']}  \n"
             f"**Window:** {definition['applicable_window']}")
    available = result["status"] == "available"
    if not available and group != UNAVAILABLE:
        if selected in SCENARIO_PARAMETERS and all(value is None for value in parameters.values()):
            st.info("Enter the required inputs above to calculate this estimate.")
        else:
            st.warning(f"No result yet: {result.get('unavailable_reason') or 'required evidence is unavailable.'}")
    if selected == "total_event_count" and result["status"] != "available":
        tutorial.question("limits", "Why can't the demo count historical events?",
                          [tutorial.LIMIT_ANSWER, "Every incident snapshot is one historical event"],
                          tutorial.LIMIT_ANSWER)
    explanation = execute_metric_tool(engine, {"action": "calculate", "metric_id": selected,
                                               "parameters": parameters})
    if explanation["ok"]:
        with st.expander("Explain this validated result"):
            ui.note(explanation["explanation"])
            st.caption("Grounded backend explanation · no external generative AI is connected.")
    st.code(definition.get("formula", "See metric definition"), language="text")
    worked = worked_formula(selected, result)
    if worked:
        st.markdown(f"**With {'your assumptions' if selected in SCENARIO_PARAMETERS else 'this source'}:** `{worked}`")
    if selected == "time_saved_hours":
        reduction = engine.calculate("time_reduction_pct", parameters=parameters)
        st.write(f"**Processing time reduction:** {format_value(reduction)}")
        if reduction.status != "available":
            st.caption(f"Percentage unavailable: {reduction.unavailable_reason}")
        else:
            st.caption("The percentage and hours describe the same matched baseline and observed process; negative values mean an increase in time.")
            st.code(worked_formula("time_reduction_pct", reduction.to_dict()), language="text")
    st.write(f"**Numerator:** {result.get('numerator', 'Not applicable')} · "
             f"**Denominator:** {result.get('denominator', 'Not applicable')}")
    if selected in SCENARIO_PARAMETERS:
        st.dataframe(pd.DataFrame([{"Input": INPUT_SPECS[name].label if name in INPUT_SPECS else name.title(),
                                    "Value": "—" if parameters.get(name) is None else str(parameters[name]),
                                    "Origin": inputs.origins[name]} for name in inputs.origins]),
                     hide_index=True, width="stretch")
    warnings, assumptions = result.get("warnings", []), result.get("assumptions", [])
    if warnings or assumptions:
        with st.expander(f"Data-quality notes and assumptions ({len(warnings) + len(assumptions)})"):
            for warning in warnings:
                st.write("• " + str(warning))
            for assumption in assumptions:
                st.write("Assumption: " + str(assumption))
    if inputs.evidence_metric:
        # The denominator the user confirmed is the source's own incident membership.
        records = engine.inspect(inputs.evidence_metric)["records"]
    actions = inspector_actions(role, group, engine.context.source_kind, selected, available)
    st.markdown("**Next step**")
    evidence_csv = records.to_csv(index=False).encode("utf-8") if available else b""
    for column, action in zip(st.columns(len(actions)), actions):
        with column:
            _render_action(action, evidence_csv, selected)
    evidence_tab, technical_tab = st.tabs(["Contributing and excluded records", "Definition & provenance"])
    with evidence_tab:
        if records.empty:
            st.info("No incident membership table applies to this result. See the calculation inputs and availability status.")
        else:
            if inputs.evidence_metric:
                st.caption(f"These are the {len(records):,} incident snapshots counted as the denominator.")
            disposition = st.radio("Evidence rows", ["All", "Included", "Excluded"], horizontal=True, key="inspector_evidence")
            shown = records
            if disposition != "All":
                shown = records[records.included.eq(disposition == "Included")]
            st.caption(f"Showing up to 250 of {len(shown):,} evidence rows. The export contains all {len(records):,} evidence rows.")
            st.dataframe(shown.head(250), hide_index=True, width="stretch")
    with technical_tab:
        st.json({"definition": definition, "result": result, "parameters": parameters})
        st.caption("The portable trace includes source provenance, the metric definition and result, input origins, and complete evidence.")
        st.download_button(
            "Download complete calculation trace ↓",
            build_calculation_evidence_export(engine, inspection, parameters, inputs.origins, records),
            f"okai_{selected}_calculation_trace.json",
            "application/json",
            key="inspector_trace_export",
        )
    st.button("Investigate a source incident →", key="inspector_start_investigation",
              on_click=navigate, args=("Investigations", selected), width="stretch")


def _selected_incident_rows(frame: pd.DataFrame, incident_id: str) -> pd.DataFrame:
    if "incident_id" not in frame:
        return frame.iloc[0:0]
    return frame[frame["incident_id"].astype("string").eq(incident_id)]


def _investigation_case_labels(cases):
    return {
        row.investigation_id:
            f"{row.incident_id} · {row.metric_id} · {row.status} · follow up {row.follow_up_date}"
            f" · {row.owner} · case {row.investigation_id}"
        for row in cases.itertuples()
    }


def investigation_workbench(engine, role):
    ui.section("INVESTIGATIONS", "Connect evidence to a follow-up.",
               "Source observations, scenario assumptions, user decisions, and reported outcomes stay distinct.")
    source_scope(engine)
    source_id = casework.stable_source_id(engine.context)
    selector_source_id = "demo" if engine.context.source_kind == "demo" else engine.context.import_id
    incidents = engine.incidents
    incident_ids = incidents["incident_id"].dropna().astype(str).tolist()
    if not incident_ids:
        st.info("This source has no incident snapshots to investigate.")
        return

    incident_key = f"investigation_incident_{source_id}"
    metric_key = f"investigation_metric_{source_id}"
    step_key = f"investigation_step_{source_id}"
    seed_source = st.session_state.pop("investigation_seed_source", None)
    seed_incident = st.session_state.pop("investigation_seed_incident", None)
    seed_metric = st.session_state.pop("investigation_seed_metric", None)
    if seed_source == selector_source_id and seed_incident in incident_ids:
        st.session_state[incident_key] = seed_incident
    if seed_source == selector_source_id and seed_metric in engine.registry:
        st.session_state[metric_key] = seed_metric

    st.caption("Observed rows come from the selected source. Scenario values are user assumptions. "
               "Owner, rationale, and next action are decisions; follow-up outcomes are user-reported.")
    st.caption("Owner names are entered locally; the demo persona is not verified identity or access control.")
    step = st.radio("Investigation step", ["Create investigation", "Follow-up outcomes"],
                    horizontal=True, key=step_key)
    if step == "Create investigation":
        incident_id = st.selectbox("Incident", incident_ids, key=incident_key)
        metric_ids = list(engine.registry)
        metric_id = st.selectbox("Calculation evidence", metric_ids, key=metric_key,
                                 format_func=lambda key: _metric_name(engine, key))
        inputs = _scenario_parameters(engine, metric_id)
        parameters = inputs.parameters
        if metric_id == "field_completeness":
            fields = [column for column in incidents.columns if column in COMPLETENESS_FIELDS]
            if not fields:
                st.error("This source has no supported incident fields to inspect.")
                return
            parameters["field"] = st.selectbox("Incident field", fields,
                                               key=f"investigation_field_{source_id}")
        try:
            inspection = engine.inspect(metric_id, parameters=parameters)
        except ValueError as exc:
            st.error(str(exc))
            return
        definition, result, all_records = (
            inspection["definition"], inspection["result"], inspection["records"])
        value = format_value(engine.calculate(metric_id, parameters=parameters))
        a, b, c = st.columns([2, 1, 1])
        with a:
            ui.metric(_metric_name(engine, metric_id), value, result["status"], ui.ORANGE)
        with b:
            ui.metric("Eligible", f"{result['eligible_count']:,}", "Source-defined population", ui.CYAN)
        with c:
            ui.metric("Excluded", f"{result['excluded_count']:,}", "Review reasons below", ui.PURPLE)
        st.code(definition["formula"], language="text")
        if result["status"] != "available":
            st.warning(result.get("unavailable_reason") or "This calculation is unavailable from the selected source.")
        if metric_id in SCENARIO_PARAMETERS:
            st.info("This is a source-wide scenario, not a cost or time attribution to the selected incident.")

        selected_records = _selected_incident_rows(all_records, incident_id)
        membership_records = _selected_incident_rows(
            engine.inspect("unique_incident_count")["records"], incident_id)
        st.markdown("**Observed incident snapshot**")
        snapshot = incidents[incidents["incident_id"].astype("string").eq(incident_id)]
        snapshot_columns = [column for column in [
            "incident_id", "opened_at", "created_at", "status", "priority",
            "category", "assignment_group", "source_row"
        ] if column in snapshot]
        st.dataframe(snapshot[snapshot_columns], hide_index=True, width="stretch")
        st.markdown("**Calculation evidence for this incident**")
        if selected_records.empty:
            st.info("The selected metric has no row-level evidence for this incident. "
                    "The stored trace will retain its calculation status and incident membership.")
        else:
            st.dataframe(selected_records.head(250), hide_index=True, width="stretch")
            st.caption(f"{len(selected_records):,} metric evidence row(s) for this incident.")
        with st.expander("Inspect the source-count membership row"):
            st.dataframe(membership_records, hide_index=True, width="stretch")

        with st.form(f"investigation_create_{source_id}_{incident_id}"):
            owner = st.text_input("Owner · responsible person or team", max_chars=120,
                                  key=f"investigation_owner_{source_id}")
            rationale = st.text_area("Rationale · why investigate this incident?", max_chars=1500,
                                     key=f"investigation_rationale_{source_id}")
            next_action = st.text_area("Next action · what should happen?", max_chars=1000,
                                       key=f"investigation_action_{source_id}")
            follow_up_date = st.date_input("Follow-up date", value=None, key=f"investigation_due_{source_id}_{incident_id}")
            submitted = st.form_submit_button("Save investigation →", type="primary",
                                              key=f"investigation_create_submit_{source_id}")
        if submitted:
            try:
                trace = casework.build_trace_reference(
                    engine, incident_id, inspection, parameters, inputs.origins,
                    membership_records)
                casework.create_investigation(trace, owner, rationale, next_action,
                                              follow_up_date, role)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Investigation saved with an immutable calculation-trace reference.")
    else:
        cases = casework.list_investigations(source_id)
        if cases.empty:
            st.info("No investigations are recorded for this source yet.")
            return
        labels = _investigation_case_labels(cases)
        case_id = st.selectbox("Investigation", list(labels), format_func=labels.get,
                               key=f"investigation_case_{source_id}")
        case = casework.read_investigation(case_id)
        trace = json.loads(case["trace_json"])
        st.write(f"**Incident:** {case['incident_id']} · **Owner:** {case['owner']} · "
                 f"**Follow-up:** {case['follow_up_date']} · **Status:** {case['status']}")
        st.write(f"**Rationale:** {case['rationale']}")
        st.write(f"**Next action:** {case['next_action']}")
        st.caption(f"Stable source ID: {case['source_id']} · Trace: {case['trace_id']} "
                   f"(schema v{case['trace_version']}, formula {case['formula_version']})")
        st.json({"source": trace["source"], "metric_definition": trace["metric_definition"],
                 "result": trace["result"], "inputs": trace["inputs"], "evidence": trace["evidence"]})
        st.button("Open this metric in Calculation Inspector →", key=f"investigation_inspect_{case_id}",
                  on_click=navigate, args=("Calculation Inspector", case["metric_id"]), width="stretch")
        with st.form(f"investigation_outcome_{case_id}"):
            outcome_options = ["Choose an outcome", *casework.OUTCOME_STATUSES]
            existing_status = case["outcome_status"]
            status_index = outcome_options.index(existing_status) if existing_status else 0
            outcome_status = st.selectbox("Reported outcome status", outcome_options, index=status_index,
                                          key=f"investigation_outcome_status_{case_id}")
            outcome_note = st.text_area("Outcome note · what was observed after the action?",
                                        value=case["outcome_note"] or "", max_chars=1500,
                                        key=f"investigation_outcome_note_{case_id}")
            outcome_date = st.date_input(
                "Outcome observed date",
                value=date.fromisoformat(case["outcome_date"]) if case["outcome_date"] else None,
                key=f"investigation_outcome_date_{case_id}")
            measured_value = st.number_input(
                "Measured outcome value · optional", value=case["measured_value"],
                step=0.1, format="%.2f", key=f"investigation_measured_value_{case_id}")
            measured_unit = st.text_input(
                "Measured outcome unit · required with a value",
                value=case["measured_unit"] or "", max_chars=40,
                key=f"investigation_measured_unit_{case_id}")
            st.caption("Measurements and outcome notes are user-reported; OKai does not independently verify them.")
            outcome_submitted = st.form_submit_button(
                "Record follow-up outcome →", type="primary",
                key=f"investigation_record_outcome_{case_id}")
        if outcome_submitted:
            try:
                if outcome_status == "Choose an outcome":
                    raise ValueError("Choose a reported outcome status.")
                casework.record_outcome(case_id, outcome_status, outcome_note, outcome_date,
                                        measured_value, measured_unit, role)
            except ValueError as exc:
                st.error(str(exc))
            else:
                case = casework.read_investigation(case_id)
                st.success("Follow-up outcome recorded; the calculation trace remains unchanged.")
        events = casework.read_events(case_id)
        st.markdown("**Investigation history**")
        if not events.empty:
            st.dataframe(events[["event_type", "actor_role", "happened_at", "details_json"]],
                         hide_index=True, width="stretch")
        st.download_button(
            "Export review summary ↓", casework.build_review_export(case, events),
            f"okai_review_{case_id}.json", "application/json",
            key=f"investigation_export_{case_id}",
            help="Decision fields, reported outcome, the immutable calculation trace, "
                 "and the audit history, in one traceable file.")


def imported_incidents(engine, metadata):
    ui.section("INCIDENT INTELLIGENCE", "One incident, with its history intact.",
               "Explore final source snapshots and inspect the events that produced each one.")
    source_scope(engine)
    search = st.text_input("Find an imported incident", placeholder="Incident ID, category, or team")
    frame = engine.incidents
    if search:
        searchable = [name for name in ["incident_id", "category", "assignment_group"] if name in frame]
        mask = frame[searchable].fillna("").astype(str).apply(
            lambda column: column.str.contains(search, case=False, regex=False)).any(axis=1)
        frame = frame[mask]
    columns = [column for column in ["incident_id", "opened_at", "status", "priority", "category",
        "assignment_group", "resolved_at", "source_sla_met", "reassignment_count", "source_row"] if column in frame]
    st.caption(f"{len(frame):,} final incident snapshots. Unknown assignments remain visible.")
    st.dataframe(frame[columns].head(500), hide_index=True, width="stretch", height=360)
    st.download_button("Export incident snapshots ↓", frame[columns].to_csv(index=False).encode("utf-8"),
                       "okai_imported_incidents.csv", "text/csv")
    if frame.empty:
        return
    incident_id = st.selectbox("Inspect incident history", frame.incident_id.tolist())
    events = imports.read_events(engine.context.import_id, incident_id=incident_id)
    events = events.sort_values(["event_at", "source_sequence", "source_row"],
                                kind="stable", na_position="first")
    st.caption("The first observed event is not guaranteed to be the incident's creation event. "
               "Enriched outcome timestamps are historical outcomes, not prediction inputs.")
    st.dataframe(events, hide_index=True, width="stretch", height=330)
    st.button("Create evidence-linked investigation →", key="imported_investigation",
              on_click=navigate, args=("Investigations", None, incident_id), width="stretch")


def import_quality(engine, metadata):
    ui.section("DATA FOUNDATION", "Quality at the correct grain.",
               "Import outcomes count source rows; field completeness below counts final incident snapshots.")
    source_scope(engine)
    with st.expander("Import evidence and stage timings", expanded=True):
        st.json(metadata)
    fields = [field for field in ["incident_id", "opened_at", "resolved_at", "priority", "category",
              "assignment_group", "assigned_to", "source_sla_met"] if field in engine.incidents]
    values = []
    for field in fields:
        result = engine.calculate("field_completeness", parameters={"field": field})
        values.append({"field": field, "completeness_pct": result.value, "valid_records": result.numerator,
                       "eligible_records": result.denominator, "excluded_records": result.excluded_count})
    audit = pd.DataFrame(values)
    with ui.chart_panel("import_completeness", "FINAL INCIDENT SNAPSHOTS", "Completeness needs a denominator.",
                        "Each field uses the same final-incident population. Fields may be missing on the same incident.",
                        "Missing resolution timestamps reduce duration coverage. Missing assignment is reported as Unknown, not removed from team volume."):
        figure = ui.bar(audit, "completeness_pct", "field", "Field completeness (%)", "%{y}: %{x:.1f}%<extra></extra>", color=ui.PURPLE)
        figure.update_xaxes(range=[0, 100], title="Valid, known field values / final incident snapshots (%)")
        st.plotly_chart(figure, width="stretch")
        st.dataframe(audit, hide_index=True, width="stretch")
    rejected = imports.read_rejections(engine.context.import_id)
    st.write("**Rejected source rows**")
    st.caption("A rejected event is not a duplicate incident. Its original data and rejection reason are retained.")
    st.dataframe(rejected.head(250), hide_index=True, width="stretch")
    st.download_button("Export rejected source rows ↓", rejected.to_csv(index=False).encode("utf-8"),
                       "okai_import_rejections.csv", "text/csv")
    st.button("Inspect resolution coverage →", on_click=navigate,
              args=("Calculation Inspector", "median_resolution_hours"), key="quality_duration")


def decision_support(engine):
    ui.section("DECISION SUPPORT", "Evidence before intervention.",
               "Use explicit investigation rules and observed patterns. Statistical model scores remain in the synthetic Risk lab.")
    source_scope(engine)
    st.caption("These are final snapshots, not a point-in-time replay. The review timestamp must be at or after "
               "the latest source observation. The machine's current time is not used to age old exports.")
    with st.form("decision_rules"):
        as_of = st.text_input("Review as-of timestamp", value=engine.context.observation_end or "", key="decision_as_of",
                              placeholder="YYYY-MM-DD HH:MM:SS, in the source timestamp zone")
        a, b, c = st.columns(3)
        age = a.number_input("Open incident age threshold (hours)", min_value=0.0, value=48.0)
        backlog = b.number_input("Unresolved backlog threshold (incidents)", min_value=0, value=25, step=1)
        unassigned = c.checkbox("Flag high-priority incidents without a team", value=True)
        submitted = st.form_submit_button("Evaluate investigation rules →", type="primary")
    if submitted:
        try:
            config = ThresholdConfig(age_hours=age, backlog_threshold=backlog,
                                     high_priority_unassigned=unassigned)
            response = execute_metric_tool(engine, {"action": "alerts", "as_of": as_of or None,
                "thresholds": {"age_hours": config.age_hours, "backlog_threshold": config.backlog_threshold,
                               "high_priority_unassigned": config.high_priority_unassigned}, "limit": 1000})
            if not response["ok"]:
                raise ValueError(response["error"]["message"])
            st.session_state["decision_evidence"] = {"source": engine.context.dataset_id, "as_of": as_of,
                                                       "response": response}
            if tutorial.observe("decision"):
                st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
    evidence = st.session_state.get("decision_evidence")
    if evidence and evidence["source"] == engine.context.dataset_id:
        st.write(f"**Rule evidence as of {evidence['as_of'] or 'unspecified'}**")
        response = evidence["response"]
        st.caption(f"{response['total_records']:,} rule matches; up to 1,000 shown. One incident can match several rules.")
        if response["alerts"]:
            st.dataframe(pd.DataFrame(response["alerts"]), hide_index=True, width="stretch")
        else:
            st.info("No investigation rules matched this source and these settings.")
        if not response["temporal_rules_evaluated"]:
            st.caption("Age and deadline rules were not evaluated because no review timestamp was supplied.")
    ui.note("These configurable thresholds support investigation. They are not contractual SLA rules. "
            "An approaching-SLA alert requires an actual supplied deadline; the importer does not invent one.")
    dimension = st.selectbox("Investigate outcome concentration by", ["category", "assignment_group", "priority"])
    groups = engine.by_dimension(dimension).sort_values("breaches", ascending=False, na_position="last")
    st.dataframe(groups, hide_index=True, width="stretch", column_config=GROUP_COLUMN_LABELS)
    st.caption("Start by reviewing groups with a large count of adverse outcomes, then inspect case mix and data coverage. "
               "A final assignment or reassignment association does not establish responsibility or causation.")
    st.download_button("Export investigation evidence ↓", groups.to_csv(index=False).encode("utf-8"),
                       "okai_investigation_evidence.csv", "text/csv")
    st.button("Inspect the SLA definition →", on_click=navigate,
              args=("Calculation Inspector", "demo_sla_attainment" if engine.context.source_kind == "demo" else "source_sla_attainment"),
              key="decision_sla_definition")


def governance(engine):
    ui.section("SETTINGS & GOVERNANCE", "Make the boundaries explicit.",
               "Source settings, numerical authority, and the limits of this portfolio application.")
    source_scope(engine)
    st.markdown("**Numerical authority.** The calculation engine owns metric formulas and evidence. "
                "Dashboards, the inspector, and the read-only interpretation contract consume its results.\n\n"
                "**Source contract.** The Import Desk stores file hashes, mapping versions, timezone assumptions, "
                "raw copies, event histories, snapshots, and row validation evidence. A changed mapping creates a distinct import.\n\n"
                "**Prediction boundary.** The fitted model demonstrates methodology on synthetic creation-time inputs. "
                "Imported final snapshots are not sent to it. Real prediction requires point-in-time feature and label validation.\n\n"
                "**Human decisions.** Rule alerts and group comparisons recommend investigation; they do not perform automatic interventions.\n\n"
                "**Access.** Personas are mock login. Imports are local shared data, not tenant-isolated records protected by production authentication. "
                "The launcher binds to localhost. Use anonymized portfolio data.\n\n"
                "**Value estimates.** Labor capacity value requires explicit inputs and does not establish realized cash savings. "
                "No external generative AI, ticketing API, or identity provider is connected.")
    tutorial.question("governance", "What protects access to imported data in this demo?",
                      [tutorial.GOVERNANCE_ANSWER, "Production authentication isolates each user's imports"],
                      tutorial.GOVERNANCE_ANSWER)
    with st.expander("Calculation result contract"):
        st.json(engine.calculate("unique_incident_count").to_dict())
    with st.expander("Read-only interpretation tool contract"):
        st.json(TOOL_SCHEMA)
    st.caption("Threshold settings are entered in Decision Support. Timezone and mapping settings belong to each immutable import.")
