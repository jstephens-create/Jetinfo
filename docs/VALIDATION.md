# Validation and performance record

This file separates verified behavior, measured local performance, and remaining limits. **The final combined suite completed with 124 tests passed in 31.44 seconds**, with the supplied real CSV enabled and **no skipped tests or warnings**. These results establish the tested local behavior, not business savings, formal standards certification, or organizational deployment readiness.

## Baseline checkpoint

On 2026-11-21, before calculation-engine and event-ingestion changes, the existing suite completed with **46 tests passed**. It covered synthetic ETL, SQLite writes and denominators, model inputs, demo review/reset isolation, and quality report/chart semantics.

The existing UCI audit showed that the old 11-field synthetic import contract safely rejected the event schema. That failure is the starting problem, not evidence that the new adapter passes.

## Integration evidence

| Check | Current evidence status |
|---|---|
| Known-example formula, null/zero denominator, rounding, exclusions | Passed in the final suite; hand-worked metric examples and finite/strict-JSON boundaries are covered |
| Invalid timestamps, timezone conversion, nonnegative duration | Passed; explicit timezone conversion, invalid zones, ambiguous/nonexistent DST times, invalid optional timestamps, and negative-duration handling are covered |
| Event versus incident grain and latest whole-row snapshot | Full UCI import preserves 141,712 events and selects 24,918 whole-row latest snapshots; focused tests also cover ordering ties |
| Immutable raw source / content hash / mapping provenance | Original SHA-256 matches the preserved copy; named profile and full mapping fingerprint stored in the import manifest |
| Repeated import idempotency and failed-import behavior | Same file/profile reuses the stored cohort; focused tests cover incompatible schema, required-core rejection, optional invalid fields, and preserved-copy integrity |
| Independent UCI reference counts and incident-level outcomes | New adapter/engine match an independent standard-library CSV/date scan; counts and outcomes below |
| Structured read-only interpretation contract | Passed; strict action/metric/parameter allowlists, pagination, error responses, grounded values, and no fallback writes |
| Demo pages, calculation inspector, import UI, and branding | Three isolated Streamlit AppTest workflows passed across both sources; fresh-process checks also rendered actual imported-source pages without exceptions |
| Existing demo facts/model compatibility and tests | Baseline behavior remains covered by the final passing regression suite; existing database/model paths remain compatible |

### Application and launch checks

The three [workflow tests](../tests/test_app_workflows.py) isolate both the demo and import databases. They exercise KPI navigation to the inspector, missing scenario values and a zero baseline, separate event/incident counts, source identity reuse, source/model boundaries, rule evaluation, and navigation across application pages.

A separate fresh-process AppTest smoke check used the actual seeded real import and rendered Overview, Calculation Inspector, imported incidents, Data quality, Decision Support, and the imported-source Risk lab boundary without exceptions. The live server was also observed with the correct OKai title, new navigation, and Analysis source selector. Automated workflow checks do not establish exhaustive responsive-layout or accessibility certification.

The live browser also selected the UCI source and displayed the reconciled 24,918-incident / 141,712-event overview. A local screenshot confirmed the reflected OKai wordmark, thick card accents, explicit eligibility counts, and beveled chart panels. The final layout pass aligned card label space and shortened the inspector button label for narrow columns. Focused UI/quality checks were rerun after that presentation adjustment.

The follow-up focused UI/quality run completed with **16 tests passed in 8.24 seconds**. The live Calculation Inspector also displayed the imported SLA result, its 15,803 / 24,918 fraction, source observation dates, formula, and record evidence. Detailed generated explanations remain expandable so the calculation itself stays prominent.

`run.ps1 -SetupOnly` checked dependencies and prepared artifacts successfully with exit code 0. A normal launch found port 8501 already serving the project, and the verified running OKai server was reused. No second server was claimed to have started on that occupied port. Editor diagnostics reported no problems in the changed app, new modules, or tests. `git diff --check` found no whitespace errors; Git emitted only line-ending conversion notices.

## Performance measurement contract

Report separately: file read/parsing, validation, normalization/snapshot creation, database writes, metric aggregation, and internal tool response. Include record counts, local environment, warm/cold context, and measurement method. A single local sample is not a service-level guarantee. The internal application has no external API deployment or network-response benchmark.

Do not combine preparation and serving timings into one throughput claim. Do not interpret parser speed as end-to-end UI latency. Cost/time-savings formulas can be tested numerically without proving that a real intervention produced savings.

## Full-file backend validation

