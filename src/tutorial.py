"""Optional, session-scoped missions using the existing synthetic workspace."""
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class Mission:
    page: str
    title: str
    task: str
    insight: str
    metric: str | None = None
    layer: str = ""
    location: str = ""
    success: str = ""


MISSIONS = {
    "orientation": Mission("Incident queue", "Start with the incident queue",
        "Open Incident queue using the button below or the navigation on the left.",
        "The queue is where the team finds open work before investigating or assigning it.",
        layer="Orientation", location="Incident queue in the left navigation",
        success="Incident queue opened. You can now begin your role's first operational task."),
    "overview": Mission("Overview", "Read the operational picture",
        "Compare unique incidents with demo-policy SLA attainment. Select Explore Demo-policy SLA attainment.",
        "A percentage needs a population; open incidents do not have a known SLA outcome.",
        layer="Measure", location="Demo-policy SLA attainment card on Overview",
        success="The SLA metric is open. Next, inspect the records behind the percentage."),
    "inspector": Mission("Calculation Inspector", "Trace a number",
        "Read the SLA definition and eligible/excluded counts, then select Review excluded records.",
        "Excluded records explain what the percentage cannot tell you.", "demo_sla_attainment", "Evidence",
        "Next step buttons in Calculation Inspector",
        "Excluded-record evidence selected. Next, examine what the source cannot tell you."),
    "limits": Mission("Calculation Inspector", "Find what is unavailable",
        "Read why Historical events is unavailable, then answer the question below the metric.",
        "The synthetic source contains incident snapshots, not an event history. Importing is a separate workflow.",
        "total_event_count", "Source limits", "Question below the unavailable metric",
        "Source limitation identified. Next, check the quality of the underlying records."),
    "scenario": Mission("Calculation Inspector", "Try a cost scenario",
        "Choose USD, enter 1,000 as operational cost, and enter a manual count of 10 incidents. If already filled, change an input and restore it.",
        "These example inputs are hypothetical; the app does not verify the cost or establish actual savings.",
        "cost_per_incident", "Scenarios", "Scenario inputs in Calculation Inspector",
        "Hypothetical cost calculated. Next, compare processing time using separate assumptions."),
    "time": Mission("Calculation Inspector", "Compare processing time",
        "Enter 10 baseline hours and 6 observed hours. If already filled, change an input and restore it.",
        "Hours saved and percentage reduction describe the same matched process; neither proves realized savings.",
        "time_saved_hours", "Scenarios", "Scenario inputs in Calculation Inspector",
        "Time comparison calculated. The result is a scenario, not proof of realized savings."),
    "queue": Mission("Incident queue", "Practice a handover",
        "Scroll past the queue table to Take a closer look. Select an incident, choose an owner and a review state other than Unreviewed, write a handover note, then select Save review.",
        "This saves a real change to your synthetic workspace, not to source facts or an imported CSV.",
        layer="Action", location="Take a closer look, below the queue table",
        success="Handover saved in your synthetic workspace. The team can now see who owns the next action."),
    "decision": Mission("Decision Support", "Investigate a pattern",
        "Use the supplied review timestamp and thresholds, then select Evaluate investigation rules.",
        "Rule matches are prompts to investigate, not automatic decisions or contractual SLA rules.",
        layer="Decision", location="Investigation rules form in Decision Support",
        success="Investigation rules evaluated. Use their evidence to inform a human decision."),
    "quality": Mission("Data quality", "Check the evidence",
        "Compare loaded, duplicate, and invalid rows, then answer the row-balance question below the metrics.",
        "Source-row outcomes and missing fields have different denominators. If no run exists, skip this mission.",
        layer="Quality", location="Row-balance question below the quality metrics",
        success="Row balance understood. This helps establish whether the source is fit for analysis."),
    "risk": Mission("Risk lab", "Explore a risk estimate",
        "Change Priority in Score an incident, compare the estimate, and explore Model evidence. If the model is not prepared, skip this mission.",
        "Synthetic model scores are relative estimates, not calibrated real-world odds or imported-source predictions.",
        layer="Prediction", location="Priority selector in Score an incident",
        success="A new synthetic risk estimate and its explanation were calculated."),
    "governance": Mission("Settings & Governance", "Understand the boundaries",
        "Read the access and prediction boundaries, then answer the question below.",
        "Personas are simulated; locally shared imports are not protected by production authentication.",
        layer="Governance", location="Access and prediction question in Settings & Governance",
        success="The access and prediction boundaries are clear. You can make a better-informed decision."),
}
ROLE_FIRST = {"Analyst": "queue", "Manager": "overview", "Admin": "quality"}
ROLE_JOURNEYS = {
    "Analyst": ("queue", "overview", "inspector", "limits", "quality",
                "risk", "decision", "scenario", "time", "governance"),
    "Manager": ("overview", "inspector", "limits", "quality", "risk",
                "decision", "queue", "scenario", "time", "governance"),
    "Admin": ("quality", "queue", "overview", "inspector", "limits",
              "risk", "decision", "scenario", "time", "governance"),
}
ROLE_CONTEXT = {
    "Analyst": "As the service desk analyst, you investigate open work and coordinate a clear handover.",
    "Manager": "As the operations manager, you assess service performance and decide what needs investigation.",
    "Admin": "As the data administrator, you check that the source and its evidence are trustworthy.",
}
LIMIT_ANSWER = "The demo contains incident snapshots, not an event history"
QUALITY_ANSWER = "Loaded, duplicate, and invalid source rows"
GOVERNANCE_ANSWER = "Personas are simulated and imports are shared locally"
TARGETS = {
    "orientation": '[class*="st-key-page"]',
    "overview": '[class*="st-key-inspect_overview_demo_sla_attainment"]',
    "inspector": '[class*="st-key-inspector_action_excluded"]',
    "limits": '[class*="st-key-tutorial_answer_limits"]',
    "scenario": ('[class*="st-key-currency_cost_per_incident"], '
                 '[class*="st-key-scenario_cost_per_incident_operational_cost"], '
                 '[class*="st-key-count_basis_cost_per_incident_"], '
                 '[class*="st-key-scenario_cost_per_incident_incident_count"]'),
    "time": ('[class*="st-key-scenario_time_saved_hours_baseline_hours"], '
             '[class*="st-key-scenario_time_saved_hours_observed_hours"]'),
    "queue": '[data-testid="stForm"]:has([class*="st-key-review_owner_"])',
    "decision": '[data-testid="stForm"]:has([class*="st-key-decision_as_of"])',
    "quality": '[class*="st-key-tutorial_answer_quality"]',
    "risk": '[class*="st-key-score_priority"]',
    "governance": '[class*="st-key-tutorial_answer_governance"]',
}


