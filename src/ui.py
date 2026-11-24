"""Presentation helpers for OKai's editorial, reference-inspired interface."""
import json
import sys
from base64 import b64encode
from contextlib import contextmanager
from html import escape
from pathlib import Path
from urllib.parse import urlencode

import plotly.express as px
import streamlit as st

from src import charts
from src.design import COLORS, GEOMETRY, FONT_FAMILY, SLOGAN

ORANGE, PURPLE, CYAN = COLORS["orange"], COLORS["purple"], COLORS["cyan"]
GREEN, INK, MUTED = COLORS["green"], COLORS["ink"], COLORS["muted"]
RISK_COLORS = {"Low": GREEN, "Medium": "#A16400", "High": "#D73A19"}
CONNECTOR_ART = b64encode((Path(__file__).resolve().parent.parent / "assets" / "connectors.svg").read_bytes()).decode("ascii")
WORDMARK_ART = b64encode((Path(__file__).resolve().parent.parent / "assets" / "okai-wordmark.svg").read_bytes()).decode("ascii")

def download_button(label, data, file_name, mime, **options):
    if sys.platform != "emscripten":
        return st.download_button(label, data, file_name, mime, **options)
    if options.get("disabled"):
        st.caption(label)
        return
    # The browser runtime has no Streamlit HTTP media endpoint.
    from streamlit.components.v1 import html
    payload = data.encode("utf-8") if isinstance(data, str) else data
    encoded = b64encode(payload).decode("ascii")
    html(
        '<style>body{margin:0}a{display:inline-block;font:600 15px system-ui;color:#171717;'
        'padding:6px 12px;border:1px solid #777;border-radius:6px;text-decoration:none}</style>'
        f'<a download="{escape(file_name)}" href="data:{escape(mime)};base64,{encoded}">'
        f'{escape(label)}</a>', height=40)


