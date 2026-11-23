"""Dashboard pages: SQL analytics, an editable demo queue, and inspectable evidence."""
import math
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import charts, database, demo, quality, tutorial, ui
from src.config import CATEGORIES, PRIORITIES, RISK_BANDS, risk_level
from src.train_model import explain, predict


def go_to(page):
    # Button callbacks run before the next script pass, so the sidebar widget
    # reads the new page without changing an already-rendered widget's value.
    st.session_state["page"] = page


def reset_demo_workspace(workspace_id, role):
    """Restore both saved demo data and the filters used to display that data."""
    demo.reset_workspace(workspace_id, role)
    for key in list(st.session_state):
        if key.startswith("review_") or key in {"queue_search", "queue_band", "queue_state"}:
            del st.session_state[key]
    st.session_state["flash"] = "Demo workspace reset. The original incident queue is ready."


def overview(incidents, kpis, workspace_id):
    """Compatibility entry: use the same engine and view as imported sources.

    ``kpis`` remains in the signature for existing callers, but numerical results
    are obtained from the calculation engine instead of a second UI formula.
    """
    from src.intelligence_views import demo_engine, operational_overview
    return operational_overview(demo_engine(incidents, database.run_history()), workspace_id)


def _open_queue(incidents, workspace_id, role, model):
    """Filter a workspace view, then write a review only when its form submits."""
    queue = demo.read_queue(workspace_id)
    a, b, c, d = st.columns(4)
    with a:
        ui.metric("Open incidents", len(queue), "Outcome is still unknown")
    with b:
        scored = int(queue.risk_level.notna().sum())
        note = (f"Creation-time estimates · {len(queue) - scored} unscored" if scored
                else "No creation-time scores available")
        ui.metric("High risk", int(queue.risk_level.eq("High").sum()) if scored else "Unavailable", note, ui.ORANGE)
    with c:
        ui.metric("Reviewed", int(queue.review_state.ne("Unreviewed").sum()), "Saved in this workspace", ui.PURPLE)
    with d:
        ui.metric("Without an owner", int(queue.owner.eq("Unassigned").sum()), "A useful place to start", ui.CYAN)

    search_col, risk_col, state_col = st.columns([2, 1, 1.3])
    search = search_col.text_input("Find an incident", placeholder="ID, service, team, or owner", key="queue_search")
    band = risk_col.selectbox("Risk band", ["All risk bands", "High", "Medium", "Low"], key="queue_band")
    state = state_col.selectbox("Review state", ["All review states"] + demo.REVIEW_STATES, key="queue_state")
    view = queue.copy()
    if search:
        columns = ["incident_id", "affected_service", "assigned_team", "owner"]
        # Treat search text literally: a bracket or dot is user text, not a
        # regular expression. any(axis=1) keeps a row if any chosen field matches.
        view = view[view[columns].apply(lambda col: col.str.contains(search, case=False, regex=False, na=False)).any(axis=1)]
    if band != "All risk bands":
        view = view[view.risk_level.eq(band)]
    if state != "All review states":
        view = view[view.review_state.eq(state)]
    st.caption(f"{len(view)} of {len(queue)} open incidents · ordered by estimated breach risk where available")
    columns = ["incident_id", "priority", "affected_service", "assigned_team", "breach_probability",
               "review_state", "owner"]
    display = view[columns].copy()
    display["owner"] = display["owner"].map(demo.owner_label)
    # Stored probabilities stay in [0, 1] for ML. Only the presentation copy is
    # multiplied by 100, avoiding accidental double conversion in later scoring.
    display["breach_probability"] = (display["breach_probability"] * 100).round(1)
    st.dataframe(display, width="stretch", hide_index=True, height=285,
                 column_config={"incident_id": "Incident", "priority": "Priority", "affected_service": "Service",
                                "assigned_team": "Assigned team", "review_state": "Review", "owner": "Owner",
                                "breach_probability": st.column_config.ProgressColumn(
                                    "Estimated risk", min_value=0, max_value=100, format="%.0f%%")})
    st.download_button("Export this queue ↓", view.to_csv(index=False).encode("utf-8"),
                       "okai_open_incidents.csv", "text/csv", key="queue_export")
    if view.empty:
        ui.note("No incidents match these filters. Clear the search or choose all risk bands and review states.")
        if tutorial.is_current("queue"):
            st.info("The handover needs an open incident. Clear the filters above or use Skip mission in the guide.")
        return

    ui.section("FROM INSIGHT TO ACTION", "Take a closer look.",
               "Review an incident, assign its next owner, and leave a clear handover.")
    if tutorial.is_current("queue") and not st.session_state["tutorial"]["verified"]:
        st.info("Guide: choose an incident, select an owner, set the review state to In review, "
                "write a handover note, and select Save review. All four are needed to unlock Next.")
        if feedback := st.session_state.pop("tutorial_queue_feedback", None):
            st.warning(feedback)
    ids = view.incident_id.tolist()
    if st.session_state.get("review_incident") not in ids:
        st.session_state.pop("review_incident", None)
    chosen = st.selectbox("Incident to inspect", ids, key="review_incident")
    incident = queue[queue.incident_id.eq(chosen)].iloc[0]
    detail, activity = st.columns([1.5, 1], gap="large")
    with detail:
        left, right = st.columns([3, 1])
        left.markdown(f"### {incident['affected_service']}")
        left.caption(f"{chosen} · {incident['priority']} priority · {incident['category']}")
        with right:
            ui.risk_pill(incident["risk_level"])
        probability = incident["breach_probability"]
        if pd.notna(probability):
            st.markdown(f"**{probability:.0%} estimated breach risk** · created {incident['created_at'][:10]}")
        st.caption(f"Source status: {incident['status']} · SLA target: {incident['sla_target_minutes']:,} minutes. "
                   "Review state is a separate demo workflow.")
        if model is not None:
            contributions = explain(model, incidents[incidents.incident_id.eq(chosen)]).head(3)
            drivers = [f"{row.feature} ({'raises' if row.contribution > 0 else 'lowers'} the estimate)"
                       for row in contributions.itertuples()]
            with st.expander("What informed this risk estimate?"):
                for driver in drivers:
                    st.write("• " + driver)
                st.caption("Associations learned from synthetic history; scores describe relative risk.")
        teams = sorted(incidents.assignment_group.unique())
        with st.form(f"review_form_{chosen}", clear_on_submit=True):
            # A form batches widget edits. Browsing or changing a dropdown alone
            # does not commit partial assignments or create audit events.
            team = st.selectbox("Assigned team", teams, index=teams.index(incident["assigned_team"]),
                                key=f"review_team_{chosen}")
            left, right = st.columns(2)
            owner = left.selectbox("Owner", demo.OWNERS, index=demo.OWNERS.index(incident["owner"]),
                                   key=f"review_owner_{chosen}",
                                   format_func=demo.owner_label)
            review_state = right.selectbox("Review state", demo.REVIEW_STATES,
                                            index=demo.REVIEW_STATES.index(incident["review_state"]),
                                            key=f"review_status_{chosen}")
            note = st.text_area("Handover note", placeholder="What should the next person investigate?",
                                max_chars=1500, height=100, key=f"review_note_{chosen}")
            submitted = st.form_submit_button("Save review →", type="primary", width="stretch")
        if submitted:
            try:
                saved = demo.save_review(workspace_id, chosen, role, team, owner, review_state, note)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state["flash"] = "Review saved. The team workload and activity timeline are up to date." if saved else "Everything is already up to date."
                if saved and owner != "Unassigned" and review_state != "Unreviewed" and note.strip():
                    tutorial.observe("queue")
                elif tutorial.is_current("queue"):
                    missing = []
                    if owner == "Unassigned":
                        missing.append("choose an owner")
                    if review_state == "Unreviewed":
                        missing.append("choose a review state other than Unreviewed")
                    if not note.strip():
                        missing.append("write a handover note")
                    st.session_state["tutorial_queue_feedback"] = (
                        "Next is still locked: " + "; ".join(missing) + ", then save the review."
                        if missing else "The review was not saved. Change the review or add a note, then save.")
                # The queue above was read before the save. A fresh pass reads
                # the committed values and displays a consistent workload/timeline.
                st.rerun()
    with activity:
        ui.section("THE HANDOVER", "Incident activity.")
        ui.timeline(demo.read_events(workspace_id, chosen), owner_labels=demo.OWNER_LABELS)