def start(role):
    order = ["orientation", *ROLE_JOURNEYS[role]]
    st.session_state.pop("tutorial_queue_feedback", None)
    st.session_state["tutorial"] = {"role": role, "order": order, "index": 0,
                                    "completed": [], "skipped": [], "paused": False, "last": None,
                                    "verified": False, "prepared": [], "scenario_touched": False,
                                    "time_touched": False, "risk_touched": False, "pending": None}
    open_mission()
    st.session_state["page"] = "Overview"


def navigation_observed():
    if is_current("orientation"):
        observe("orientation")


def open_mission():
    state = st.session_state["tutorial"]
    key = state["order"][state["index"]]
    state["pending"] = None
    st.session_state.pop("tutorial_queue_feedback", None)
    mission = MISSIONS[key]
    if key not in state["prepared"]:
        state["prepared"].append(key)
        if key in {"limits", "quality", "governance"}:
            st.session_state.pop(f"tutorial_answer_{key}", None)
    st.session_state.pop("pending_dataset", None)
    st.session_state["analytical_source"] = "demo"
    st.session_state["page"] = mission.page
    if mission.metric:
        st.session_state["inspector_metric"] = mission.metric
        st.session_state.pop("inspector_search", None)


def advance(skipped=False):
    state = st.session_state["tutorial"]
    if not skipped and not state["verified"]:
        return
    key = state["order"][state["index"]]
    for collection in (state["completed"], state["skipped"]):
        if key in collection:
            collection.remove(key)
    state["skipped" if skipped else "completed"].append(key)
    state["last"] = (key, skipped)
    state["verified"] = False
    state["index"] += 1
    if state["index"] < len(state["order"]):
        state["verified"] = state["order"][state["index"]] in state["completed"]
        open_mission()