STYLES = """
<style>
:root { --paper: #f7f6f3; --ink: #171717; --orange: #ff512b; }
html, body, [data-testid="stApp"] { font-family: Arial, Helvetica, sans-serif; }
.stApp { background: var(--paper); color: var(--ink); }
[data-testid="stHtml"] { font-family: Arial, Helvetica, sans-serif; }
[data-testid="stHeader"] { background: rgba(247,246,243,.95); }
[data-testid="stToolbar"] { right: 1rem; }
/* Keep the wordmark below Streamlit's fixed top bar; otherwise the translucent
   bar washes out its upper edge and looks like a misplaced reflection. */
[data-testid="stMainBlockContainer"] { max-width: 1440px; padding: 4.5rem 2.8rem 3rem; }
[data-testid="stVerticalBlock"] { gap: 1rem; }
[data-testid="stSidebar"] { background: #eeede9; border-right: 1px solid #deddd7; }
[data-testid="stSidebarUserContent"] { padding-top: 2.5rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] p { font-size: .9rem; }
.okai-brand { display:inline-flex; align-items:flex-start; position:relative; min-width:116px;
    min-height:76px; padding:0 10px 0 4px; border-radius:10px; color:#161616 !important;
    text-decoration:none !important; transition:background .16s ease; }
.okai-brand:hover { background:#eeebe4; }
.okai-brand:focus-visible { outline:3px solid var(--orange); outline-offset:3px; }
.okai-wordmark-image { display:block; width:116px; height:76px; }
.okai-brand--sidebar { margin-left:-10px; }
.brand-caption, .eyebrow { color: #74716b; font: 600 .65rem/1.5 Arial, sans-serif;
    text-transform: uppercase; letter-spacing: .14em; }
.masthead { display: flex; justify-content: space-between; align-items: center; margin: 0 0 .8rem; }
.masthead-right { display:flex; align-items:center; gap:.8rem; font-size:.72rem; color:#726e67; }
.demo-tag { border:1px solid #ccc8bf; border-radius: 99px; padding:.28rem .62rem;
    font-size:.6rem; font-weight:700; letter-spacing:.13em; white-space:nowrap; }
.okai-hero { position:relative; overflow:hidden; background:#050505; color:white;
    border-radius:5px; min-height:265px; isolation:isolate; }
.hero-meta { position:absolute; top:22px; left:26px; right:26px; display:flex;
    justify-content:space-between; font-size:.59rem; letter-spacing:.15em; color:#aaa9a5; z-index:2; }
.connector-art { position:absolute; left:0; top:12px; width:100%; height:250px; object-fit:fill; }
.hero-type { position:relative; padding:68px 35px 82px 28%; z-index:1; }
.hero-title { font-size:clamp(46px,5.3vw,80px); letter-spacing:-.075em;
    line-height:1.02; font-weight:800; color:#ffa4ad; margin:0 0 16px; }
.hero-subtitle { color:#c0bfbc; font-size:.88rem; line-height:1.65; max-width:470px; margin:0; }
.hero-ribbon { background:var(--orange); color:#131313; position:absolute; bottom:24px;
    left:0; width:100%; display:flex; justify-content:space-around; align-items:center;
    padding:9px 12px; gap:20px; font-size:.58rem; font-weight:700; letter-spacing:.1em; }
.hero-ribbon strong { font-size:1.1rem; letter-spacing:-.06em; font-style:italic; }
.okai-hero.compact { min-height:233px; }
.compact .hero-type { padding-top:56px; padding-bottom:75px; }
.compact .hero-title { font-size:clamp(37px,4.1vw,61px); margin-bottom:10px; }
.compact .connector-art { top:13px; height:210px; }
.compact .hero-ribbon { bottom:17px; padding:6px 12px; }
.section-heading { margin: .7rem 0 .35rem; }
.section-heading h2 { color:#161616; font-weight:700; font-size:1.6rem;
    letter-spacing:-.055em; line-height:1.15; margin:5px 0 9px; }
.section-heading p { color:#77736b; font-size:.83rem; line-height:1.6; margin:0; }
.metric-card { background:#fff; border:1px solid #e1dfd8; border-radius:5px;
    padding:16px 20px 17px; height:180px; display:flex; flex-direction:column;
    border-top:8px solid var(--card-accent,#222); }
.metric-card--link { color:inherit !important; text-decoration:none !important; position:relative;
    transition:box-shadow .16s ease,border-color .16s ease; }
.metric-card--link:hover { box-shadow:0 4px 14px rgba(35,31,24,.10);
    border-right-color:#bdb6a8; border-bottom-color:#bdb6a8; border-left-color:#bdb6a8; }
.metric-card--link:focus-visible { outline:3px solid var(--card-accent,#222); outline-offset:4px; }
.metric-card--link .metric-label { padding-right:20px; }
.metric-card-arrow { position:absolute; top:15px; right:16px; color:#77736b; font-size:1rem; }
.metric-label { color:#77736c; text-transform:uppercase; font-size:.61rem;
    letter-spacing:.10em; line-height:1.4; min-height:42px; }
.metric-value { color:#181818; font-size:2.3rem; letter-spacing:-.065em; font-weight:700;
    line-height:1.2; margin:9px 0 4px; }
.metric-note { color:#8a857c; font-size:.70rem; line-height:1.4; margin-top:auto; }
.feature-card { border-top:1px solid #d7d3ca; padding:16px 4px 10px; }
.feature-card h3 { font-size:1.05rem; font-weight:700; letter-spacing:-.03em; margin:9px 0; }
.feature-card p { color:#7d786f; font-size:.81rem; line-height:1.6; margin:0; }
.feature-number { font-size:.65rem; font-weight:700; color:#e44820; }
.context-note { background:#ebe9e2; border-left:3px solid var(--orange); padding:13px 17px;
    font-size:.78rem; color:#666158; line-height:1.65; border-radius:0 4px 4px 0; }
[class*="st-key-tutorial_focus"] { border:1px solid #dfb9a9; border-left:5px solid #d8401b;
    background:#fffaf7; border-radius:8px; padding:24px;
    box-shadow:0 4px 16px rgba(35,31,24,.08); }
[class*="st-key-tutorial_focus"] h2, [class*="st-key-tutorial_focus"] h3 {
    font-size:1.45rem; line-height:1.25; }
[class*="st-key-tutorial_focus"] p { font-size:1rem; line-height:1.55; color:#24211f; }
[class*="st-key-tutorial_focus"] [data-testid="stCaptionContainer"] p {
    color:#594e47; font-size:.8rem; font-weight:600; }
/* Every chart_* container gets the same raised edge. The data stays flat and
   readable: the bevel belongs to the card, never to a bar's measured length. */
[class*="st-key-chart_"] { background:linear-gradient(150deg,#ffffff 0%,#faf9f6 100%);
    border:1px solid #d6d1c7; border-top-color:#fff; border-left-color:#fff;
    border-radius:12px; padding:20px 18px 16px;
    box-shadow:inset 1px 1px 0 #fff,inset -1px -2px 0 #e0dbd0,
               0 0 0 1px #d8d2c6,0 5px 12px rgba(47,40,27,.07); }
.chart-heading { min-height:92px; padding-bottom:12px; border-bottom:1px solid #e4dfd5; }
.chart-heading h3 { font-size:1.05rem; line-height:1.35; margin:7px 0 6px; font-weight:700; }
.chart-heading p { font-size:.74rem; line-height:1.55; color:#6b665e; margin:0; }
.chart-reading { min-height:65px; padding:12px 0 0; border-top:1px solid #e4dfd5;
    font-size:.73rem; line-height:1.6; color:#615c53; }
.chart-reading strong { color:#37342e; }
.chart-legend { display:flex; flex-wrap:wrap; gap:10px 20px; font-size:.7rem; color:#5f5a52; padding:4px 0; }
.chart-legend span { display:inline-flex; gap:7px; align-items:center; }
.chart-legend i { width:9px; height:9px; border-radius:2px; display:inline-block; }
.chart-empty { height:360px; display:flex; align-items:center; justify-content:center;
    padding:30px; text-align:center; font-size:.85rem; color:#5a655c; }
.quality-scope { display:flex; justify-content:space-between; gap:14px; padding:12px 15px;
    background:#eeece5; border:1px solid #ded8cc; border-radius:6px; margin:0 0 8px;
    color:#625b50; font-size:.72rem; line-height:1.6; }
.risk-pill { display:inline-flex; align-items:center; gap:6px; padding:5px 9px;
    border:1px solid currentColor; border-radius:99px; font-size:.65rem; font-weight:700; }
.risk-dot { width:5px; height:5px; border-radius:100%; background:currentColor; }
.persona { display:flex; align-items:center; gap:10px; margin:10px 0 18px; }
.avatar { width:34px; height:34px; border-radius:100%; display:grid; place-items:center;
    background:#24231f; color:#fff; font-size:.65rem; }
.persona-name { font-size:.8rem; font-weight:700; }
.persona-title { font-size:.63rem; color:#817b71; margin-top:3px; }
.timeline-item { padding:13px 0; border-bottom:1px solid #e5e1d8; }
.timeline-top { display:flex; justify-content:space-between; gap:12px; font-size:.68rem; color:#7d766b; }
.timeline-item p { font-size:.8rem; margin:6px 0 0; line-height:1.6; color:#48433b; }
.timeline-item strong { color:#222; }
.empty-state { background:#efede6; padding:24px; border-radius:5px; color:#827b70;
    font-size:.82rem; line-height:1.7; }
.project-footer { display:flex; justify-content:space-between; padding:22px 0 8px;
    border-top:1px solid #dbd7cd; margin-top:30px; color:#8a8377; font-size:.6rem;
    letter-spacing:.1em; text-transform:uppercase; }
.brand-name { text-transform:none; }
h1, h2, h3 { letter-spacing:-.04em !important; }
[data-testid="stCaptionContainer"] { font-size:.8rem; color:#625e56; }
[data-testid="stCaptionContainer"] p { font-size:.8rem; color:#625e56; line-height:1.55; }
[data-testid="stBaseButton-primary"] { background:var(--orange); color:#171717;
    border:1px solid var(--orange); font-weight:600; border-radius:4px; }
[data-testid="stBaseButton-primary"]:hover { background:#ed4721; color:#111; border-color:#ed4721; }
.stButton button, .stDownloadButton button { border-radius:4px; font-size:.8rem; }
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button { min-height:44px; }
[data-testid="stForm"] { border-color:#ddd8ce; border-radius:5px; background:#fff; padding:22px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:5px; }
[data-testid="stDataFrame"] { border:1px solid #ddd8cf; border-radius:5px; }
[data-baseweb="tab-list"] { gap:24px; border-bottom:1px solid #ddd7ca; }
[data-baseweb="tab"] { padding:10px 0; font-size:.8rem; }
[data-baseweb="input"], [data-baseweb="select"] > div { border-radius:4px; }
@media (min-width:1500px) { .hero-title { font-size:80px; } .compact .hero-title { font-size:61px; } }
@media (max-width:1300px) { .hero-ribbon .ribbon-extra { display:none; } }
@media (max-width:760px) {
    [data-testid="stMainBlockContainer"] { padding:4.5rem 1rem 2rem; }
    .okai-hero { min-height:305px; }
    .hero-type { padding:92px 22px 95px 20px; }
    .hero-title { font-size:clamp(40px,8vw,61px); letter-spacing:-.06em; }
    .connector-art { opacity:.25; }
    .hero-meta { left:20px; right:20px; font-size:.5rem; }
    .hero-meta span:last-child { display:none; }
    .hero-ribbon { justify-content:space-between; gap:8px; font-size:.49rem; }
    .hero-ribbon .ribbon-extra { display:none; }
    .compact .hero-type { padding:70px 20px 80px; }
    .compact .hero-title { font-size:40px; }
    .masthead-right > span:first-child { display:none; }
    .metric-value { font-size:2rem; }
    .project-footer { gap:15px; font-size:.5rem; }
}
@media (prefers-reduced-motion: reduce) {
    .okai-brand, .metric-card--link { transition:none; }
}
</style>
"""