The supplied 46,212,397-byte source has SHA-256 `fd184bbfd62329cfe093e99da2ea7071905f2ead91900b448eb2635870821bef`. The default local import ID in this run was `246d25a0fce54595a6cdd96696459aaa`; IDs are generated, not expected constants. No application formula hardcodes the source counts.

| Evidence | Verified result |
|---|---:|
| Loaded valid events / rejected core rows | 141,712 / 0 |
| Distinct latest incident snapshots | 24,918 |
| Source-reported met / known eligible incidents | 15,803 / 24,918 |
| Engine source-reported SLA attainment (one decimal) | 63.4% |
| Incident snapshots excluded from duration calculations | 1,556 |
| Valid-duration population | 23,362 |
| Engine mean / median gross resolution hours | 178.2 / 22.1 |
| Known / unknown final assignment group | 22,761 / 2,157 |
| Engine assignment completeness | 91.3% |
| Final Closed / unresolved incidents | 24,918 / 0 |
| Imported-data demo-policy SLA result | Explicitly unavailable |

The case study's event-weighted 93.4974% is intentionally an **incorrect incident reporting method**, not an alternative KPI. See the [denominator analysis](CASE_STUDY.md). Original source bytes and the demo cohort were not replaced by the import.

### Import phase measurements

Single local sample, Python **3.12.16**, Windows **10.0.19045**, 141,712 events and 24,918 incidents. These are elapsed wall-clock samples, not statistically characterized benchmarks. No peak-memory, concurrent-user, cold-disk, or long-running service benchmark was performed.

| Stage | Seconds | What was measured |
|---|---:|---|
| File preservation | 0.301 | Source hashing/integrity checking and preservation |
| Parsing | 1.068 | Reading preserved CSV strings and checking schema |
| Validation | 2.729 | Missing-value handling, timestamp/type checks, warnings/reasons |
| Normalization | 18.042 | Normalized event/snapshot construction, original-row JSON serialization, and SQL tuple preparation |
| Audit exports | 0.049 | Rejected-row and optional-field warning CSVs |
| Database writes | 3.502 | Event/snapshot/manifest/rejection transaction including commit |
| Measured import interval | 25.697 | Overall recorded interval, including stage overhead; excludes the small final timing-metadata update |

The resulting import database was **216,555,520 bytes (~206.5 MiB)**. The exact raw copy additionally occupies 46,212,397 bytes. Full per-event original-row JSON increases storage deliberately to retain evidence. JSON/tuple preparation is the largest measured cost; optimizing it should retain provenance rather than silently omit history.

### Read and calculation measurements

These are separate local samples against the prepared import. File import is not included. The internal tool call used an already-built engine after summary calculation and is therefore a subsequent calculation, not a cold end-to-end response.

| Operation | Seconds |
|---|---:|
| Read import metadata | 0.008 |
| SQL event count | 0.034 |
| Read three selected event columns (141,712 rows) | 0.885 |
| Read latest snapshots (24,918 rows) | 0.707 |
| Read one four-event incident timeline | 0.402 |
| Repeat import with the same file/profile | 0.455 |
| Separate combined snapshot/minimal-event read sample | 1.142 |
| Construct engine/context from those frames | 0.016 |
| Calculate engine summary, including first duration/evidence aggregation | 3.186 |
| Subsequent internal `calculate(source_sla_attainment)` tool response | 0.080 |

Separate samples can differ because of filesystem/database cache state. Do not add them into a promised UI response time. There is no network API response measurement because no HTTP/MCP service was added.

## Known reliability boundaries

- Each import is an immutable export cohort. Latest state is selected **within that file**; cross-file freshness merges, incremental watermarks, historical as-of replay, scheduled refresh, CDC, and API polling are not implemented.
- Database facts are written transactionally. Raw-file and CSV-export filesystem operations are not part of a distributed transaction; a failed database write can leave an unreferenced export directory. There is no durable failed-attempt job ledger.
- The file/profile unique constraint prevents duplicate committed facts. Simultaneous first imports have not been workload-tested; one racing caller can receive a constraint error rather than a transparently coordinated job result.
- Timing metadata is finalized in a small subsequent transaction. An abrupt process crash can leave incomplete timing evidence even when the fact transaction completed.
- Historical outcome timestamps and latest assignments are not validated prediction-time inputs. No real-file model retraining or claim of predictive generalization is part of this change.
- Source timezone, contractual SLA policy/calendar, real identity controls, retention/backup operations, and business cost/savings measurements remain unavailable or outside the local demonstration scope.

## Reliability sprint verification

