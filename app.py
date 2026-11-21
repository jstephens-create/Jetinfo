"""SIGNAL - AI Incident Intelligence Lab (Streamlit dashboard).

Read-only view over the SQLite database and the trained model.
Run:  streamlit run app.py
"""
import json

import joblib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import database
from src.config import (CATEGORIES, DB_PATH, METRICS_PATH, MODEL_PATH, PRIORITIES, RISK_BANDS,
                        risk_level)
from src.train_model import explain, predict

ORANGE = "#FF4F00"
SLATE = "#7C8DA6"      # "lowers risk" pole of the diverging coefficient chart
INK = "#ECECEC"
MUTED = "#9A9AA2"
GRID = "#2E2E33"
SURFACE = "#242428"
RISK_COLORS = {"Low": "#3FB37F", "Medium": "#F2B233", "High": ORANGE}

st.set_page_config(page_title="SIGNAL · Incident Intelligence", page_icon="📡", layout="wide")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stText {{ font-family: 'Inter', sans-serif; }}
.stApp {{ background: #1A1A1D; }}
.block-container, [data-testid="stMainBlockContainer"] {{ padding-top: 4rem; max-width: 1300px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.brand {{ font-size: 2rem; font-weight: 700; letter-spacing: .18em; color: {INK}; margin: 0; }}
.brand span {{ color: {ORANGE}; }}
.tagline {{ color: {MUTED}; margin: .1rem 0 1.4rem 0; font-size: .95rem; }}
.kpi {{ background: {SURFACE}; border: 1px solid #34343A; border-radius: 14px;
        padding: 1.1rem 1.25rem; height: 100%; }}
.kpi .label {{ color: {MUTED}; font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }}
.kpi .value {{ color: {INK}; font-size: 2rem; font-weight: 700; margin-top: .25rem; }}
.kpi .sub {{ color: {MUTED}; font-size: .8rem; }}
.kpi.accent {{ border-left: 3px solid {ORANGE}; }}
.note {{ background: rgba(255,79,0,.07); border: 1px solid rgba(255,79,0,.35); border-radius: 10px;
         padding: .7rem 1rem; color: {INK}; font-size: .88rem; }}
.pill {{ display:inline-block; padding: .15rem .65rem; border-radius: 999px; font-weight: 600;
         font-size: .85rem; border: 1px solid currentColor; }}
.stTabs [data-baseweb="tab-list"] {{ gap: .5rem; border-bottom: 1px solid #34343A; }}
.stTabs [data-baseweb="tab"] {{ padding: .6rem 1rem; }}
div[data-testid="stDataFrame"] {{ border: 1px solid #34343A; border-radius: 10px; }}
h3 {{ font-weight: 600 !important; }}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def kpi(label, value, sub="", accent=False):
    st.markdown(f'<div class="kpi {"accent" if accent else ""}"><div class="label">{label}</div>'
                f'<div class="value">{value}</div><div class="sub">{sub}</div></div>',
                unsafe_allow_html=True)


def pill(level):
    return f'<span class="pill" style="color:{RISK_COLORS[level]}">● {level} risk</span>'


def style(fig, height=320):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, sans-serif", color=INK, size=13), height=height,
                      margin=dict(l=10, r=10, t=40, b=10), title_font=dict(size=15),
                      hoverlabel=dict(bgcolor=SURFACE, bordercolor="#44444A"))
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def bar(df, x, y, title, fmt="%{x}", horizontal=True):
    fig = px.bar(df, x=x, y=y, orientation="h" if horizontal else "v", title=title, text_auto=False)
    fig.update_traces(marker_color=ORANGE, marker_line_width=0, hovertemplate=fmt + "<extra></extra>")
    fig.update_layout(bargap=0.35, yaxis_title=None, xaxis_title=None)
    return style(fig)


@st.cache_data(ttl=60)
def load_data():
    return (database.read_incidents(), database.kpi_summary(), database.run_history())


@st.cache_resource
def load_model():
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


# ------------------------------------------------------------------ guard
st.markdown('<div class="brand">SIGN<span>A</span>L</div>'
            '<p class="tagline">AI incident intelligence · synthetic ITSM data · SLA breach risk estimates</p>',
            unsafe_allow_html=True)

if not DB_PATH.exists():
    st.error("No database found. Run the pipeline first:")
    st.code("python -m src.generate_data\npython -m src.etl\npython -m src.train_model")
    st.stop()

incidents, kpis, runs = load_data()
model = load_model()
metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else None

tab_overview, tab_explorer, tab_ai, tab_quality = st.tabs(
    ["Overview", "Incident Explorer", "AI Predictions", "Data Quality"])

# ================================================================== A. OVERVIEW
with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Total incidents", f"{int(kpis['total_incidents']):,}", f"{int(kpis['open_incidents'])} still open")
    with c2:
        kpi("SLA compliance", f"{kpis['sla_compliance_pct']:.1f}%", "of resolved incidents", accent=True)
    with c3:
        kpi("Avg resolution", f"{kpis['avg_resolution_hours']:.1f} h", "resolved incidents")
    with c4:
        kpi("High priority", f"{int(kpis['high_priority_incidents'])}", "Critical + High")

    st.write("")
    left, right = st.columns(2)
    by_priority = database.sla_by_dimension("priority")
    by_priority["order"] = by_priority["dimension"].map(PRIORITIES.index)
    left.plotly_chart(bar(by_priority.sort_values("order", ascending=False), "compliance_pct", "dimension",
                          "SLA compliance by priority (%)", "%{y}: %{x:.1f}% compliant"),
                      use_container_width=True)
    right.plotly_chart(bar(database.sla_by_dimension("category"), "compliance_pct", "dimension",
                           "SLA compliance by category (%)", "%{y}: %{x:.1f}% compliant"),
                       use_container_width=True)

    left, right = st.columns(2)
    trend = database.monthly_trend()
    fig = px.line(trend, x="month", y="compliance_pct", markers=True, title="Monthly SLA compliance (%)")
    fig.update_traces(line=dict(color=ORANGE, width=2), marker=dict(size=8),
                      hovertemplate="%{x}: %{y:.1f}%<extra></extra>")
    fig.update_layout(xaxis_title=None, yaxis_title=None, hovermode="x unified", xaxis_type="category")
    left.plotly_chart(style(fig), use_container_width=True)
    groups = database.sla_by_dimension("assignment_group")
    right.plotly_chart(bar(groups.sort_values("avg_resolution_hours"), "avg_resolution_hours", "dimension",
                           "Average resolution time by team (hours)", "%{y}: %{x:.1f} h"),
                       use_container_width=True)
    st.caption("All metrics above are computed with SQL queries in `src/database.py`. "
               "Compliance excludes open incidents, whose outcome is not yet known.")

# ================================================================== B. EXPLORER
with tab_explorer:
    f1, f2, f3 = st.columns([2, 1.3, 1.3])
    search = f1.text_input("Search", placeholder="Incident ID, service or team…")
    pr = f2.multiselect("Priority", PRIORITIES, default=PRIORITIES)
    cat = f3.multiselect("Category", CATEGORIES, default=CATEGORIES)

    view = incidents[incidents["priority"].isin(pr) & incidents["category"].isin(cat)]
    if search:
        s = search.lower()
        view = view[view[["incident_id", "affected_service", "assignment_group"]]
                    .apply(lambda col: col.str.lower().str.contains(s, regex=False)).any(axis=1)]

    st.caption(f"{len(view)} of {len(incidents)} incidents")
    table = view[["incident_id", "created_at", "priority", "category", "affected_service",
                  "assignment_group", "status", "resolution_time_minutes", "sla_target_minutes",
                  "sla_breached", "breach_probability"]].copy()
    table["breach_probability"] = (table["breach_probability"] * 100).round(1)
    table["sla_breached"] = table["sla_breached"].map({1: "Breached", 0: "Met"}).fillna("Pending")
    st.dataframe(table.sort_values("created_at", ascending=False), hide_index=True, height=380,
                 use_container_width=True,
                 column_config={
                     "breach_probability": st.column_config.ProgressColumn(
                         "Est. breach risk", format="%.0f%%", min_value=0, max_value=100, width="medium"),
                     "resolution_time_minutes": st.column_config.NumberColumn("Resolution (min)", format="%.0f"),
                     "sla_target_minutes": st.column_config.NumberColumn("SLA target (min)"),
                 })

    if len(view):
        st.markdown("### Incident details")
        chosen = st.selectbox("Select an incident", view.sort_values("created_at", ascending=False)["incident_id"])
        inc = incidents[incidents["incident_id"] == chosen].iloc[0]
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            kpi("Priority", inc["priority"], inc["category"])
        with d2:
            kpi("Service", inc["affected_service"], inc["assignment_group"])
        with d3:
            outcome = "Pending" if pd.isna(inc["sla_breached"]) else ("Breached" if inc["sla_breached"] else "Met")
            margin = "" if pd.isna(inc["sla_margin_minutes"]) else f"{inc['sla_margin_minutes']:+.0f} min vs target"
            kpi("SLA outcome", outcome, margin)
        with d4:
            if pd.notna(inc["breach_probability"]):
                kpi("Estimated risk", f"{inc['breach_probability']:.0%}", inc["risk_level"] + " (model estimate)",
                    accent=True)
        st.caption(f"Created {inc['created_at']} · status {inc['status']} · first response "
                   f"{inc['response_time_minutes']:.0f} min · SLA target {inc['sla_target_minutes']} min")

# ================================================================== C. AI PREDICTIONS
with tab_ai:
    if model is None or metrics is None:
        st.warning("No trained model yet. Run `python -m src.train_model`.")
    else:
        st.markdown('<div class="note"><b>How to read this:</b> scores are <b>estimates</b> of breach '
                    'likelihood learned from past incidents, using only information available when a '
                    'ticket is created. They are not guarantees, and the model was trained with balanced '
                    'class weights, so treat scores as <b>relative risk</b> for triage rather than exact odds.'
                    '</div>', unsafe_allow_html=True)
        st.write("")

        # --- open incidents ranked by risk: the operational payoff
        open_inc = incidents[incidents["sla_breached"].isna()].sort_values("breach_probability", ascending=False)
        st.markdown(f"### Open incidents ranked by estimated breach risk ({len(open_inc)})")
        open_view = open_inc[["incident_id", "created_at", "priority", "category", "affected_service",
                              "assignment_group", "status", "breach_probability", "risk_level"]].copy()
        open_view["breach_probability"] = (open_view["breach_probability"] * 100).round(1)
        st.dataframe(open_view,
                     hide_index=True, use_container_width=True, height=260,
                     column_config={"breach_probability": st.column_config.ProgressColumn(
                         "Est. breach risk", format="%.0f%%", min_value=0, max_value=100, width="medium"),
                         "risk_level": "Risk band"})
        bands = " · ".join(f"{label}: {lo:.0%}–{min(hi, 1):.0%}" for lo, hi, label in RISK_BANDS)
        st.caption(f"Risk bands: {bands}")

        # --- what-if scorer + explanation
        st.markdown("### Score a new incident")
        w1, w2, w3 = st.columns(3)
        w_priority = w1.selectbox("Priority", PRIORITIES, index=1)
        w_category = w1.selectbox("Category", CATEGORIES)
        w_service = w2.selectbox("Affected service", sorted(incidents["affected_service"].unique()))
        w_group = w2.selectbox("Assignment group", sorted(incidents["assignment_group"].unique()))
        w_date = w3.date_input("Created on", pd.Timestamp("2024-07-01"))
        w_hour = w3.slider("Created at hour", 0, 23, 10)
        new = pd.DataFrame([{"priority": w_priority, "category": w_category, "affected_service": w_service,
                             "assignment_group": w_group,
                             "created_at": f"{w_date} {w_hour:02d}:00:00"}])
        p = float(predict(model, new)[0])
        r1, r2 = st.columns([1, 2])
        with r1:
            kpi("Estimated breach probability", f"{p:.0%}", "model estimate, not a guarantee", accent=True)
            st.markdown(pill(risk_level(p)), unsafe_allow_html=True)
        with r2:
            contrib = explain(model, new).head(8).iloc[::-1]
            fig = go.Figure(go.Bar(
                x=contrib["contribution"], y=contrib["feature"], orientation="h",
                marker_color=[ORANGE if v > 0 else SLATE for v in contrib["contribution"]],
                hovertemplate="%{y}: %{x:+.2f} log-odds<extra></extra>"))
            fig.update_layout(title="What pushed this estimate up (orange) or down (slate)", bargap=0.35)
            st.plotly_chart(style(fig, 300), use_container_width=True)

        # --- model performance
        st.markdown("### Model performance (chronological hold-out test set)")
        sp = metrics["split"]
        st.caption(f"Trained on {sp['train_rows']} incidents ({sp['train_start'][:10]} → {sp['train_end'][:10]}), "
                   f"tested on the next {sp['test_rows']} ({sp['test_start'][:10]} → {sp['test_end'][:10]}). "
                   f"Test breach rate {sp['test_breach_rate']:.0%}.")
        rows = []
        for key, name in [("model", "Logistic Regression"), ("baseline_priority_rate", "Baseline: priority rule"),
                          ("baseline_majority_class", "Baseline: always 'no breach'")]:
            m = metrics[key]
            rows.append({"Model": name, "Precision": m["precision"], "Recall": m["recall"], "F1": m["f1"],
                         "ROC-AUC": m["roc_auc"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        m1, m2 = st.columns(2)
        cm = metrics["model"]["confusion_matrix"]
        z = [[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]]
        fig = go.Figure(go.Heatmap(z=z, x=["Predicted: met", "Predicted: breach"],
                                   y=["Actual: met", "Actual: breach"], text=z, texttemplate="%{text}",
                                   colorscale=[[0, "#2A2A2F"], [1, ORANGE]], showscale=False, xgap=2, ygap=2,
                                   hovertemplate="%{y} · %{x}: %{z}<extra></extra>"))
        fig.update_layout(title="Confusion matrix", yaxis_autorange="reversed")
        m1.plotly_chart(style(fig), use_container_width=True)

        roc = metrics["roc_curve"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Random guess",
                                 line=dict(color=MUTED, dash="dash", width=1)))
        fig.add_trace(go.Scatter(x=roc["fpr"], y=roc["tpr"], mode="lines", name="Model",
                                 line=dict(color=ORANGE, width=2),
                                 hovertemplate="FPR %{x:.2f} · TPR %{y:.2f}<extra></extra>"))
        fig.update_layout(title=f"ROC curve (AUC {metrics['model']['roc_auc']:.2f})", xaxis_title="False positive rate",
                          yaxis_title="True positive rate", legend=dict(x=.55, y=.1))
        m2.plotly_chart(style(fig), use_container_width=True)

        # --- coefficients
        st.markdown("### What the model learned (coefficients)")
        coefs = pd.DataFrame(metrics["coefficients"])
        top = pd.concat([coefs.head(8), coefs.tail(8)]).drop_duplicates().sort_values("coefficient")
        fig = go.Figure(go.Bar(x=top["coefficient"], y=top["feature"], orientation="h",
                               marker_color=[ORANGE if v > 0 else SLATE for v in top["coefficient"]],
                               customdata=top["odds_multiplier"],
                               hovertemplate="%{y}<br>coefficient %{x:+.2f} · odds ×%{customdata}<extra></extra>"))
        fig.update_layout(bargap=0.35)
        st.plotly_chart(style(fig, 480), use_container_width=True)
        st.markdown('<div class="note">Coefficients show <b>association, not causation</b>. A positive weight '
                    'on "is_weekend" means weekend tickets breached more often in this history — not that the '
                    'weekend itself causes breaches (staffing levels could be the real driver). Weights for '
                    'related features (e.g. category and its usual team) also share credit, so read them '
                    'together.</div>', unsafe_allow_html=True)

# ================================================================== D. DATA QUALITY
with tab_quality:
    latest = runs.iloc[0]
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        kpi("Rows read", int(latest["rows_read"]), f"run #{int(latest['run_id'])}")
    with q2:
        kpi("Rows loaded", int(latest["rows_loaded"]), f"{int(latest['new_incidents'])} new this run", accent=True)
    with q3:
        kpi("Rows rejected", int(latest["rows_rejected"]), "see reasons below")
    with q4:
        kpi("Duplicates removed", int(latest["duplicates_removed"]), "same incident_id twice")

    st.write("")
    left, right = st.columns(2)
    missing = pd.Series(json.loads(latest["missing_values"])).rename("missing").reset_index()
    missing.columns = ["column", "missing"]
    left.plotly_chart(bar(missing.sort_values("missing"), "missing", "column",
                          "Missing values in raw file", "%{y}: %{x} missing"), use_container_width=True)
    left.caption("resolution_time and sla_breached are blank for open incidents by design — not an error.")

    rejected = database.rejected_for_run(int(latest["run_id"]))
    reasons = (rejected["reason"].str.split("; ").explode().value_counts()
               .rename_axis("reason").reset_index(name="rows"))
    right.plotly_chart(bar(reasons.sort_values("rows"), "rows", "reason",
                           "Validation failures", "%{y}: %{x} rows"), use_container_width=True)

    st.markdown("### Rejected records (latest run)")
    st.dataframe(rejected, hide_index=True, use_container_width=True, height=260)

    st.markdown("### Pipeline execution history")
    st.dataframe(runs.drop(columns=["missing_values"]), hide_index=True, use_container_width=True)
    st.caption("Rerunning the pipeline upserts by incident_id, so 'new_incidents' drops to 0 on a rerun "
               "of the same file — proof the load is idempotent.")
