"""OKai's entry point: connect saved data, demo state, and page functions.

Streamlit runs this script from top to bottom whenever a widget changes. Local
variables are recreated on each run; session_state keeps one browser session's
widget/persona choices, while SQLite keeps review changes across page refreshes.
"""
import json
from uuid import uuid4

import joblib
import streamlit as st

from src import database, demo, ui, views, intelligence_views
from src.config import DB_PATH, METRICS_PATH, MODEL_PATH

PAGES = ["Overview", "Incident queue", "Import Desk", "Calculation Inspector",
         "Decision Support", "Data quality", "Risk lab", "Project notes", "Settings & Governance"]
LANDING = {"Analyst": "Incident queue", "Manager": "Overview", "Admin": "Data quality"}
# Landing cards can open these three demo views directly. An allowlist keeps
# query parameters from choosing arbitrary pages or pretending to be real auth.
SHORTCUTS = {"quality": ("Admin", "Data quality"), "overview": ("Manager", "Overview"),
             "risk": ("Analyst", "Risk lab"), "inspector": ("Manager", "Calculation Inspector")}


@st.cache_data(ttl=60)
def load_facts():
    """Reuse source snapshots for 60 seconds instead of querying on every click.

    This cache is shared across sessions, so only shared synthetic facts go here.
    Workspace-specific reviews are read separately, keeping saved actions fresh.
    """
    return database.read_incidents(), database.kpi_summary(), database.run_history()


@st.cache_resource
def load_model(version):
    """Keep one fitted model in memory rather than loading it on every rerun."""
    # Streamlit hashes arguments as part of the cache key. Although joblib does
    # not need `version`, passing the file's modification time reloads a rebuilt
    # artifact. Treat this shared resource as read-only; use it only to predict.
    return joblib.load(MODEL_PATH)


def enter_workspace():
    # Widget callbacks run before the next top-to-bottom render. Set navigation
    # here so the page radio is created with the correct role's landing page.
    role = st.session_state["login_role"]
    st.session_state["persona_role"] = role
    st.session_state["page"] = LANDING[role]


def change_role():
    st.session_state["page"] = LANDING[st.session_state["persona_role"]]


def sign_out():
    # Leaving the simulated persona clears navigation, not the saved workspace.
    st.session_state.pop("persona_role", None)
    st.session_state.pop("page", None)


def reset_demo(workspace_id):
    # Reset both persistent reviews and their widget/filter state before widgets
    # are rendered again; otherwise an old selection can hide the restored queue.
    views.reset_demo_workspace(workspace_id, st.session_state["persona_role"])


def login(incidents, metrics, runs):
    ui.masthead()
    ui.hero()
    introduction, access = st.columns([1.6, 1], gap="large")
    with introduction:
        ui.section("A DATA PROJECT, END TO END", "What deserves attention next?",
                   "OKai turns incident exports into traceable metrics and investigation evidence. "
                   "Explore the synthetic operations team, then import a historical event log and inspect every calculation.")
        successes = runs[runs.status.eq("success")]
        raw_rows = int(successes.iloc[0].rows_read) if not successes.empty else "—"
        a, b, c = st.columns(3)
        with a:
            ui.metric("Raw records", raw_rows, "Seeded synthetic export", ui.PURPLE,
                      destination="quality", action_label="View source data quality")
        with b:
            ui.metric("Clean incidents", len(incidents), "Validated and queryable", ui.CYAN,
                      destination="overview", action_label="View incident overview")
        with c:
            auc = f"{metrics['model']['roc_auc']:.3f}" if metrics else "—"
            ui.metric("Hold-out ROC-AUC", auc, "Synthetic chronological test set", ui.ORANGE,
                      destination="risk", action_label="Explore the risk lab")
    with access:
        with st.form("demo_login"):
            st.markdown("### Explore OKai.")
            st.caption("Start as an analyst, manager, or admin. Each persona opens a different view.")
            st.selectbox("Demo persona", list(demo.PROFILES), key="login_role",
                         format_func=lambda name: f"{name} — {demo.PROFILES[name]['name']}")
            st.caption("Analyst → review queue · Manager → overview · Admin → data quality")
            st.form_submit_button("Open workspace →", type="primary", width="stretch", on_click=enter_workspace)
        st.caption("Mock login · Fictional identities · Synthetic incident data. "
                   "Workspace changes are saved locally and survive a page refresh.")
    a, b, c = st.columns(3)
    with a:
        ui.feature("01 / CLEAN", "Start with better inputs.",
                   "See missing values, rejected records, and a pipeline that can be rerun safely.")
    with b:
        ui.feature("02 / UNDERSTAND", "Put the numbers in context.",
                   "Explore SQL-driven performance metrics and inspect the queries behind them.")
    with c:
        ui.feature("03 / ACT", "Turn a score into a next step.",
                   "Review the risk, assign responsibility, and keep a clear activity trail.")
    ui.footer()


