# OKai Calculation Engine and metric reference

OKai calculates operational metrics in [`src/calculations.py`](../src/calculations.py).
Dashboards, the Calculation Inspector, and the read-only interpretation tools use
the same definitions. A rendered card does not maintain a second formula.

## Data contract and grain

`CalculationEngine(incidents, events=None, context=None)` takes two distinct
pandas tables:

| Input | Contract | Important columns |
|---|---|---|
| `incidents` | One whole, deterministically selected snapshot per nonmissing incident ID. Duplicate IDs raise `ValueError`; the engine does not choose a snapshot. | `incident_id`, `source_row`, `status`, `priority`, `assignment_group`, `opened_at`, `resolved_at`, `source_sla_met` |
| `events` | Optional historical observations, not deduplicated by incident ID. The engine retains only the identifiers, event time, source row, and ordering columns it needs. | `incident_id`, `event_at`, `source_row`, optional `event_id`/`source_sequence` |
| `context` | Explicit source provenance and time semantics. | `dataset_id`, `source_name`, `source_kind`, optional `import_id`, `timezone`, `observation_start`, `observation_end`, `warnings` |

Supported source kinds are `demo` and `event_log`. An unknown source timezone is
represented by the literal `unknown`; it is not silently changed to UTC. The
context's observation window describes the selected cohort. It does not filter
rows automatically. Callers must select a coherent source/import/cohort before
constructing the engine, and must treat the engine's frames as read-only.

Event-aware ingestion supplies `opened_at`/`resolved_at` and nullable Boolean
`source_sla_met`. Legacy demo facts supply `created_at`, validated
`resolution_time_minutes`, and nullable `sla_breached`. Missing service, response,
financial, or policy inputs stay unavailable. A coded source category is not
invented into a business service name.

An imported latest snapshot supports retrospective reporting. It is not an
approved prediction feature set. Future enriched fields must never be carried
back into an earlier model observation.

## Public interface

```python
from src.calculations import CalculationContext, CalculationEngine

context = CalculationContext(
    dataset_id="source-namespace",
    source_name="Approved event export",
    source_kind="event_log",
    import_id="saved-import-id",
    timezone="unknown",
    observation_start="2016-02-29T01:16:00",
    observation_end="2017-02-18T15:00:00",
)
engine = CalculationEngine(latest_incidents, historical_events, context)
result = engine.calculate("source_sla_attainment")
inspection = engine.inspect("source_sla_attainment")
field_result = engine.calculate("field_completeness", {"field": "resolved_at"})
```

The example window illustrates the context shape; production callers use saved
import metadata instead of copying these example dates. The engine also exposes
`summary()`, `by_dimension(dimension)`, `monthly_trend()`, and
`alerts(config, as_of=...)`.

`database.kpi_summary`, `database.sla_by_dimension`, and
`database.monthly_trend` preserve the demo's existing public names and output
keys while delegating to this engine. Group and trend outputs additionally
expose eligible/excluded SLA outcome counts. Group outputs expose valid duration
counts. Do not average group percentages to calculate overall attainment.

## Result and inspector contract

Every result contains:

- `metric_id`, `value`, `status`, `unit`;
- `observation_window` including the explicit source timezone;
- `dataset_id`, `source_name`, `source_kind`, `import_id`;
- `eligible_count`, `excluded_count`, `numerator`, `denominator`;
- `formula_version`, UTC `calculated_at`;
- `warnings`, `assumptions`, `unavailable_reason`, and used `parameters`.

An unavailable result has `value=None`, not zero. A count of zero can be a valid
available observation. Rates with an empty denominator are unavailable. A
nonfinite result or intermediate becomes explicit unknown and carries a reason;
JSON serialization never relies on nonstandard `NaN`/`Infinity` values.

`inspect()` returns `definition`, `result`, and a `records` DataFrame. Record
evidence retains `incident_id`, `source_row`, and `event_id` when provided, plus:

- `included`: membership in the eligible calculation population;
- `reason`: why the record contributes or is excluded;
- `numerator_member`: membership in a rate/count numerator where relevant;
- `contribution_value`: duration hours where relevant.