def inject_styles():
    """Apply shared CSS once per rerun; named containers keep chart rules scoped."""
    st.html(STYLES)
    # CSS variables bridge the Python tokens into HTML; Plotly reads the same
    # tokens in charts.py. Overrides remain small so existing layout is retained.
    variables = ";".join([f"--{key}:{COLORS[key]}" for key in ["paper", "ink", "orange", "muted"]])
    variables += f";--card-accent-size:{GEOMETRY['card_accent_px']}px;--font-family:{FONT_FAMILY}"
    st.html("<style>:root{" + variables + "}"
            ".metric-card{border-top-width:var(--card-accent-size)}"
            ".metric-note,.metric-label,.brand-caption,[data-testid='stCaptionContainer'] p{color:var(--muted)}"
            ".metric-value{font-size:clamp(1.5rem,2.5vw,2.3rem);overflow-wrap:anywhere}"
            "html,body,[data-testid='stApp']{font-family:var(--font-family)}"
            "</style>")


def page_href(destination=None):
    """Keep the demo workspace when linking to home or an approved shortcut."""
    params = {}
    if workspace := st.query_params.get("workspace"):
        params["workspace"] = workspace
    if destination:
        params["open"] = destination
    return "./" + ("?" + urlencode(params) if params else "")


def brand_html(sidebar=False):
    """One accessible name; the vector asset owns slant and reflected geometry.

    An SVG keeps the same proportions in the header and sidebar. Its reflected
    copy is decorative, so the link has one spoken name instead of two logos.
    """
    return (f'<a class="okai-brand {"okai-brand--sidebar" if sidebar else ""}" '
            f'href="{escape(page_href(), quote=True)}" target="_self" aria-label="OKai home" title="Back to OKai start">'
            f'<img class="okai-wordmark-image" src="data:image/svg+xml;base64,{WORDMARK_ART}" '
            'alt="" aria-hidden="true"></a>')