def sidebar(workspace_id):
    with st.sidebar:
        st.html(ui.brand_html(sidebar=True) + '<div class="brand-caption">OPERATIONAL DECISION INTELLIGENCE</div>')
        st.divider()
        st.selectbox("Demo persona", list(demo.PROFILES), key="persona_role", on_change=change_role)
        role = st.session_state["persona_role"]
        profile = demo.PROFILES[role]
        st.html(f'<div class="persona"><div class="avatar">{profile["initials"]}</div>'
                f'<div><div class="persona-name">{profile["name"]}</div>'
                f'<div class="persona-title">{profile["title"]}</div></div></div>')
        st.radio("Workspace", PAGES, key="page", label_visibility="collapsed")
        st.divider()
        source_id = intelligence_views.source_selector()
        st.divider()
        with st.expander("Make the most of the demo"):
            st.caption("1. Review an open incident and save a note.\n\n"
                       "2. Switch to Manager to see the updated workload.\n\n"
                       "3. Import a historical event log in Import Desk.\n\n"
                       "4. Follow any KPI to its Calculation Inspector.")
        if role == "Admin":
            st.button("Reset demo workspace", key="admin_reset_sidebar", on_click=reset_demo,
                      args=(workspace_id,), width="stretch")
        st.button("Leave workspace ↗", key="sign_out", on_click=sign_out, width="stretch")
        st.caption(f"DEMO / {workspace_id[:8].upper()}\n\n"
                   "Personas simulate access. The analysis source is selected above; imports are shared locally.")
    return role, source_id


def main():
    """Prepare shared inputs once per rerun, then render the selected view."""
    st.set_page_config(page_title="OKai — Operational Decision Intelligence", page_icon="◉", layout="wide",
                       initial_sidebar_state="expanded")
    ui.inject_styles()
    if not DB_PATH.exists():
        ui.masthead()
        ui.hero()
        st.info("Prepare the sample data to open the workspace.")
        st.code("python -m src.etl\npython -m src.train_model", language="bash")
        st.stop()
    incidents, kpis, runs = load_facts()
    if incidents.empty:
        st.info("The incident dataset is empty. Run python -m src.etl to prepare it.")
        st.stop()
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8")) if METRICS_PATH.exists() else None
    shortcut = st.query_params.get("open", "")
    if shortcut in SHORTCUTS:
        st.session_state["persona_role"], st.session_state["page"] = SHORTCUTS[shortcut]
        del st.query_params["open"]  # Consume the shortcut once; later role changes stay in control.
    if st.session_state.get("persona_role") not in demo.PROFILES:
        login(incidents, metrics, runs)
        return
    # The URL selects a persistent set of demo edits. It is not authentication:
    # anyone with this UUID can revisit that workspace after choosing a persona.
    # A refresh loses session_state, but retaining the URL retains the saved data.
    try:
        workspace_id = demo.validate_workspace_id(st.query_params.get("workspace", ""))
    except (ValueError, AttributeError, TypeError):
        workspace_id = uuid4().hex
        st.query_params["workspace"] = workspace_id
    demo.ensure_workspace(workspace_id)
    role, source_id = sidebar(workspace_id)
    ui.masthead()
    # A save callback can leave a one-use message for the next render. pop()
    # displays it once, so later filter changes do not repeat a stale success.
    if message := st.session_state.pop("flash", None):
        st.success(message)
    if source_id == "demo":
        engine = intelligence_views.demo_engine(incidents, runs)
        import_metadata = None
    else:
        engine, import_metadata = intelligence_views.imported_engine(source_id)
    model = load_model(MODEL_PATH.stat().st_mtime_ns) if source_id == "demo" and MODEL_PATH.exists() else None
    # Page functions own presentation; database/demo own SQL and persistence.
    # Keeping these responsibilities separate makes each part easier to inspect.
    page = st.session_state["page"]
    if page == "Overview":
        intelligence_views.operational_overview(engine, workspace_id)
    elif page == "Incident queue":
        if source_id == "demo":
            views.incident_queue(incidents, workspace_id, role, model)
        else:
            intelligence_views.imported_incidents(engine, import_metadata)
    elif page == "Risk lab":
        if source_id == "demo":
            views.risk_lab(incidents, model, metrics)
        else:
            st.info("The Risk lab is validated only on the synthetic demo. Imported final snapshots are not scored. "
                    "Select Synthetic demo in Analysis source to explore the fitted model.")
            st.button("Inspect imported outcome evidence →", on_click=intelligence_views.navigate,
                      args=("Calculation Inspector", "source_sla_attainment"))
    elif page == "Data quality":
        if source_id == "demo":
            views.data_quality(runs, workspace_id, role)
        else:
            intelligence_views.import_quality(engine, import_metadata)
    elif page == "Import Desk":
        intelligence_views.import_desk()
    elif page == "Calculation Inspector":
        intelligence_views.calculation_inspector(engine)
    elif page == "Decision Support":
        intelligence_views.decision_support(engine)
    elif page == "Settings & Governance":
        intelligence_views.governance(engine)
    elif page == "Project notes":
        st.caption("These project notes explain the synthetic demo pipeline and model. "
                   "Imported-source definitions and evidence are available in Calculation Inspector.")
        views.project_notes(incidents, metrics, runs)
    ui.footer()


if __name__ == "__main__":
    main()
