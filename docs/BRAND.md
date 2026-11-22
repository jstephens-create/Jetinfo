# OKai brand language and interface vocabulary

**Product:** OKai  
**Category:** Operational Decision Intelligence  
**Recommended slogan:** **Make every metric meaningful.**

OKai helps a person understand an operational measure, inspect its source and limitations, and choose a justified next action. The product demonstrates Python, SQL, data engineering, and statistical modeling. Its simulated personas are not real authentication. Its internal calculation/explanation interface is not an externally connected generative AI assistant.

## Position and visual direction

The current application uses warm paper (`#F7F6F3`), black feature panels, orange (`#FF512B`), pink display type, and purple/cyan/green connectors. Preserve this familiar foundation instead of changing every surface to a dark dashboard. Black panels provide emphasis; large light analytical areas support reading tables and comparing charts. Use the centralized [design tokens](../src/design.py), shared [chart theme](../src/charts.py), [UI helpers](../src/ui.py), and [Streamlit theme](../.streamlit/config.toml).

The [OKai wordmark](../assets/okai-wordmark.svg) retains its slight italic slant, orange `ai`, and fading reflected lower copy. The logo remains readable text artwork, not a claim that a generative AI service is connected. Card top edges are thick enough to identify their boundary, while flat two-dimensional chart marks preserve measured length. Keep visible focus, textual status labels, and explicit units; color alone never carries risk or quality meaning.

## Candidate evaluation

Scores are editorial judgments on a 1–5 scale, where 5 is strongest. They are **not measured customer-research results**. C = clarity, M = memorability, T = technical credibility, D = distinctiveness, R = relevance to actual capabilities, E = enterprise suitability. Suitability describes restrained language, not proof of enterprise readiness.

### Five primary slogans

| Candidate | C | M | T | D | R | E | Assessment |
|---|---:|---:|---:|---:|---:|---:|---|
| **Make every metric meaningful.** | 5 | 5 | 5 | 3 | 5 | 5 | Recommended: directly connects calculation, interpretation, and human use without promising autonomous action. |
| Know the data. Understand the impact. | 5 | 4 | 4 | 3 | 4 | 5 | Clear, but “impact” needs qualification when financial or causal evidence is unavailable. |
| Clarity for complex operations. | 5 | 4 | 5 | 2 | 4 | 5 | Credible umbrella language, less specific about measurable methods. |
| From records to reasoned decisions. | 4 | 4 | 5 | 4 | 5 | 5 | Strong traceability story; “reasoned” is slightly more formal than the interface. |
| Trace the number. Find the next step. | 5 | 4 | 5 | 4 | 5 | 4 | Useful operational emphasis, better as supporting copy than the main product promise. |

The recommendation is a commitment to visible definitions and provenance. A metric is meaningful only when its unit, denominator, eligible records, exclusions, and limitations are available. The Calculation Inspector makes that promise reviewable. The slogan does not imply every available field is useful or every result supports a business intervention.

### Five short interface catchphrases

| Candidate | C | M | T | D | R | E | Intended location |
|---|---:|---:|---:|---:|---:|---:|---|
| Inspect the number. | 5 | 4 | 5 | 3 | 5 | 5 | Calculation Inspector link or metric detail. |
| Keep the history. | 5 | 4 | 5 | 3 | 5 | 5 | Event preservation explanation. |
| Count what matters. | 4 | 5 | 4 | 3 | 5 | 4 | Event-versus-incident guidance, with a named counting unit. |
| See what is missing. | 5 | 4 | 5 | 3 | 5 | 5 | Completeness and exclusions. |
| Review the evidence. | 5 | 4 | 5 | 2 | 5 | 5 | Decision/risk evidence panel; a human remains responsible. |

### Three positioning statements

| Candidate | C | M | T | D | R | E | Assessment |
|---|---:|---:|---:|---:|---:|---:|---|
| OKai turns incident records into traceable operational metrics and evidence for human decisions. | 5 | 4 | 5 | 4 | 5 | 5 | Preferred general product positioning; concise and tied to implemented work. |
| OKai connects event-aware data preparation, reproducible calculations, and explainable incident analysis in one lightweight application. | 4 | 3 | 5 | 4 | 5 | 5 | Strong technical audience statement; requires event ingestion to be present. |
| OKai is an operational decision workspace that shows where a number came from, who it describes, and what deserves investigation. | 5 | 4 | 5 | 4 | 5 | 5 | Useful presentation copy; “investigation” avoids unsupported causal conclusions. |