def _archive(incidents):
    """Explore original source facts; demo assignments never rewrite this history."""
    a, b, c = st.columns([2, 1, 1])
    search = a.text_input("Search the full dataset", placeholder="ID, service, or team", key="archive_search")
    priorities = b.multiselect("Priority", PRIORITIES, default=PRIORITIES, key="archive_priorities")
    categories = c.multiselect("Category", CATEGORIES, default=CATEGORIES, key="archive_categories")
    view = incidents[incidents.priority.isin(priorities) & incidents.category.isin(categories)].copy()
    if search:
        view = view[view[["incident_id", "affected_service", "assignment_group"]]
                    .apply(lambda col: col.str.contains(search, case=False, regex=False, na=False)).any(axis=1)]
    view["sla_outcome"] = view.sla_breached.map({1: "Breached", 0: "Met"}).fillna("Pending")
    columns = ["incident_id", "created_at", "priority", "category", "affected_service", "assignment_group",
               "status", "resolution_time_minutes", "sla_target_minutes", "sla_outcome"]
    st.caption(f"{len(view)} of {len(incidents)} cleaned incidents · source facts remain unchanged by demo actions")
    st.dataframe(view[columns].sort_values("created_at", ascending=False), hide_index=True,
                 width="stretch", height=450,
                 column_config={"incident_id": "Incident", "created_at": "Created", "priority": "Priority",
                                "category": "Category", "affected_service": "Service", "assignment_group": "Source team",
                                "status": "Source status", "resolution_time_minutes": "Resolution (min)",
                                "sla_target_minutes": "SLA target (min)", "sla_outcome": "SLA outcome"})
    st.download_button("Export filtered history ↓", view[columns].to_csv(index=False).encode("utf-8"),
                       "okai_incident_history.csv", "text/csv", key="archive_export")


