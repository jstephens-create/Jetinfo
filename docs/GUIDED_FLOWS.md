# Guided flows by persona

Personas are a mock sign-in (no real identity provider). Each flow is
**Role → Goal → Available actions → Required inputs → Result and evidence**.
Status: **Implemented** = in the app now; **Proposed** = design only.

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