Imports now persist an attempt lifecycle in `source_import_attempts`: preserving, parsing,
validating, normalizing, exporting, database_write, committed, failed, or interrupted.
Fact rows, snapshot pointers, rejections, and the manifest are inserted in one SQLite
transaction. Injected commit failures leave no partial source facts and can be retried
against the same import identity. Repeated committed imports remain idempotent.

The read path no longer requests raw event JSON unless `include_raw=True`; normal
timeline/count/snapshot reads select normalized columns only. Targeted tests verify
the timeline and snapshot indexes and the absence of temporary snapshot ordering.

Authentication and authorization remain explicitly simulated. A workspace UUID and
persona selector are demo conveniences, not identity verification or tenant isolation.
Local imports are shared to anyone who can run or access the application. No role,
dataset, incident, or investigation authorization boundary is implemented.

## Reproduction

Run the focused and full test suites with the project environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Use the [launcher](../run.ps1) or existing VS Code task for the interactive app. The ingestion-focused run, including the optional real-file test, completed with **20 passed in 28.72 seconds**. The final combined suite completed with **124 passed in 31.44 seconds** with the same real CSV enabled.

The full-file test is opt-in so a normal checkout does not require a local third-party download. Point it at the supplied CSV to independently compare application results with a standard-library reference:

```powershell
$env:OKAI_UCI_CSV = 'C:\Users\jstep\Downloads\incident+management+process+enriched+event+log\incident_event_log.csv'
.\.venv\Scripts\python.exe -m pytest tests/test_event_ingestion.py -q
# All formulas, ingestion, application workflows, and existing regressions:
.\.venv\Scripts\python.exe -m pytest
```

Import directly with `python -m src.event_ingestion --source <local-csv>`. The persisted manifest contains the actual file/profile identity, original-copy path, audit-export paths, per-stage timings, warnings, and counts for that import. Reimporting it returns `idempotent_reuse=true` while preserving the original processing measurements.

## Implementation file map

This map describes the additive architecture work, rather than treating all pre-existing working-tree edits as newly authored changes.

| Files | Role in this implementation |
|---|---|
| [calculations.py](../src/calculations.py), [calculation_tools.py](../src/calculation_tools.py) | New deterministic registry/result/evidence service and strict read-only interpretation boundary |
| [event_ingestion.py](../src/event_ingestion.py) | New source profile, preserved-file identity, event history, incident snapshot, rejection, and read contracts |
| [intelligence_views.py](../src/intelligence_views.py) | New source-aware overview, Import Desk, Calculation Inspector, historical exploration, quality, decision, and governance views |
| [design.py](../src/design.py) | New shared brand/color/geometry/font tokens |
| [app.py](../app.py) | Integrates source selection, navigation, authoritative views, and the imported-data model boundary |
| [views.py](../src/views.py) | Retains the existing overview entry point as a compatibility wrapper around the shared engine-backed view |
| [database.py](../src/database.py), [etl.py](../src/etl.py) | Preserve public compatibility functions while delegating metric/demo-SLA arithmetic to the engine |
| [ui.py](../src/ui.py), [charts.py](../src/charts.py) | Reuse shared tokens, preserve beveled framing and flat data marks, and apply OKai language |
| [test_calculations.py](../tests/test_calculations.py), [test_event_ingestion.py](../tests/test_event_ingestion.py), [test_app_workflows.py](../tests/test_app_workflows.py) | New known-example, source-contract, independent-reference, numerical/tool, and UI workflow coverage |
| [README](../README.md), [architecture](ARCHITECTURE.md), [metric reference](METRICS.md), [case study](CASE_STUDY.md), [brand language](BRAND.md), this validation record | Product purpose, contracts, design choices, evidence, limitations, and reproduction |
| [.gitignore](../.gitignore) | Excludes preserved third-party import files/exports under `data/imports/` |

The existing [launcher](../run.ps1), [VS Code task](../.vscode/tasks.json), [configuration](../src/config.py), dependencies, demo review storage, and model artifacts remain part of the working project. No dependency, separate service, external API, MCP server, real identity integration, destructive migration, model retraining on imported events, or external deployment was added.

## Recommended next development milestone

Agree on a real operational source contract with an owner before extending the source scope: confirm timezone and actual SLA-policy semantics, define retention/access controls, and specify a small investigation workflow with measurable review outcomes. For continued local engineering, profile and reduce raw-JSON/tuple preparation cost without losing evidence, and add a durable import-attempt ledger if retry/recovery becomes a real workflow requirement. Measure a prospective intervention before presenting time savings, labor capacity value, or causal business impact as achieved outcomes.

See [architecture](ARCHITECTURE.md), [metric definitions](METRICS.md), and the [event-log case study](CASE_STUDY.md) for scope and interpretation.
