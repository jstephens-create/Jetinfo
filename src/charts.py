"""A small chart design system: shared geometry, typography, units, and colors.

The surrounding UI adds the bevel. Bars stay two-dimensional because shadows
or perspective on a bar can make its measured length difficult to compare.
"""
from textwrap import fill
from math import ceil, log10

import plotly.graph_objects as go

from src.quality import QualityReport
from src.design import COLORS, GEOMETRY, FONT_FAMILY

# These are semantic tokens, not a new color choice for every chart. A field
# whose missing value may be expected must not use the invalid-row color.
QUALITY_COLORS = {
    "loaded": COLORS["loaded"], "duplicate": COLORS["duplicate"], "invalid": COLORS["invalid"],
    "required": COLORS["invalid"], "outcome": COLORS["outcome"], "derived": COLORS["informational"],
    "informational": COLORS["informational"],
}
CHART_HEIGHT = GEOMETRY["chart_height_px"]
QUALITY_CONFIG = {"displayModeBar": False, "displaylogo": False, "responsive": True}


def theme(fig, height=310):
    """Apply the same font, contrast, grid, and margins throughout the app."""
    fig.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", height=height,
                      font=dict(family=FONT_FAMILY, size=12, color=COLORS["ink"]),
                      title_font=dict(size=14), margin=dict(l=8, r=15, t=45, b=12),
                      hoverlabel=dict(bgcolor="#20221F", font_color="#fff", font_size=12))
    fig.update_xaxes(gridcolor="#e3dfd6", zerolinecolor="#c8c2b6", title=None,
                     tickfont=dict(size=12, color="#5e5a53"))
    fig.update_yaxes(gridcolor="#e3dfd6", zerolinecolor="#c8c2b6", title=None,
                     tickfont=dict(size=12, color="#5e5a53"))
    return fig


def _quality_bar(labels, counts, percentages, colors, denominator, denominator_name,
                 axis_title, *, maximum=None, left_margin=145):
    """Show the count and its denominator in text and hover, with a zero baseline."""
    labels = [fill(label, width=24).replace("\n", "<br>") for label in labels]
    fig = go.Figure(go.Bar(
        x=list(counts), y=labels, orientation="h", marker=dict(color=list(colors), line_width=0),
        text=[f"{count:,} · {pct:.1f}%" for count, pct in zip(counts, percentages)],
        textposition="outside", textfont=dict(size=12), cliponaxis=False,
        customdata=[[pct, denominator] for pct in percentages],
        hovertemplate=("%{y}<br>%{x:,} / %{customdata[1]:,} " + denominator_name +
                       "<br>%{customdata[0]:.1f}%<extra></extra>"),
    ))
    theme(fig, CHART_HEIGHT)
    # Outside labels need a reserved right gutter, otherwise a long 93.7%
    # annotation gets clipped at the edge of a narrow chart card.
    fig.update_layout(margin=dict(l=left_margin, r=104, t=14, b=48), bargap=.42,
                      showlegend=False, dragmode=False)
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=labels,
                     showgrid=False, tickfont=dict(size=12), fixedrange=True)
    limit = maximum if maximum and maximum > 0 else max(max(counts, default=0), 1) * 1.1
    # Counts cannot have half a row. Pick a readable integer tick interval even
    # when the selected run contains only one invalid row.
    magnitude = 10 ** max(0, int(log10(max(limit / 4, 1))))
    step = next((factor * magnitude for factor in (1, 2, 5, 10)
                 if factor * magnitude >= limit / 4), ceil(limit / 4))
    fig.update_xaxes(title=dict(text=axis_title, font=dict(size=11, color="#6a665e")),
                     range=[0, limit], tickformat=",d", dtick=step, tick0=0,
                     minallowed=0, fixedrange=True)
    return fig


def row_outcomes(report: QualityReport):
    data = report.outcomes
    return _quality_bar(data.outcome, data.rows, data.source_pct,
                        [QUALITY_COLORS[kind] for kind in data.kind], report.source_rows,
                        "source rows", "Source rows", maximum=report.source_rows, left_margin=108)


def validation_rules(report: QualityReport):
    data = report.rule_failures
    return _quality_bar(data.rule, data.rows, data.invalid_pct,
                        [QUALITY_COLORS["invalid"]] * len(data), report.invalid_rows,
                        "invalid rows", "Invalid rows matching a rule", maximum=report.invalid_rows)


def missing_fields(report: QualityReport):
    # Zero-height bars add labels without adding information. The field audit
    # table keeps the complete list, including fields with zero missing values.
    data = report.fields[report.fields.missing_cells.gt(0)].sort_values(
        ["missing_cells", "label"], ascending=[False, True])
    return _quality_bar(data.label, data.missing_cells, data.source_pct,
                        [QUALITY_COLORS[kind] for kind in data.kind], report.source_rows,
                        "source rows", "Missing cells in each field", left_margin=145)