def incident_queue(incidents, workspace_id, role, model):
    ui.section("02 / INCIDENT WORKSPACE", "Make the next move clear.",
               "Risk-ranked open work, a shared handover, and the full historical record.")
    open_tab, archive_tab = st.tabs(["Open review queue", "Incident history"])
    with open_tab:
        _open_queue(incidents, workspace_id, role, model)
    with archive_tab:
        _archive(incidents)


def risk_lab(incidents, model, metrics):
    """Separate interactive prediction from the saved out-of-time evaluation.

    What-if controls call the final refitted model. The evidence tab reads the
    metrics calculated during training's earlier hold-out evaluation; it does
    not recompute a test score using a model that has now seen that history.
    """
    ui.section("03 / MACHINE LEARNING", "A little foresight. A clearer decision.",
               "Explore a creation-time risk estimate, then inspect the evidence behind the model.")
    if model is None or metrics is None:
        st.info("Prepare the model with python -m src.train_model to use the risk lab.")
        return
    ui.note("These are relative risk estimates learned from synthetic incidents. Balanced class weights "
            "help surface breaches, but the scores are not calibrated real-world odds.")
    score_tab, evidence_tab = st.tabs(["Score an incident", "Model evidence"])
    with score_tab:
        ui.section("WHAT IF?", "Change the context. See the estimate.")
        a, b, c = st.columns(3)
        priority = a.selectbox("Priority", PRIORITIES, index=1, key="score_priority",
                               on_change=tutorial.risk_changed)
        category = a.selectbox("Category", CATEGORIES, key="score_category")
        services = sorted(incidents[incidents.category.eq(category)].affected_service.unique())
        service = b.selectbox("Affected service", services, key="score_service")
        group = b.selectbox("Assignment group", sorted(incidents.assignment_group.unique()), key="score_group")
        date = c.date_input("Created on", pd.Timestamp("2024-07-01"), key="score_date")
        hour = c.slider("Created at hour", 0, 23, 10, key="score_hour")
        new = pd.DataFrame([dict(priority=priority, category=category, affected_service=service,
                                 assignment_group=group, created_at=f"{date} {hour:02d}:00:00")])
        try:
            probability = float(predict(model, new)[0])
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("The model returned an invalid probability.")
            contributions = explain(model, new).head(8).iloc[::-1]
        except Exception as exc:
            st.error(f"Risk calculation could not be completed: {exc}")
            return
        if tutorial.risk_scored():
            st.rerun()
        left, right = st.columns([1, 2])
        with left:
            ui.metric("Estimated breach risk", f"{probability:.0%}", "At incident creation", ui.ORANGE)
            ui.risk_pill(risk_level(probability))
            st.caption(" · ".join(f"{label}: {low:.0%}–{min(high, 1):.0%}"
                                  for low, high, label in RISK_BANDS))
        with right:
            fig = go.Figure(go.Bar(x=contributions.contribution, y=contributions.feature, orientation="h",
                                   marker_color=[ui.ORANGE if x > 0 else ui.PURPLE for x in contributions.contribution],
                                   hovertemplate="%{y}: %{x:+.2f} log-odds<extra></extra>"))
            fig.update_layout(title="What pushes the estimate up or down", bargap=.4)
            st.plotly_chart(ui.style(fig, 330), width="stretch")
        st.caption("Orange contributions raise the estimate; purple contributions lower it. "
                   "The model uses creation-time inputs; later resolution time and outcome are excluded.")
    with evidence_tab:
        split = metrics["split"]
        a, b, c, d = st.columns(4)
        with a:
            ui.metric("Hold-out ROC-AUC", f"{metrics['model']['roc_auc']:.3f}", "Risk ranking on unseen later incidents", ui.ORANGE)
        with b:
            ui.metric("Breach recall", f"{metrics['model']['recall']:.1%}", "At the 0.50 decision threshold", ui.PURPLE)
        with c:
            ui.metric("Training incidents", split["train_rows"], f"{split['train_start'][:10]} → {split['train_end'][:10]}")
        with d:
            ui.metric("Test incidents", split["test_rows"], f"{split['test_start'][:10]} → {split['test_end'][:10]}", ui.CYAN)
        rows = []
        for key, label in [("model", "Logistic regression"), ("baseline_priority_rate", "Priority rule"),
                           ("baseline_majority_class", "Always predict no breach")]:
            rows.append({"Model": label, **{name: metrics[key][name]
                                            for name in ["precision", "recall", "f1", "roc_auc"]}})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={name: st.column_config.NumberColumn(name.upper() if name == "f1" else name.replace("_", " ").title(), format="%.3f")
                                    for name in ["precision", "recall", "f1", "roc_auc"]})
        left, right = st.columns(2)
        cm = metrics["model"]["confusion_matrix"]
        z = [[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]]
        fig = go.Figure(go.Heatmap(z=z, x=["Predicted met", "Predicted breach"],
                                   y=["Actually met", "Actually breached"], text=z, texttemplate="%{text}",
                                   colorscale=[[0, "#eeeae2"], [1, ui.ORANGE]], showscale=False, xgap=3, ygap=3))
        fig.update_layout(title="Confusion matrix", yaxis_autorange="reversed")
        left.plotly_chart(ui.style(fig), width="stretch")
        roc = metrics["roc_curve"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Random",
                                 line=dict(color="#aaa298", dash="dash", width=1)))
        fig.add_trace(go.Scatter(x=roc["fpr"], y=roc["tpr"], mode="lines", name="Model",
                                 line=dict(color=ui.ORANGE, width=2)))
        fig.update_layout(title="ROC curve", legend=dict(orientation="h", y=-.2))
        fig = ui.style(fig)
        fig.update_xaxes(title="False positive rate")
        fig.update_yaxes(title="True positive rate")
        right.plotly_chart(fig, width="stretch")
        ui.note(f"The hold-out contains {split['test_rows']} synthetic incidents, with a {split['test_breach_rate']:.0%} "
                "breach rate. These metrics demonstrate evaluation methodology; they do not establish performance "
                "on a real service desk. Displayed incident scores use a final model refit on all labelled history.")
        with st.expander("Inspect learned feature weights"):
            coefficients = pd.DataFrame(metrics["coefficients"])
            top = pd.concat([coefficients.head(8), coefficients.tail(8)]).drop_duplicates().sort_values("coefficient")
            fig = go.Figure(go.Bar(x=top.coefficient, y=top.feature, orientation="h",
                                   marker_color=[ui.ORANGE if value > 0 else ui.PURPLE for value in top.coefficient]))
            fig.update_layout(title="Associations learned from the sample history", bargap=.4)
            st.plotly_chart(ui.style(fig, 490), width="stretch")
            st.caption("Related features share credit. Coefficients describe associations, not causal effects.")