def masthead():
    st.html('<div class="masthead">' + brand_html() + '<div class="masthead-right">'
            '<span>MAKE EVERY METRIC MEANINGFUL.</span><span class="demo-tag">PORTFOLIO DEMO</span></div></div>')


def hero(compact=False):
    title = "Clarity for operations." if compact else SLOGAN
    subtitle = ("A clear view of incident performance, data quality, and what deserves attention next."
                if compact else "From messy incident data to a clearer next move.\n"
                "An interactive lab for SQL analytics, data engineering, and machine learning.")
    st.html(f"""
    <div class="okai-hero {'compact' if compact else ''}">
      <div class="hero-meta"><span>OPERATIONAL DECISION INTELLIGENCE / OKai</span><span>SYNTHETIC WALKTHROUGH</span></div>
      <img class="connector-art" src="data:image/svg+xml;base64,{CONNECTOR_ART}" alt="" aria-hidden="true">
      <div class="hero-type"><div class="hero-title">{title}</div>
        <p class="hero-subtitle">{escape(subtitle)}</p></div>
      <div class="hero-ribbon"><span>PYTHON / SQL / MACHINE LEARNING</span><strong>OKai</strong>
        <span>SYNTHETIC DATA. REAL PIPELINE.</span><strong class="ribbon-extra">OKai</strong>
        <span class="ribbon-extra">CLEAN → ANALYZE → PRIORITIZE</span></div>
    </div>
    """)


def section(eyebrow, title, description=""):
    # HTML escaping keeps supplied labels/notes as text rather than executable
    # markup. Static layout can use HTML without trusting dataset values as HTML.
    st.html(f'<div class="section-heading"><div class="eyebrow">{escape(eyebrow)}</div>'
            f'<h2>{escape(title)}</h2><p>{escape(description)}</p></div>')