The Calculation Inspector's JSON trace export packages the metric definition,
result (including unavailable reasons), source/import context, parameter values
and origins, and every evidence row. If a scenario denominator is confirmed
against the source, the supporting incident rows are included separately from
the scenario's result row. The existing CSV evidence export remains available.

For completeness, a missing field value still belongs to the denominator.
Consequently its `included` is true and its `numerator_member` is false. This is
intentional: excluding missing assignments from the denominator would manufacture
100% completeness. An absent entire source column makes that metric unavailable.

## Registered metrics, version 1.0.0

The immutable runtime registry additionally contains business purpose, required
fields, exact exclusions, missing-data behavior, rounding, window semantics, and
validation requirements. The inspector displays that registry directly.

| Metric ID | Formula / population | Unit and important exclusions |
|---|---|---|
| `unique_incident_count` | Count distinct snapshot incident IDs. | Incidents; constructor refuses mixed-grain repeated IDs. |
| `total_event_count` | Count events with nonmissing incident ID and valid event timestamp. | Events; unavailable when no event history was provided. |
| `resolved_incident_rate` | 100 × Resolved/Closed snapshots ÷ snapshots with recognized status. | Percent; unknown status excluded. A populated future resolution timestamp does not override source status. |
| `source_sla_attainment` | 100 × resolved/closed snapshots reporting met ÷ resolved/closed snapshots with known source outcome. | Percent; missing/invalid outcomes and unresolved states excluded. Source-reported, not independently verified contractual compliance. |
| `demo_sla_attainment` | 100 × resolved/closed demo snapshots with `sla_breached=0` ÷ resolved/closed demo snapshots with known outcome. | Percent; unavailable for event-log sources. Only the synthetic configured elapsed policy applies. |
| `mean_resolution_hours` | Sum of valid gross resolution hours ÷ valid resolved/closed duration observations. | Hours; missing/invalid/negative duration and unresolved status excluded. |
| `median_resolution_hours` | Median of the same valid gross duration population. | Hours; `pandas.quantile(0.5, interpolation="linear")`, the midpoint of two central values for even populations. |
| `assignment_completeness` | 100 × known final assignment groups ÷ all snapshots. | Percent; unknown groups stay in the denominator and appear as `Unknown` in grouped reporting. |
| `field_completeness` | 100 × valid nonmissing selected field values ÷ all snapshots. | Percent; allowlisted field required; timestamp/numeric/Boolean/status/priority types validated where applicable. |
| `unresolved_incident_count` | Count recognized nonterminal source statuses. | Incidents; missing SLA does not itself mean open. |
| `high_priority_incident_count` | Count Critical/High source priorities, including normalized UCI variants. | Incidents; missing/unrecognized priority excluded from eligibility. |
| `time_saved_hours` | Supplied baseline hours − supplied observed hours. | Hours; matched processing scope required; negative savings retained. |
| `time_reduction_pct` | 100 × (baseline − observed) ÷ baseline. | Percent; baseline must be positive; negative reduction retained. |
| `estimated_labor_value` | Supplied saved hours × supplied hourly labor cost. | Explicit currency; estimated labor capacity value, not demonstrated cash savings. |
| `processing_throughput` | Supplied successfully processed whole records ÷ positive elapsed seconds. | Records/second; caller must identify the processing stage and matching scope. |
| `cost_per_incident` | Supplied eligible operational cost ÷ explicit positive whole incident count. | Explicit currency/incident; neither cost nor eligible financial scope is inferred. |

Counts round to integers. Percentages and gross duration hours round once at the
result boundary to one decimal. Financial/throughput outputs round to two
decimals. Numerators and denominators retain underlying precision. Python's
`Decimal` with `ROUND_HALF_UP` preserves the historical SQL result midpoint
behavior (away from zero); rounding never changes population membership. The
legacy ETL margin helper retains its existing pandas rounding behavior.