def data_quality(runs, workspace_id, role):
    """Render one run's evidence with explicit row, rule, and cell denominators.

    Chart calculations live in quality.py; charts.py owns their visual grammar.
    This page only chooses a run and arranges the evidence. That separation
    prevents a future styling change from quietly changing a metric's meaning.
    """
    ui.section("04 / DATA QUALITY", "Know what the numbers are counting.",
               "Follow one pipeline run from source rows to validated data, with every exclusion explained.")
    successes = runs[runs.status.eq("success")]
    if successes.empty:
        st.info("Run python -m src.etl to create a successful pipeline snapshot.")
        return

    # Every figure below uses this same saved run, never a mixture of today's
    # CSV and an older rejection log. The newest successful run is the default.
    lookup = successes.set_index("run_id")
    selected = st.selectbox(
        "Pipeline run", successes.run_id.tolist(), key="quality_run",
        format_func=lambda run_id: f"Run #{int(run_id)} · {lookup.loc[run_id, 'finished_at']} UTC")
    run = lookup.loc[selected]
    rejected = database.rejected_for_run(int(selected))
    try:
        report = quality.build_report(run, rejected)
    except (ValueError, TypeError) as exc:
        st.error(f"This run's quality records cannot be reconciled: {exc}")
        return

    source_name = str(run["source_file"]).replace("\\", "/").rsplit("/", 1)[-1]
    ui.quality_scope(int(selected), source_name, str(run["finished_at"]))
    a, b, c, d = st.columns(4)
    shares = report.outcomes.set_index("kind").source_pct
    with a:
        ui.metric("Source rows", f"{report.source_rows:,}", "Rows read in the selected run")
    with b:
        ui.metric("Loaded", f"{report.loaded_rows:,}", f"{shares['loaded']:.1f}% of source rows",
                  charts.QUALITY_COLORS["loaded"])
    with c:
        ui.metric("Duplicates", f"{report.duplicate_rows:,}", f"{shares['duplicate']:.1f}% of source rows",
                  charts.QUALITY_COLORS["duplicate"])
    with d:
        ui.metric("Invalid rows", f"{report.invalid_rows:,}", f"{shares['invalid']:.1f}% of source rows",
                  charts.QUALITY_COLORS["invalid"])
    ui.note(f"Row balance: {report.loaded_rows:,} loaded + {report.duplicate_rows:,} duplicates + "
            f"{report.invalid_rows:,} invalid = {report.source_rows:,} source rows. "
            f"The {report.duplicate_rows + report.invalid_rows:,} excluded rows already include duplicates.")
    tutorial.question("quality", "Which outcomes add up to all source rows?",
                      [tutorial.QUALITY_ANSWER, "Only loaded and invalid source rows"], tutorial.QUALITY_ANSWER)

    left, right = st.columns(2, gap="large")
    with left:
        with ui.chart_panel(
            "quality_outcomes", "01 / SOURCE ROWS", "Where did the rows go?",
            f"One exclusive outcome per row · denominator: {report.source_rows:,} source rows.",
            "Each source row appears once. Loaded, duplicate, and invalid counts add up to the source total."):
            ui.chart_legend([("Loaded", charts.QUALITY_COLORS["loaded"]),
                             ("Duplicate", charts.QUALITY_COLORS["duplicate"]),
                             ("Invalid", charts.QUALITY_COLORS["invalid"])])
            if report.source_rows:
                st.plotly_chart(charts.row_outcomes(report), width="stretch",
                                config=charts.QUALITY_CONFIG, key="quality_outcomes_plot")
            else:
                ui.chart_empty("No source rows were read in this run.")
    with right:
        with ui.chart_panel(
            "quality_rules", "02 / INVALID ROWS", "Which validation rules failed?",
            f"Duplicates excluded · denominator: {report.invalid_rows:,} invalid rows.",
            "One row can fail multiple rules. Adding these bars counts rule matches, not unique rejected rows."):
            ui.chart_legend([("Rows matching a failed rule", charts.QUALITY_COLORS["invalid"])])
            if not report.rule_failures.empty:
                st.plotly_chart(charts.validation_rules(report), width="stretch",
                                config=charts.QUALITY_CONFIG, key="quality_rules_plot")
            else:
                ui.chart_empty("No invalid rows. There are no failed validation rules to plot.")

    nonzero = report.fields[report.fields.missing_cells.gt(0)]
    with ui.chart_panel(
        "quality_missing", "03 / MISSING CELLS", "Missing values need context.",
        f"{len(nonzero)} fields have missing values · each percentage uses {report.source_rows:,} source rows.",
        "Each bar counts missing cells in one field; the same row can appear in several bars. "
        "Empty values and recognized markers such as N/A count as missing. Outcome fields may be "
        "missing for open incidents; their color does not claim every missing outcome is valid."):
        legend = [("Required input", charts.QUALITY_COLORS["required"]),
                  ("Outcome field · may be expected", charts.QUALITY_COLORS["outcome"])]
        if nonzero.kind.isin(["derived", "informational"]).any():
            legend.append(("Derived / extra field", charts.QUALITY_COLORS["informational"]))
        ui.chart_legend(legend)
        if not nonzero.empty:
            st.plotly_chart(charts.missing_fields(report), width="stretch",
                            config=charts.QUALITY_CONFIG, key="quality_missing_plot")
        else:
            ui.chart_empty("No missing values were recorded in the source fields.")

    ui.section("FOLLOW THE EVIDENCE", "Inspect the rows behind the charts.",
               "These records and field counts belong to the selected pipeline run.")
    rejected_tab, fields_tab, runs_tab, rules_tab = st.tabs(
        ["Rejected rows", "Field audit", "Pipeline history", "Rules & definitions"])
    with rejected_tab:
        # Attach a readable disposition without changing the stored audit data.
        display = rejected.copy()
        is_duplicate = display.reason.str.split(";").apply(
            lambda rules: any(rule.strip() == "duplicate incident_id" for rule in rules))
        display["rejection_type"] = is_duplicate.map({True: "Duplicate", False: "Invalid"})
        columns = ["incident_id", "rejection_type", "reason", "raw_record"]
        st.caption(f"{len(display):,} excluded source rows = {report.duplicate_rows:,} duplicates "
                   f"+ {report.invalid_rows:,} invalid rows.")
        st.dataframe(display[columns], hide_index=True, width="stretch", height=310,
                     column_config={"incident_id": "Incident", "rejection_type": "Outcome",
                                    "reason": "Recorded reason", "raw_record": "Original source row (JSON)"})
        st.download_button("Export rejected rows ↓", display[columns].to_csv(index=False).encode("utf-8"),
                           f"okai_run_{int(selected)}_rejected.csv", "text/csv")
    with fields_tab:
        st.caption("All profiled fields, including zero counts. A field's policy is separate from its missing-value count.")
        audit = report.fields[["label", "missing_cells", "source_pct", "policy"]]
        st.dataframe(audit, hide_index=True, width="stretch",
                     column_config={"label": "Source field", "missing_cells": "Missing cells",
                                    "source_pct": st.column_config.NumberColumn("% of source rows", format="%.1f%%"),
                                    "policy": "How to interpret a missing value"})
        st.download_button("Export field audit ↓", audit.to_csv(index=False).encode("utf-8"),
                           f"okai_run_{int(selected)}_fields.csv", "text/csv")
    with runs_tab:
        st.dataframe(runs.drop(columns=["missing_values"]), hide_index=True, width="stretch", height=280)
        st.caption("'Loaded' counts valid rows processed by that run; 'new incidents' counts newly inserted IDs. "
                   "A repeat import can load the same valid rows while adding zero new incidents.")
    with rules_tab:
        st.dataframe(pd.DataFrame([
            {"Measure": "Source-row outcomes", "Counting unit": "One source row",
             "Denominator": "All source rows", "Can bars overlap?": "No"},
            {"Measure": "Validation rules", "Counting unit": "One invalid row matching a rule",
             "Denominator": "Invalid rows; duplicates excluded", "Can bars overlap?": "Yes, across different rules"},
            {"Measure": "Missing values", "Counting unit": "One missing cell in a field",
             "Denominator": "All source rows, per field", "Can bars overlap?": "Yes, across fields"},
        ]), hide_index=True, width="stretch")
        st.markdown("**Validation order:** normalize values → remove duplicate IDs → validate the remaining rows "
                    "→ recompute SLA fields → upsert valid incidents. Open incidents have an unknown SLA outcome.")
        st.caption("The raw missing-value profile has no breakdown by source status. "
                   "Use the row-level rejection reasons to determine which missing values failed validation.")
    if role == "Admin":
        ui.section("DEMO ADMINISTRATION", "A fresh start for the next walkthrough.",
                   "Reset clears workspace reviews and notes. It preserves these pipeline snapshots and model evidence.")
        if st.button("Reset this demo workspace", key="admin_reset_page"):
            reset_demo_workspace(workspace_id, role)
            st.rerun()