def metric(label, value, note="", color=INK, destination=None, action_label=None):
    """Optional destinations turn the entire card into a keyboard-accessible link."""
    tag = "a" if destination else "div"
    link = (f' href="{escape(page_href(destination), quote=True)}" target="_self" '
            f'aria-label="{escape(action_label or label, quote=True)}"' if destination else "")
    arrow = '<span class="metric-card-arrow" aria-hidden="true">↗</span>' if destination else ""
    st.html(f'<{tag} class="metric-card {"metric-card--link" if destination else ""}" '
            f'style="--card-accent:{color}"{link}>{arrow}'
            f'<div class="metric-label">{escape(str(label))}</div>'
            f'<div class="metric-value">{escape(str(value))}</div>'
            f'<div class="metric-note">{escape(str(note))}</div></{tag}>')


def feature(number, title, description):
    st.html(f'<div class="feature-card"><span class="feature-number">{escape(number)}</span>'
            f'<h3>{escape(title)}</h3><p>{escape(description)}</p></div>')


def note(text):
    st.html(f'<div class="context-note">{escape(text)}</div>')


def risk_pill(level):
    level = str(level)
    if level.strip().casefold() in {"none", "nan", "<na>", ""}:
        st.html(f'<span class="risk-pill" style="color:{MUTED}">RISK UNAVAILABLE</span>')
        return
    color = RISK_COLORS.get(level, MUTED)
    st.html(f'<span class="risk-pill" style="color:{color}">'
            f'<span class="risk-dot"></span>{escape(level.upper())} RISK</span>')


def style(fig, height=310):
    """Use the same base theme for historical, model, and quality charts."""
    return charts.theme(fig, height)


@contextmanager
def chart_panel(key, number, title, scope, reading):
    """Keep heading → chart → interpretation in one reusable, beveled container.

    `yield` lets the caller insert a Plotly chart or an honest empty state while
    this helper owns the surrounding layout. A stable key gives CSS one target.
    """
    with st.container(key=f"chart_{key}"):
        st.html(f'<div class="chart-heading"><div class="eyebrow">{escape(number)}</div>'
                f'<h3>{escape(title)}</h3><p>{escape(scope)}</p></div>')
        yield
        st.html(f'<div class="chart-reading"><strong>How to read it.</strong> {escape(reading)}</div>')


def chart_legend(items):
    """Pair semantic color with visible wording so meaning never relies on color alone."""
    entries = "".join(f'<span><i style="background:{color}"></i>{escape(label)}</span>'
                      for label, color in items)
    st.html(f'<div class="chart-legend">{entries}</div>')


def chart_empty(message):
    st.html(f'<div class="chart-empty">{escape(message)}</div>')


def quality_scope(run_id, source_name, finished_at):
    st.html(f'<div class="quality-scope"><span><strong>RUN {run_id}</strong> · '
            f'{escape(source_name)}</span><span>Snapshot: {escape(finished_at)} UTC</span></div>')


def bar(df, x, y, title, hover="%{y}: %{x:.1f}<extra></extra>", color=ORANGE):
    fig = px.bar(df, x=x, y=y, orientation="h", title=title)
    fig.update_traces(marker_color=color, marker_line_width=0, hovertemplate=hover)
    fig.update_layout(bargap=.42)
    return style(fig)


def timeline(events, limit=6, owner_labels=None):
    if events.empty:
        st.html('<div class="empty-state">Your workspace starts with a clean slate.<br>'
                'Review an incident or add a note to start the activity timeline.</div>')
        return
    labels = {"assigned_team": "Team", "owner": "Owner", "review_state": "Review"}
    owner_labels = owner_labels or {}
    for event in events.head(limit).to_dict("records"):
        before, after = json.loads(event["before_json"]), json.loads(event["after_json"])
        changes = [f'{labels[key]}: {owner_labels.get(before.get(key), before.get(key, "—")) if key == "owner" else before.get(key, "—")} '
                   f'→ {owner_labels.get(value, value) if key == "owner" else value}'
                   for key, value in after.items() if before.get(key) != value]
        summary = " · ".join(changes) if changes else "Added a note"
        note_html = f'<p>{escape(event["note"])}</p>' if event["note"] else ""
        st.html(f'<div class="timeline-item"><div class="timeline-top">'
                f'<strong>{escape(owner_labels.get(event["actor"], event["actor"]))} · {escape(event["incident_id"])}</strong>'
                f'<span>{escape(event["happened_at"])} UTC</span></div>'
                f'<p>{escape(summary)}</p>{note_html}</div>')


def footer():
    st.html('<div class="project-footer"><span><span class="brand-name">OKai</span> / A DATA PORTFOLIO PROJECT</span>'
            '<span>LOCAL WORKSPACE · SOURCE SHOWN IN ANALYSIS</span></div>')