def back():
    state = st.session_state["tutorial"]
    if (state["index"] > 0 and not state["paused"]
            and st.session_state.get("analytical_source") == "demo"
            and st.session_state.get("page") != "Import Desk"
            and st.session_state.get("persona_role") == state["role"]):
        state["index"] -= 1
        state["verified"] = state["order"][state["index"]] in state["completed"]
        state["last"] = None
        open_mission()


def exit_tutorial():
    st.session_state.pop("tutorial", None)


def set_paused(value):
    st.session_state["tutorial"]["paused"] = value
    if not value:
        open_mission()


def active(role, source, page):
    state = st.session_state.get("tutorial")
    return bool(state and "completed" in state and not state["paused"] and state["role"] == role and source == "demo"
                and page != "Import Desk" and state["index"] < len(state["order"]))


def is_current(key):
    state = st.session_state.get("tutorial")
    return bool(state and active(st.session_state.get("persona_role"),
                                st.session_state.get("analytical_source"), st.session_state.get("page"))
                and state["order"][state["index"]] == key
                and st.session_state.get("page") == MISSIONS[key].page)


def observe(key):
    if not is_current(key) or st.session_state["tutorial"]["verified"]:
        return False
    st.session_state["tutorial"]["verified"] = True
    return True


def inspection_requested(key):
    if is_current(key):
        st.session_state["tutorial"]["pending"] = key


def inspection_loaded(metric, result, records):
    state = st.session_state.get("tutorial", {})
    if (not active(st.session_state.get("persona_role"), st.session_state.get("analytical_source"),
                   st.session_state.get("page"))
            or metric != "demo_sla_attainment" or result.get("status") != "available"
            or st.session_state.get("page") != "Calculation Inspector"):
        return False
    key = state["order"][state["index"]]
    if (state.get("pending") == key and
            (key == "overview" or (key == "inspector" and not records.empty
                                    and st.session_state.get("inspector_evidence") == "Excluded"))):
        state["pending"] = None
        state["verified"] = True
        return True
    return False


def scenario_changed():
    if is_current("scenario") and st.session_state.get("inspector_metric") == "cost_per_incident":
        st.session_state["tutorial"]["scenario_touched"] = True
    elif is_current("time") and st.session_state.get("inspector_metric") == "time_saved_hours":
        st.session_state["tutorial"]["time_touched"] = True


def risk_changed():
    if is_current("risk"):
        st.session_state["tutorial"]["risk_touched"] = True


def risk_scored():
    state = st.session_state.get("tutorial", {})
    if state.get("risk_touched") and observe("risk"):
        state["risk_touched"] = False
        return True
    return False


def remaining(key):
    state = st.session_state
    if key == "scenario":
        missing = []
        if state.get("currency_cost_per_incident") != "USD":
            missing.append("select USD")
        if state.get("scenario_cost_per_incident_operational_cost") != 1000:
            missing.append("enter 1,000 for operational cost")
        basis = next((value for name, value in state.items()
                      if name.startswith("count_basis_cost_per_incident_")), None)
        if basis != "Cost covers a different set of incidents (enter the count)":
            missing.append("choose the manual incident count option")
        elif state.get("scenario_cost_per_incident_incident_count") != 10:
            missing.append("enter 10 incidents")
        if not missing:
            missing.append("change an input and restore it to calculate the example")
        return missing
    if key == "time":
        missing = []
        if state.get("scenario_time_saved_hours_baseline_hours") != 10:
            missing.append("enter 10 baseline hours")
        if state.get("scenario_time_saved_hours_observed_hours") != 6:
            missing.append("enter 6 observed hours")
        if not missing:
            missing.append("change an input and restore it to calculate the example")
        return missing
    return []