SQL_EXAMPLES = {
    "SLA compliance by team": """SELECT assignment_group AS team,
       COUNT(*) AS incidents,
       SUM(sla_breached) AS breaches,
       ROUND(100.0 * SUM(sla_breached = 0)
             / NULLIF(COUNT(sla_breached), 0), 1) AS compliance_pct
FROM incidents
GROUP BY assignment_group
ORDER BY compliance_pct;""",
    "Rank open incidents by risk": """SELECT i.incident_id, i.priority, i.affected_service,
       ROUND(p.breach_probability * 100, 1) AS estimated_risk_pct,
       p.risk_level
FROM incidents AS i
JOIN predictions AS p ON p.incident_id = i.incident_id
WHERE i.sla_breached IS NULL
ORDER BY p.breach_probability DESC;""",
    "Monthly breach trend with a window function": """WITH monthly AS (
    SELECT strftime('%Y-%m', created_at) AS month,
           SUM(sla_breached IS NOT NULL) AS resolved,
           SUM(sla_breached = 1) AS breaches
    FROM incidents
    GROUP BY month
)
SELECT month, resolved, breaches,
       ROUND(100.0 * SUM(breaches) OVER (ORDER BY month)
             / NULLIF(SUM(resolved) OVER (ORDER BY month), 0), 1)
           AS cumulative_breach_pct
FROM monthly
ORDER BY month;""",
}