### Three onboarding messages

| Candidate | C | M | T | D | R | E | Intended context |
|---|---:|---:|---:|---:|---:|---:|---|
| Start with the synthetic demo, or import a supported event log. Keep the selected source in view as you explore. | 5 | 3 | 5 | 4 | 5 | 5 | Source selection. Do not display the import option unless the workflow is available. |
| Open a metric to inspect its formula, contributing records, exclusions, and assumptions. | 5 | 3 | 5 | 4 | 5 | 5 | Calculation Inspector introduction. |
| Choose a demo persona to explore reviews and notes. Personas simulate a team; they do not authenticate a user. | 5 | 3 | 5 | 3 | 5 | 5 | Existing workspace entry. |

### Reusable product descriptions

| Use | Approved copy | C | M | T | D | R | E |
|---|---|---:|---:|---:|---:|---:|---:|
| Concise product description | OKai is a lightweight operational decision application that preserves incident history, calculates traceable metrics, and explains the evidence and limitations behind them. | 5 | 3 | 5 | 4 | 5 | 5 |
| One-sentence GitHub description | Operational decision intelligence portfolio project: Python, SQL, event-aware CSV ingestion, traceable metrics, and an interactive calculation inspector. | 5 | 3 | 5 | 4 | 5 | 5 |
| Professional portfolio description | Built OKai to demonstrate an end-to-end data workflow: validate operational CSVs, preserve event history, create reproducible incident snapshots, centralize metric definitions, and expose calculation evidence in Streamlit. The project separates source-reported SLA outcomes from demo policy calculations and keeps statistical estimates distinct from deterministic rules. | 5 | 3 | 5 | 4 | 5 | 5 |

Use descriptions only for capabilities present in the current implementation. Do not add savings percentages, deployment scale, real customer results, or production-readiness claims without evidence.

## Interface vocabulary

| Term | Meaning and usage |
|---|---|
| Operational Overview | Validated summary for the selected source and observation window. |
| Import Desk | A supported CSV/profile import workflow; not a generic ITSM/API connector. |
| Data Foundation | Explanatory architecture term for raw preservation, validation, history, and snapshots; avoid an empty navigation page. |
| Calculation Inspector | Backend definitions, result, numerator/denominator, included/excluded records, and assumptions. |
| Incident queue | Existing synthetic open-incident review workspace; imported historical closed incidents must not appear as live work. |
| Risk lab | Existing synthetic-model evidence and what-if estimates; not validation on real imported data. |
| Decision support | Evidence-based investigative guidance; not autonomous incident resolution. |
| Data quality | Explicit record grain, validation results, missing values, and exclusions. |
| Source-reported SLA attainment | Latest incident-level source flag among known eligible outcomes; does not certify contractual compliance. |
| Demo-policy SLA attainment | Result under the explicitly simplified synthetic elapsed-time policy. |
| Gross elapsed resolution time | Valid resolved-minus-opened interval; excludes business calendars and pause logic. |
| Unknown / Unavailable | Missing source values or unsupported results; never silently relabel as zero, success, or failure. |
| Estimated labor capacity value | User-supplied saved hours multiplied by a supplied hourly rate; not realized cash savings. |

Use sentence case, concrete verbs, and concise explanations. Keep “source,” “as of,” and units near a displayed metric. An error should say which input failed and what the user can correct. Warnings should state a present limitation, not generic alarm language.

## Branding audit and compatibility

The active product name is **OKai**. Application title, navigation, headers, footer, exports, launch task, launcher messages, and README should use it. Old hero phrases that center “signal” as the product identity should use the approved slogan or concrete functional copy. Ordinary uses of the English word “signal” are not automatically branding defects.

The following are intentionally retained: `data/processed/signal.db`, model artifact names, `signal.etl` and `signal.model` logger names, source dataset values, and historical records. Renaming those provides no user benefit and could break existing files or compatibility. This documentation records their purpose rather than applying a blind replacement.

No trademark clearance, brand awareness research, accessibility certification, or enterprise readiness certification was performed. The evaluation above is a practical language and visual-consistency decision for this local portfolio product.