def answer(key, expected):
    if st.session_state.get(f"tutorial_answer_{key}") == expected:
        observe(key)


def question(key, label, options, expected):
    if not is_current(key):
        return
    st.radio(label, options, index=None, key=f"tutorial_answer_{key}",
             on_change=answer, args=(key, expected))
    selected = st.session_state.get(f"tutorial_answer_{key}")
    if selected and selected != expected:
        st.warning("Not quite. Review the evidence above and try again.")


def sidebar(role, source):
    state = st.session_state.get("tutorial")
    st.markdown("**Guided demo missions**")
    if not state:
        st.caption("Practice with synthetic data. Starting switches the analysis source to the demo.")
        st.button("Start guided demo", key="tutorial_start", on_click=start, args=(role,), width="stretch")
        return
    if "completed" not in state:
        st.caption("The guide was updated. Restart to use verified missions; saved demo reviews are unchanged.")
        st.button("Restart guided demo", key="tutorial_restart", on_click=start, args=(role,), width="stretch")
        return
    if state["role"] != role:
        st.caption(f"The {state['role']} tour is paused while you use another persona.")
        st.button("Start tour for this persona", key="tutorial_restart_role", on_click=start,
                  args=(role,), width="stretch")
        return
    total, index = len(state["order"]), state["index"]
    st.progress(index / total, text=f"Mission progress: {index} of {total}")
    if state["last"]:
        key, skipped = state["last"]
        st.caption(f"{'Skipped' if skipped else 'Checkpoint verified'}: {MISSIONS[key].title}.")
    can_go_back = not state["paused"] and source == "demo" and st.session_state["page"] != "Import Desk"
    if index == total:
        st.success(f"Tour finished: {len(state['completed'])} verified, {len(state['skipped'])} skipped.")
    else:
        mission = MISSIONS[state["order"][index]]
        st.markdown(f"**Current: {mission.title}**")
        if state["paused"] or source != "demo" or st.session_state["page"] == "Import Desk":
            st.caption("Tour paused. Your imported source is unchanged until you choose to return to the synthetic demo.")
            st.button("Resume on synthetic demo", key="tutorial_resume", on_click=set_paused,
                      args=(False,), width="stretch")
        else:
            if st.session_state["page"] != mission.page and not state["verified"] and state["order"][index] != "orientation":
                st.caption(f"You're on {st.session_state['page']}; this mission is on {mission.page}.")
                st.button("Go to mission", key="tutorial_go", on_click=open_mission, width="stretch")
            if state["verified"]:
                st.success("Action detected. Continue when you're ready.")
            else:
                st.caption(f"Next locked — {mission.task} Location: {mission.location}.")
            st.button("Continue to next mission", key="tutorial_next", on_click=advance,
                      disabled=not state["verified"], type="primary" if state["verified"] else "secondary", width="stretch")
            st.button("Skip mission", key="tutorial_skip", on_click=advance, kwargs={"skipped": True},
                      width="stretch")
            st.button("Pause guided demo", key="tutorial_pause", on_click=set_paused, args=(True,), width="stretch")
    st.button("Previous mission", key="tutorial_back", on_click=back,
              disabled=index == 0 or not can_go_back, width="stretch")
    st.button("Restart on synthetic demo", key="tutorial_restart", on_click=start, args=(role,), width="stretch")
    st.button("Exit guided demo", key="tutorial_exit", on_click=exit_tutorial, width="stretch")
    st.caption("Progress lasts for this browser session; saved demo reviews remain in the workspace.")