def project_notes(incidents, metrics, runs):
    """Expose reproducible evidence and a small set of read-only SQL examples."""
    ui.section("05 / BEHIND THE PROJECT", "The work behind the interface.",
               "One operational question, connected end to end: which incidents deserve attention first?")
    a, b, c = st.columns(3)
    with a:
        ui.feature("01 / DATA ENGINEERING", "Make messy data usable.",
                   "A seeded incident generator, explicit validation, idempotent loads, and a rejection audit trail.")
    with b:
        ui.feature("02 / SQL & ANALYSIS", "Make performance explainable.",
                   "Joins, conditional aggregates, CTEs, and window functions turn incident facts into inspectable metrics.")
    with c:
        ui.feature("03 / MACHINE LEARNING", "Make evaluation honest.",
                   "Creation-time features, chronological evaluation, baseline comparisons, and per-incident contributions.")
    ui.section("THE DATA JOURNEY", "Every number has a path.")
    successes = runs[runs.status.eq("success")]
    latest = successes.iloc[0] if not successes.empty else None
    a, b, c = st.columns(3)
    with a:
        ui.metric("01 / Raw export", int(latest.rows_read) if latest is not None else "—", "Synthetic source rows", ui.PURPLE)
    with b:
        ui.metric("02 / Clean facts", len(incidents), "Validated and stored in SQLite", ui.CYAN)
    with c:
        ui.metric("03 / Labelled history", int(incidents.sla_breached.notna().sum()), "Resolved incidents eligible for training", ui.ORANGE)
    with st.expander("Inspect SQL and run it against the sample data", expanded=True):
        selected = st.selectbox("Choose a query", list(SQL_EXAMPLES), key="sql_example")
        sql = SQL_EXAMPLES[selected]
        # These queries are curated SELECT statements, not arbitrary user SQL.
        # Inspecting the portfolio cannot accidentally mutate its incident facts.
        st.code(sql, language="sql")
        st.dataframe(database.query(sql), hide_index=True, width="stretch")
    with st.expander("A three-minute walkthrough"):
        st.markdown("1. **Overview:** explain the SLA denominator and compare performance across priorities.\n"
                    "2. **Incident queue:** review a high-risk open incident, assign an owner, and save a handover.\n"
                    "3. **Manager persona:** inspect the updated team workload and workspace activity.\n"
                    "4. **Risk lab:** change a creation-time input and compare the model with its baselines.\n"
                    "5. **Data quality:** inspect a rejected record and explain why an idempotent rerun adds no duplicates.")
    with st.expander("What is real, and what is simulated?"):
        st.markdown("**Working components:** Python ETL, SQLite storage, SQL metrics, scikit-learn training and scoring, "
                    "saved workspace reviews, audit events, CSV exports, and repeatable reset.\n\n"
                    "**Simulated components:** incident source data, company identities, login personas, and the operational workspace. "
                    "No external ticketing system is connected. Demo roles provide a product walkthrough, not production authentication.\n\n"
                    "**Limits:** the dataset is small and synthetic. Risk estimates are uncalibrated; the hold-out demonstrates methodology. "
                    "Validation on real historical incidents is required to assess real-world usefulness.")
    with st.expander("Reproduce the analysis locally"):
        st.code("python -m src.generate_data\npython -m src.etl\npython -m src.train_model\npython -m pytest\nstreamlit run app.py", language="bash")
        st.caption("The generator uses a fixed seed. Workspace reviews are stored separately from the source facts used for modelling.")