Known terminal statuses are `Resolved` and `Closed`. Recognized nonterminal
statuses are `Open`, `In Progress`, `New`, `Active`, `Awaiting User Info`,
`Awaiting Vendor`, `Awaiting Problem`, and `Awaiting Evidence`, ignoring case and
surrounding spaces. Unknown strings are not silently classified as open.

Gross imported resolution duration is `resolved_at − opened_at`. Explicit offset
timestamps are normalized to UTC. Named-zone naive timestamps are localized with
ambiguous/nonexistent daylight-saving times rejected as unknown. Unknown-zone
naive times are subtracted as source-clock values with a daylight-saving warning.
Gross time includes waiting and is not an SLA business-hours clock.

## Explicit scenario inputs

Financial and efficiency metrics cannot measure savings automatically. Their
parameters must be supplied as matched observations:

| Metric | Required parameters |
|---|---|
| `time_saved_hours`, `time_reduction_pct` | `baseline_hours`, `observed_hours` |
| `estimated_labor_value` | `hours_saved`, `hourly_labor_cost`, `currency` |
| `processing_throughput` | `processed_records`, `elapsed_seconds` |
| `cost_per_incident` | `operational_cost`, `incident_count`, `currency` |

An empty parameter object returns unavailable and names the missing inputs.
Inputs must be finite, nonnegative numbers except saved hours, which may represent
capacity loss. Currency must be explicit. No default salary, hourly rate, cost,
or cash-savings assumption exists.

## Deterministic investigation rules

`ThresholdConfig` exposes `age_hours=72`, `backlog_threshold=100`,
`sla_warning_minutes=60`, `high_priority_unassigned=True`, and an explicit
`rule_basis`. These are configurable investigation examples, not verified
contractual SLA rules. Backlog triggers strictly above its threshold; age
triggers strictly above its threshold; deadline proximity includes zero through
the configured number of remaining minutes.

Backlog and high-priority missing-assignment rules inspect current selected
snapshots. Age and deadline rules require an explicit `as_of` timestamp. They
never use the machine's current time implicitly, and timezone-incompatible
comparisons raise a validation error. The `as_of` timestamp must be at or after
the context's observation end, or the latest available snapshot event timestamp
when the context omits that bound. Evaluating a final snapshot at an earlier
historical time is rejected: point-in-time replay is not implemented. Missing
snapshot timing is also explicit rather than guessed. Deadline proximity requires a real
`sla_deadline_at` column; no source SLA deadline is derived from demo targets.

Each alert contains its rule, incident membership where applicable, observed
value, threshold, message, rule basis, explicit `as_of`, dataset/import/source,
and formula version. Alerts suggest investigation; they do not prove causation
or constitute validated statistical predictions.

## Read-only interpretation boundary

[`src/calculation_tools.py`](../src/calculation_tools.py) defines `TOOL_SCHEMA`
and `execute_metric_tool(engine, request)`. This is an internal Python interface;
there is no remote endpoint, connected LLM, or MCP service.

Allowed actions are `list_metrics`, `calculate`, `inspect`, and `alerts`. Inputs
are validated against metric/rule/field allowlists. The caller supplies an
already-authorized engine. Requests cannot choose a filesystem path, execute
SQL/code, alter source records, trigger imports, or train models. Inspector and
alert membership is paginated, at most 1,000 rows per response.

The deterministic explanation renderer repeats returned backend values and their
limitations. It does not do alternate arithmetic, invent absent policies or
financial values, infer causation, or treat imported historical outcomes as
validated predictions. Errors return `ok=False` with `invalid_request` rather
than executing a fallback operation.

## Verification

[`tests/test_calculations.py`](../tests/test_calculations.py) uses hand-worked
examples to verify event/incident grain, final-state eligibility, source/demo
SLA separation, unknown denominators, inspector membership, mean/median
population agreement, zero/invalid/negative durations, timezone conversions and
DST ambiguity, completeness, explicit scenario arithmetic, finite-result/JSON
boundaries, configurable alerts, and strict read-only requests. Existing ETL
and database tests verify compatibility with the working synthetic pipeline.

Full-dataset counts and measured stage timings belong in the validation case
study. They are calculated from imports and are not constants in this engine.