def highlight(key):
    state = st.session_state.get("tutorial")
    if not state or not active(st.session_state.get("persona_role"), st.session_state.get("analytical_source"),
                               st.session_state.get("page")):
        return
    current = state["order"][state["index"]]
    if current == key:
        mission = MISSIONS[key]
        if (is_current(key) or key == "orientation") and not state["verified"]:
            st.html(f"<style>{TARGETS[key]} {{ outline:3px solid #d8401b; "
                    "outline-offset:4px; border-radius:6px; } "
                    '[data-testid="stMain"] [data-testid="stPlotlyChart"], '
                    '[data-testid="stMain"] [data-testid="stDataFrame"] { opacity:.82; } '
                    '[data-testid="stMain"] [data-testid="stPlotlyChart"]:hover, '
                    '[data-testid="stMain"] [data-testid="stPlotlyChart"]:focus-within, '
                    '[data-testid="stMain"] [data-testid="stDataFrame"]:hover, '
                    '[data-testid="stMain"] [data-testid="stDataFrame"]:focus-within { opacity:1; } '
                    '@media (prefers-contrast: more) { [data-testid="stMain"] '
                    '[data-testid="stPlotlyChart"], [data-testid="stMain"] '
                    '[data-testid="stDataFrame"] { opacity:1; } }</style>')
        with st.container(key="tutorial_focus", border=True):
            st.caption(f"GUIDED DEMO · STEP {state['index'] + 1} OF {len(state['order'])} · "
                       f"{len(state['completed'])} VERIFIED · {len(state['skipped'])} SKIPPED · "
                       f"{mission.layer.upper()} · SYNTHETIC DATA")
            st.subheader(mission.title)
            if key == "orientation":
                st.write(ROLE_CONTEXT[state["role"]])
                st.write("Explore open incidents, evidence, risk and decisions, then practice a handover. "
                         "The guide uses synthetic data; your imported records are not changed.")
            st.markdown(f"**Your next action:** {mission.task}")
            st.info(f"**Key moment:** {mission.insight}")
            if state["verified"]:
                next_title = (MISSIONS[state["order"][state["index"] + 1]].title
                              if state["index"] + 1 < len(state["order"]) else "Finish the tour")
                st.success(f"Action verified. {mission.success} Next: {next_title}.")
                st.button("Continue to next mission", key="tutorial_continue_focus",
                          on_click=advance, type="primary")
            elif key == "orientation":
                st.write("**Next is locked:** the queue has not been opened yet. Open it to see the work you will investigate.")
                if st.session_state["page"] != "Overview":
                    st.warning(f"You opened {st.session_state['page']}. To begin, open Incident queue.")
                st.button("Open Incident queue to begin", key="tutorial_begin_queue",
                          on_click=open_mission, type="primary")
            elif st.session_state["page"] != mission.page:
                st.warning(f"You are on {st.session_state['page']}. Return to {mission.page} to complete this action.")
                st.button(f"Go to {mission.page}", key="tutorial_go_focus", on_click=open_mission, type="primary")
            else:
                st.write(f"**Next is locked:** action not detected yet. Find it at: {mission.location}.")
                if missing := remaining(key):
                    st.write("**Still needed:** " + "; ".join(missing) + ".")
                if key == "queue":
                    st.write("1. Scroll to **Take a closer look** and select an incident.\n"
                             "2. Choose a mock **Owner** and set **Review state** to **In review**.\n"
                             "3. Write a **Handover note**, then select **Save review**.\n\n"
                             "The form sends these choices together when you save.")
                st.caption("After the action succeeds, return here or use the sidebar to continue. "
                           "If the required data or control is unavailable, open the sidebar "
                           "(top left on small screens) and select Skip mission.")


def focus():
    state = st.session_state.get("tutorial")
    if state and state["index"] < len(state["order"]):
        highlight(state["order"][state["index"]])
    elif (state and "completed" in state and not state["paused"]
          and state["role"] == st.session_state.get("persona_role")
          and st.session_state.get("analytical_source") == "demo"
          and st.session_state.get("page") != "Import Desk"):
        with st.container(key="tutorial_focus", border=True):
            st.subheader("Your guided journey is complete")
            st.success(f"{len(state['completed'])} checkpoints verified; {len(state['skipped'])} skipped.")
            st.write("You explored the evidence behind operational decisions. "
                     "Review the results below or continue working in the synthetic workspace.")
            with st.expander("Review your journey"):
                for key in state["order"]:
                    status = "Verified" if key in state["completed"] else "Skipped"
                    st.write(f"**{status}:** {MISSIONS[key].title}")
