# Guided flows by persona

Personas are a mock sign-in (no real identity provider). Each flow is
**Role → Goal → Available actions → Required inputs → Result and evidence**.
Status: **Implemented** = in the app now; **Proposed** = design only.

## Guided synthetic missions

Select **Start guided demo** at sign-in or in the sidebar. The orientation
introduces the selected role and asks the user to open **Incident queue** using
the main button or sidebar navigation. Only reaching that view unlocks Next.
Select **Continue to next mission** to move from step 0 to the role-specific
first mission. The guide explains a locked Next button beside the action and
in the sidebar.

The Analyst starts with a handover, the Manager with service-level analysis,
and the Admin with data quality. The journeys then connect the overview, metric evidence and
limitations, hypothetical cost and time estimates, incident handover, investigation
rules, data quality, the risk lab, and governance. Highlighted instructions explain the
key moment on each page and place each mission in the source-to-action architecture.
The next mission unlocks only after the relevant action succeeds or the correct
answer is selected. Handover requires a saved review, scenarios require the
specified inputs, and the risk checkpoint requires a successful score and
explanation after a priority change. The checks verify those interactions, not
that the user understood or read every screen. Users can review the result,
go back, skip, pause, restart, or exit. Revisited completed missions remain
verified; skipped missions are reported separately. Progress is session-only;
saved review changes remain in the demo workspace.

The focus panel presents the architectural layer and key moment. An outline
marks the current control or form, while unrelated charts and tables are
subtly dimmed without blocking interaction. This is not a full-screen overlay
or browser zoom. Chart/table opacity returns on hover or keyboard focus and
when the user requests higher contrast; reduced-motion settings disable
decorative transitions. These measures are not a full accessibility audit.
If the user visits another page, the guide offers a route back without clearing
verified progress. For a handover, the form submits all fields together; an
incomplete save identifies the missing owner, review state, or note. Clear
queue filters if no matching incident is visible, or skip if the synthetic
queue is empty. A completed journey shows verified and skipped steps separately.

The tour uses only the synthetic source. Importing is a separate entry point;
switching to an imported source or opening Import Desk pauses the tour without
changing the selected import. Back navigation is disabled there; resuming or
restarting explicitly switches back to the demo.
CSV import currently supports the UCI Incident Management event-log profile,
not arbitrary CSV schemas. The data quality and risk missions can be skipped
when the pipeline run or model is unavailable.

Mock names and positions are presentation labels. The saved owner identifiers
and audit data remain unchanged. After updating Python modules, restart the
Streamlit process rather than only refreshing the browser: a running process
may retain previously imported modules even when `app.py` reruns. Stop the
running OKai server with Ctrl+C in its terminal, then launch it from the project
root:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Confirm the server is ready at `http://localhost:8501`. Restarting clears
browser-session tutorial progress but does not reset saved demo reviews or
imported data.

## Persona flows

| Role | Goal | Available actions | Required inputs | Result and evidence |
|---|---|---|---|---|
| Analyst (lands on Incident queue) | Find records that distort a number | Incident queue → Inspect → review excluded records | A source; optionally a metric | Excluded rows with reasons; per-incident history for imported sources |
| Manager (lands on Overview) | Decide whether a number is trustworthy enough to act on | Overview → Inspect → Decision Support | A source; scenario inputs for cost/time metrics; an as-of time for Decision Support | Value, formula, eligible/excluded counts, assumptions |
| Admin (lands on Data quality) | Confirm the source can be relied on | Data quality → Import Desk → Inspect a metric | A CSV (upload or local path) and timezone | Import quality, completeness, row-level evidence |

## Screens

| Screen | Highlighted action | Secondary options that stay visible | Changes with the data source | Unavailable option and why | Status |
|---|---|---|---|---|---|
| Calculation Inspector | One per role and metric state: Analyst → Review excluded records, Manager → Review decision evidence, Admin → Check data quality. With missing inputs the highlight moves to "Enter inputs". | The other actions plus Export evidence | Metric groups are recomputed per source (e.g. event count needs events; demo SLA is demo-only) | Greyed buttons carry a caption saying why and what to do next | **Implemented** |
| Investigations | Select a source incident, inspect its metric evidence, save an owner and follow-up plan, then record a reported outcome | Open the selected metric in Calculation Inspector; review the immutable trace and event history | Stable synthetic source ID or immutable import ID; source incidents remain read-only | Unavailable metrics keep their reason and incident membership in the saved trace | **Implemented** |
| Overview | Inspect the headline metric | Other metric cards, Import Desk | Demo vs imported metric set | Card note names the missing field | Proposed |
| Incident queue | Open the first unreviewed incident | Filters, export | Review/assignment only on the demo; imported sources show a read-only snapshot table | "Not scored" explains imported sources have no model score | Proposed |
| Import Desk | Choose CSV | Local path, timezone | Imported source becomes selectable | Import stays disabled until a file and timezone are chosen | Proposed |
| Decision Support | Set the as-of time | SLA definition, outcome concentration | Needs as-of at or after the source observation end | Explain the earliest valid as-of timestamp | Proposed |
| Data quality | Review the worst-completeness field | Duration checks | Demo checks vs import quality | Fields missing from the source are listed, not hidden | Proposed |
| Risk lab | Score a scenario | Saved reviews | Demo only | "Not scored" on imported sources, with a link to switch to the demo | Proposed |

## Calculation Inspector

Metrics are grouped without running every calculation (a full run takes about 3 s on the 24,918-incident source):

- **Available from this source** – required columns exist.
- **Needs scenario inputs** – cost, time-reduction and similar metrics. Every value you type is labelled *your assumption*.
- **Unavailable** – the reason and the next step sit beside the metric (for example, import an event log for total events).

Estimated cost per incident:

1. Pick a currency from the list, or choose "Other…" and type a validated three-letter code.
2. Enter the operational cost (validated, non-negative number).
3. Eligible incidents: choose "Cost covers all N unique incidents in this source" or enter your own count. The source count is never preselected, because only you know whether the cost covers the same population. Events are not counted as incidents.
4. The result shows the formula, the formula with your values, an inputs table (source vs your assumption), and the contributing incident records.

## Worked example

Manager, imported UCI event-log source, goal: cost per incident.

1. Overview → source "UCI Incident Management Process" → Calculation Inspector → group **Needs scenario inputs** → *Estimated cost per incident*.
2. Currency **USD**; operational cost **1,245,900** (your assumption); choose **Cost covers all 24,918 unique incidents in this source**.
3. Result: `1,245,900 / 24,918 = 50 USD/incident`, labelled as depending on user-entered assumptions.
4. Evidence: 24,918 unique-incident records (one per incident, not the 141,712 events). The highlighted next step is **Review decision evidence**; Review excluded records is greyed with "Scenario results have no excluded rows".

The cost figure is illustrative.
