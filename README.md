# OKai — Operational Decision Intelligence

**Make every metric meaningful.** An interactive portfolio project for entry-level data roles, connecting **Python, SQL, data engineering, and machine learning** to a practical question:

> *What does the operational data actually support, how was the number calculated, and what deserves investigation next?*

The original walkthrough generates synthetic IT incidents, validates them, stores them in SQLite, and trains a Logistic Regression on a creation-time feature allowlist. Its statistical evidence applies to the synthetic demo. The architecture now extends that foundation with event-aware import, centralized calculations, and inspection of metric definitions and exclusions. See the [architecture inventory](docs/ARCHITECTURE.md) and [validation record](docs/VALIDATION.md) for the implementation checkpoint and measured evidence.

**Stack:** Python 3.11+ · Pandas · SQLite · scikit-learn · Streamlit · Plotly. No cloud and no paid APIs.

The [metric reference](docs/METRICS.md), [event-log case study](docs/CASE_STUDY.md), and [brand decisions](docs/BRAND.md) explain the calculation contracts, the event-versus-incident denominator problem, and the product language. No external generative AI service, ITSM API, or real identity provider is connected.

---

## Quick start

### Windows / VS Code

Open the `Jetinfo` folder itself in VS Code (File > Open Folder). It is the
application's Git repository; the enclosing `signal-project` folder is a separate
repository. Use the Source Control branch label to confirm you are working on
`Jetinfo` before committing. The project's VS Code settings select its local
Python environment and discover tests. Terminal > Run Task also offers setup,
data/model rebuild, and tests.

Run **Terminal > Run Task > OKai: Run dashboard**, then open
<http://localhost:8501>. The task downloads a project-local Python 3.12 runtime
when needed, installs dependencies, prepares any missing data/model artifacts,
and starts Streamlit. Later launches reuse the prepared snapshot. The first run
requires internet access. Launcher tasks start Windows PowerShell directly
rather than going through the active integrated shell, so a broken terminal
profile cannot prevent them from running. Stop the dashboard with
**Terminal > Terminate Task** or Ctrl+C in the task terminal. The workspace also
offers *Setup only*, *Rebuild data and model*, and *Run tests* tasks. See
[guided flows by persona](docs/GUIDED_FLOWS.md) for the Calculation Inspector
flow and the [visual code study guide](docs/CODE_STUDY_GUIDE.md) for a guided
tour from UI to implementation.

You can also run the same launcher from PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
# Optional: prepare everything without starting the server
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -SetupOnly
# Optional: use another port
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Port 8502
# Optional: rebuild the dataset and model explicitly
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -RebuildData
```

Runtime downloads and caches stay in `.tools/`; packages stay in `.venv/`.
Pytest uses the ignored project-local `.pytest-tmp/` directory so an inaccessible
or stale user temp folder does not block the test task. The launcher verifies
that the local Python executable actually runs and recreates a copied or
otherwise stale environment whose `pyvenv.cfg` points to another checkout.

If the VS Code integrated terminal itself is unavailable, double-click
`run.cmd` from File Explorer. It launches the same `run.ps1` setup and dashboard
in a normal Windows console without depending on a VS Code terminal profile.

If an old integrated terminal displays `Could not find pty` or cannot attach to
its process, it is a dead VS Code terminal session rather than an application
failure. Use its trash icon to close it, then create a new terminal or run
**Developer: Reload Window**. The dashboard task is independent of that stale
terminal. If VS Code offers `Python: Installing uv...` tasks with no command,
cancel them and use the checked-in `OKai: Setup only` or `OKai: Run dashboard`
tasks, or double-click `run.cmd`; the launcher already installs uv locally
under `.tools\`.

### Manual setup (Python 3.11+)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m src.generate_data     # 1. create data/raw/incidents_raw.csv (510 messy rows)
python -m src.etl               # 2. clean + validate + load into data/processed/signal.db
python -m src.train_model       # 3. train, evaluate, save models/, score every incident
python -m pytest                # 4. run the tests
streamlit run app.py            # 5. open http://localhost:8501
```

You can rerun step 2 any number of times. Incidents are upserted by `incident_id`, so nothing is duplicated, and the dashboard's run history shows `new_incidents = 0` on a rerun.

### Import a supported historical event log

The [event-aware adapter](src/event_ingestion.py) supports the UCI Incident Management Process Enriched Event Log through a named, versioned `UCI_PROFILE`. This is an explicit source contract, not an arbitrary CSV importer. It maps `number` to incident identity, `sys_updated_at` to event time, `sys_mod_count` to source revision, and `made_sla` to a source-reported outcome. Coded categories and groups retain their source meaning; unavailable response times and SLA policies are not manufactured.

```powershell
.\.venv\Scripts\python.exe -m src.event_ingestion --source "C:\path\to\incident_event_log.csv"
# Optional isolated destinations:
.\.venv\Scripts\python.exe -m src.event_ingestion --source "C:\path\to\incident_event_log.csv" --db ".tools\trial\imports.db" --storage ".tools\trial\files"
```

Default storage is separate from the demo: `data/processed/okai_imports.db` and ignored `data/imports/`. The adapter preserves exact original bytes under a SHA-256 name, stores normalized event history, records rejected rows and optional-field warnings, and points each incident to one latest whole event. It orders by event time, revision counter, and source row. Import identity combines the file hash with the **complete mapping-profile fingerprint**; rerunning the same file/profile reuses the import without duplicating history. Another import is a separate cohort, so an older file cannot overwrite the demo or a newer cohort.

The public functions include `import_event_log`, `list_imports`, `read_import`, `read_events`, `read_snapshots`, `read_initial_snapshots`, `read_rejections`, and `event_count`. Earliest observed snapshots are not guaranteed creation-time features. Reusable `MappingProfile` objects record field names, date format, sentinels, priority mapping, version, and timezone; adding a new source requires a validated mapping contract.

Each import attempt records its lifecycle (`preserving`, `parsing`, `validating`,
`normalizing`, `exporting`, `database_write`, `committed`, `failed`, or `interrupted`).
Database fact writes commit atomically, and retries reuse or complete the interrupted
source identity without replacing existing committed imports.

The supplied dataset has no documented timezone. The default therefore preserves source-local clock values with **timezone unknown**, rather than labeling them UTC. If a source owner supplies a named timezone, a profile can localize strictly and convert to UTC; ambiguous or nonexistent daylight-saving times are not silently guessed. Gross elapsed duration with unknown timezone carries that limitation.

See the [case study](docs/CASE_STUDY.md) for independent counts and the denominator correction, and [validation](docs/VALIDATION.md) for actual integration results and separate phase timings.

---

## Portfolio walkthrough

1. Open the app and enter as **Analyst (Alex Morgan)**. The login is a simulated persona selector. Choose **Synthetic demo · Jan–Jun 2024** under **Analysis source**.
2. In **Incident queue**, inspect the top-ranked open incident. Assign an owner, change its review state, and save a handover note.
3. Switch to **Manager (Jordan Lee)** in the sidebar. **Overview > Demo team workload** and **Workspace activity** reflect the saved review immediately.
4. In **Risk lab**, change a creation-time input and inspect the model's contributions. Compare hold-out precision, recall, F1, and ROC-AUC with both baselines.
5. In **Data quality**, inspect rejected rows, validation rules, and run history.
6. In **Project notes**, inspect executable SQL examples, including joins, conditional aggregation, a CTE, and a window function.
7. Switch to **Admin (Casey Brooks)** and use **Reset demo workspace** to restore the original review queue for another walkthrough.

### Real-file evidence walkthrough

1. Open **Import Desk**, upload the supported UCI CSV or choose **Local file on this machine**, inspect the mapping profile, and leave its timezone **unknown** unless a source owner confirms it. Select **Validate and import**.
2. Choose the saved import in **Analysis source** and open **Overview**. Incident count and historical event count are separate; SLA is labeled source-reported.
3. Select **Inspect ↗** below a KPI. In **Calculation Inspector**, compare its formula, numerator/denominator, warnings, and Included/Excluded evidence. The on-screen table previews up to 250 records; the export includes the full selected evidence.
4. In **Incident queue**, explore the imported final snapshots and open an incident's history. This source view is historical; it does not receive demo review writes or synthetic model scores.
5. In **Data quality**, inspect source validation and missing fields. In **Decision Support**, review outcome concentration and configurable investigation rules with an explicit historical review time. **Settings & Governance** explains source, model, tool, access, and value-estimate boundaries.

The independently verified source has **141,712 events**, **24,918 incidents**, and **63.4% source-reported SLA attainment** using final known incident outcomes. Event-weighted counting would misleadingly show 93.5%. These are measured reference results, not embedded application constants; see the [case study](docs/CASE_STUDY.md).

The visual direction uses a warm light canvas, black panels, bold type, an orange band, and original vector connector artwork.

The [OKai wordmark](assets/okai-wordmark.svg) uses a slight italic slant and a fading mirror reflection underneath. Header and sidebar logos return to the demo entry while preserving the workspace URL. The three landing metric cards are full-card shortcuts to data quality, the incident overview, and the risk lab, with thicker 8px colored top edges and visible keyboard focus.

### Working components and simulated components

**Working original walkthrough:** seeded generation, ETL validation, SQLite transactions, SQL metrics, real scikit-learn training/scoring, per-workspace saved reviews and audit events, CSV exports, and reset. Imported data and calculation-engine behavior are documented separately from this simulated company workflow.

**Working source-analysis backend:** event-aware CSV mapping, preserved raw bytes, normalized history, latest whole-row snapshots, idempotent import identity, 16 registered operational/scenario metrics, record eligibility evidence, and a strict read-only calculation tool. The app connects these through source selection, Import Desk, Calculation Inspector, historical incident exploration, and Decision Support. See [validation evidence and remaining limits](docs/VALIDATION.md).

**Simulated:** demo incidents, identities, login, and company operations. A real historical dataset does not make the persona selector production authentication or a security boundary.

Each workspace receives a random UUID in its URL. Refreshing that URL keeps its saved reviews; another workspace gets a separate review queue. Anyone with a workspace URL can enter its simulated personas. Use synthetic or appropriate anonymized public data locally; this app has no access-control or privacy boundary for organizational records.

Review assignments and notes are stored separately from original incident facts and creation-time features. Assigning a new review team does not recalculate a historical SLA outcome or silently alter a model input. Model evaluation remains the original chronological hold-out; displayed incident scores use the final refit on labelled history.

### Skills demonstrated

| Area | Evidence in the project |
|---|---|
| Data analysis | Correct SLA denominators, priority/category/team comparisons, monthly trends, and interpretable charts |
| SQL | Joins, conditional aggregates, CTEs, window functions, upserts, keys, constraints, and transactions |
| Data engineering | Explicit parsing/validation, deterministic inputs, idempotent loads, and rejected-record provenance |
| Machine learning | Creation-time feature selection, chronological hold-out, baseline comparisons, and contribution explanations |
| Software quality | Isolated workspace state, transactional review/event writes, reset tests, CI, and reproducible launch commands |

## Architecture

The [six-layer architecture and initial inventory](docs/ARCHITECTURE.md) distinguishes verified capabilities, baseline gaps, reused components, and deliberate boundaries. Source integration and data foundation feed one calculation service; deterministic rules and read-only explanations consume its results; the UI exposes the same definitions. No separate microservice or unnecessary framework is required.

### Learn the code in this order

The code contains teaching comments explaining both the operation and its reason:

1. [Configuration](src/config.py): shared paths, business policy, and thresholds.
2. [Generation](src/generate_data.py): seeded randomness and deliberately imperfect synthetic inputs.
3. [ETL](src/etl.py): parsing, validation, null outcomes, deduplication, and repeatable loads.
4. [SQL storage](src/database.py): parameterized queries, transactions, joins, and SLA denominators.
5. [Model](src/train_model.py): feature leakage, chronological evaluation, baselines, and final refitting.
6. [Quality report](src/quality.py): why rows, rule matches, and missing cells use different denominators.
7. [Chart system](src/charts.py) and [UI helpers](src/ui.py): semantic colors, count axes, chart framing, and reading notes.
8. [Pages](src/views.py), [app](app.py), and [demo state](src/demo.py): reruns, forms, callbacks, caches, and isolated saved reviews.

For the extended product, read the [calculation engine](src/calculations.py) and [read-only tool contract](src/calculation_tools.py) before the Calculation Inspector view. The [metric reference](docs/METRICS.md) explains all supported definitions and scenario-input requirements.

The quality page has one saved-run selector. Its first chart partitions source rows into loaded, duplicate, and invalid outcomes. Its second counts failed rules across invalid rows, so bars may overlap. Its third counts missing cells per field; missing outcome fields can be valid for open incidents. Every panel states its unit and denominator, and the field audit retains zero counts. Beveled panels frame flat bars without distorting their lengths.

The original synthetic-demo data path remains supported:

```mermaid
flowchart LR
    subgraph Source
        G[generate_data.py<br/>seeded simulator] -->|messy export| RAW[(data/raw/<br/>incidents_raw.csv)]
    end

    subgraph ETL["Data engineering: src/etl.py"]
        RAW --> P[Profile<br/>missing · duplicates]
        P --> V[Validate<br/>timestamps · numbers · status]
        V --> S[Standardize<br/>priority · category]
        S --> C[Derive SLA<br/>target · breached · margin]
    end

    C -->|valid rows · upsert| DB[(SQLite<br/>signal.db)]
    V -->|rejected rows + reason| DB
    C --> CSV[(data/processed/<br/>incidents_clean.csv)]

    subgraph ML["Machine learning: src/train_model.py"]
        DB -->|resolved incidents| F[Creation-time features only]
        F --> SPLIT[Chronological split<br/>past → train · future → test]
        SPLIT --> LR[Logistic Regression]
        SPLIT --> BL[Baselines]
        LR --> EV[Precision · Recall · F1<br/>Confusion matrix · ROC-AUC]
    end

    LR -->|sla_model.joblib · metrics.json| M[(models/)]
    LR -->|breach_probability| DB

    DB -->|SQL metrics| APP[Streamlit dashboard<br/>app.py]
    M --> APP
```

**Database tables:** `incidents` (clean facts) · `predictions` (model scores) · `pipeline_runs` (one row per ETL run) · `rejected_records` (every bad row with its reason and the original row as JSON). The app adds `demo_workspaces`, `demo_reviews`, and `demo_events` for isolated review state and an activity trail.

The separate import database uses `source_imports` (hash, mapping, provenance and phase measurements), `source_events` (history and original row JSON), `source_incidents` (latest whole-event pointers), and `source_rejections` (row-level reasons). Import IDs partition the historical cohorts.

## Authoritative calculation contract

The [OKai Calculation Engine](src/calculations.py) accepts **one latest snapshot per incident**, a separate optional event table, and a `CalculationContext` naming the source, import, timezone, and observation window. Repeated snapshot IDs are rejected rather than silently counted or deduplicated. Its immutable registry defines each metric's purpose, fields, unit, formula, eligibility, missing-value behavior, rounding, validation, and version.

The 16 registered metrics cover distinct incidents, valid events, resolved rate, source and demo SLA attainment, mean/median gross duration, assignment/field completeness, unresolved/high-priority counts, and supplied processing/cost scenarios. Every result includes availability, value/unit, window/source, eligible/excluded counts, formula version, calculation time, warnings, and assumptions. Unknown or unsupported inputs remain unavailable. See [all formulas and parameters](docs/METRICS.md).

Once a caller has constructed an engine for its selected dataset, it uses the same functions as the dashboard:

```python
result = engine.calculate("source_sla_attainment").to_dict()
evidence = engine.inspect("source_sla_attainment")
# evidence contains the definition, result, and record-level membership/reasons.
```

The [internal read-only tool](src/calculation_tools.py) supports only `list_metrics`, `calculate`, `inspect`, and `alerts`. A caller supplies an already-authorized engine; requests cannot select a file path, run SQL, change data, train a model, or access an external service. Unknown request fields and invalid parameters produce validation errors. This is an ordinary Python interface, not an external API deployment, MCP server, or connected LLM.

Threshold alerts are configurable investigation rules. Age/deadline checks require an explicit historical `as_of`; real SLA deadline evidence must come from the source. Cost and efficiency formulas require supplied matched-scope inputs. Estimated labor capacity value is not evidence of realized cash savings.

---

## Components: what each does, why it exists, what it depends on

| File | What it does | Why it exists | Depends on |
|---|---|---|---|
| `src/config.py` | Paths, synthetic SLA policy, valid values, risk bands | Shared configuration for the original demo; imported source outcomes remain separate | nothing |
| `src/generate_data.py` | Simulates 500 incidents and then makes the export messy | We need realistic data with known problems to prove the pipeline works | numpy, pandas, config |
| `src/etl.py` | Extract → profile → dedupe → validate → standardize → derive SLA → load | Raw data is never trusted. This is the gate between "export" and "fact" | pandas, database, config |
| `src/event_ingestion.py` | Preserve source bytes, apply a mapping profile, normalize events, and build latest whole-row snapshots | Supports real historical event grain without replacing the demo or discarding lifecycle updates | pandas, sqlite3, Python standard library |
| `src/database.py` | Incident schema, upserts, pipeline run logging, and historical SQL metrics | Keeps source facts and analytical queries together; demo writes are separate | sqlite3 (built in), pandas |
| `src/train_model.py` | Feature engineering, leakage guard, chronological split, training, evaluation, explanations, scoring | Turns history into a forward-looking risk estimate | scikit-learn, joblib, database |
| `app.py` | Demo persona entry, navigation, cached facts/model, and workspace identity | Connects the portfolio walkthrough | streamlit, database, demo, ui, views |
| `src/views.py` | Overview, Incident queue, Risk lab, Data quality, and Project notes | Interactive analysis, reviews, model evidence, and executable SQL | streamlit, plotly, database, demo, train_model |
| `src/intelligence_views.py` | Source selection, authoritative overview, Import Desk, Calculation Inspector, historical exploration, Decision Support, and governance | Connects existing walkthroughs to the new calculation/import contracts without repeating business formulas | streamlit, event_ingestion, calculations, calculation_tools, ui |
| `src/ui.py` | Reusable layout, charts, typography, and vector artwork | Consistent presentation | streamlit, plotly |
| `src/demo.py` | Workspace-scoped review writes, audit events, summaries, and reset | Persists demo actions without rewriting source facts | database, pandas |
| `src/quality.py` | Reconciles run counts and prepares chart denominators | Separates source rows, overlapping rule matches, and per-field missing cells | pandas |
| `src/charts.py` | Shared chart theme and quality figures | Consistent units, readable labels, zero baselines, and semantic colors | plotly, quality |
| `src/calculations.py` | Metric registry, structured results, record eligibility, and deterministic thresholds | One authoritative calculation implementation shared by the dashboard, inspector, and tools | pandas, Python standard library |
| `src/calculation_tools.py` | Strict read-only metric listing, calculation, inspection, and alert requests | A validated internal explanation boundary without an external AI dependency | calculations |
| `src/design.py` | Named color, geometry, font, category, and slogan tokens | One shared visual vocabulary for cards, charts, and product language | nothing |
| `tests/` | Pytest checks | Proves ETL, SQL, model inputs, workspace isolation, quality denominators, saved reviews, and reset | pytest |

---

## Data generation rules

Seed `42`. Re-running the generator always produces the same file.

**Incidents (500, Jan to Jun 2024)**
- **Creation time:** a random day, with about 60% of weekend tickets pushed to Monday or Tuesday. 75% fall in business hours (08:00–17:59) and the rest overnight or in the evening.
- **Priority mix:** Critical 5% · High 15% · Medium 45% · Low 35%.
- **SLA resolution targets:** Critical 240 min · High 480 · Medium 1,440 · Low 4,320.
- **Category mix:** Software 28% · Access 18% · Hardware 16% · Network 16% · Email 12% · Database 10%. Each category has its own services (for example, Database → Data Warehouse / ERP / CRM).
- **Assignment group:** the category's specialist team, except that 15% of non-Email tickets are left with the **Service Desk** (misrouted).
- **Response time:** log-normal around a priority median (10 / 25 / 90 / 300 min).
- **Resolution time:** `SLA target × priority ratio × risk factors × log-normal noise`. These are the hidden drivers, and all of them are known at creation:

  | Driver | Multiplier |
  |---|---|
  | Category: Database / Network / Software / Hardware / Email / Access | 1.35 / 1.15 / 1.10 / 1.00 / 0.85 / 0.80 |
  | Service: ERP, Data Center / Data Warehouse | 1.20 / 1.15 |
  | Misrouted to Service Desk | 1.30 |
  | Created off-hours (before 08:00 or from 18:00) | 1.35 |
  | Created on a weekend | 1.40 |

- **Status:** the 25 most recent tickets are `Open` or `In Progress`, with no resolution time and an unknown outcome. The rest are `Closed` (70%) or `Resolved` (30%).
- **Outcome:** `sla_breached = resolution > target`. The result is about a 21% breach rate.

**Injected data-quality problems** (so the ETL has real work to do)

| Problem | Rows | ETL action |
|---|---|---|
| Exact duplicate rows | 10 | removed (keep first) |
| Missing priority | 5 | rejected |
| Missing category | 3 | rejected |
| Invalid timestamp (`2024-13-45`, `not a date`, …) | 4 | rejected |
| Negative response time | 4 | rejected |
| Non-numeric response time (`N/A`) | 3 | rejected |
| Resolution shorter than response | 3 | rejected |
| Priority spelling variants (`P1`, `critical`, `med`, …) | ~40 | standardized |
| Category variants (`H/W`, `DB`, `E-mail`, …) | ~40 | standardized |
| Padded whitespace in team names | 15 | trimmed |

Result: **510 rows read → 478 loaded, 32 rejected** (10 duplicates + 22 invalid). The raw file stays untouched in `data/raw/`. The cleaned copy is in `data/processed/incidents_clean.csv`.

---

## ETL design decisions

- **Read structural fields as text, then parse explicitly.** The demo reader may still recognize pandas' default missing-value markers; timestamps and numeric values are validated with explicit rules. An external source's additional sentinels, such as `?`, belong to its mapping profile rather than a guessed global rule.
- **Every rule has a reason string.** A row that fails three rules lists all three, joined by `; `.
- **Synthetic SLA targets come from the declared demo policy.** The original demo pipeline recomputes `sla_target_minutes` and `sla_breached` from that policy. This is not a rule for external imports: UCI `made_sla` must remain a qualified source-reported outcome, not be overwritten using the demo targets.
- **Open incidents are valid.** Their blank resolution time is expected and their outcome is `NULL` (unknown), never "met".
- **Idempotent load.** `INSERT … ON CONFLICT(incident_id) DO UPDATE` means a rerun updates rows in place. A ticket that was open last run and is closed now gets updated, not duplicated.
- **One transaction per load.** Incidents, rejected records and the run summary are committed together or not at all.

---

## Machine learning design

**Target:** `sla_breached` (1/0), on resolved incidents only.

**Inputs (creation-time only):** priority, category, affected service, assignment group, `shift` (business hours / evening / overnight from the creation hour), and `is_weekend`.

**Excluded to prevent leakage:** resolution time, response time, status, SLA margin and the outcome. All of these happen *after* the ticket is opened. `build_features()` selects only the allowed columns and asserts that no leakage column got through, and a test enforces this.

**Split:** chronological. The oldest 80% is used for training (Jan 1 → May 18) and the newest 20% for testing (May 20 → Jun 20). This evaluates later synthetic arrivals; it does not simulate historical label availability. Equal creation timestamps can straddle the cut. Imported-event evaluation additionally needs incident grouping and point-in-time source validation.

**Model:** one-hot encoding → `LogisticRegression(class_weight="balanced")`. Balancing stops the model from ignoring the ~20% minority class. The trade-off is that scores lean high, so the dashboard presents them as **relative risk estimates**.

**Results on the hold-out test set** (91 incidents, 19% breached):

| Model | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|
| **Logistic Regression** | 0.370 | **0.588** | **0.455** | **0.774** |
| Baseline: flag priorities that breach above average | **0.429** | 0.353 | 0.387 | 0.612 |
| Baseline: always predict "no breach" | 0.000 | 0.000 | 0.000 | 0.500 |

How to read this:
- The model **ranks risk much better** (AUC 0.77 vs 0.61) and **catches more breaches** (59% vs 35%).
- The priority rule is **slightly more precise**: when it raises an alarm it is right more often, but it misses most breaches.
- The "always no" model scores 81% *accuracy* and catches **zero** breaches. That is why accuracy isn't reported.
- 91 test rows is a small sample, so these numbers would move by several points with different data.

**Coefficients, and why they are not causes.** The dashboard plots each feature's weight. Positive weights push the estimate up. The generator gave Hardware a neutral 1.0× factor, yet the model assigns `category = Hardware` a *positive* weight. That happens because Hardware tickets are compared against a mix of baseline categories, share credit with their team (Desktop Support, which gets a large negative weight), and the sample is small. Coefficients describe patterns in this history. They do not tell you what to change.

---

## Dashboard

| Tab | What you get |
|---|---|
| **Overview** | Calculation-engine metrics and source scope, incident/event distinction, priority/month comparisons, inspect links, and demo workspace workload/activity |
| **Incident queue** | Synthetic source: saved risk-ranked reviews, notes, and activity. Imported source: final incident snapshots and preserved event timelines |
| **Import Desk** | Supported UCI profile, file upload/local path, explicit timezone, mapping inspection, validation/import evidence, and source history |
| **Calculation Inspector** | Registry definition, authoritative result, numerator/denominator, eligibility/exclusions, technical provenance, scenario inputs, and evidence export |
| **Decision Support** | Configurable investigation rules with explicit review time, source evidence, outcome concentration, and limits on causal interpretation |
| **Risk lab** | Synthetic-source what-if scorer, contributions, model/baseline metrics, confusion matrix, ROC curve, and coefficients; imported snapshots are explicitly not scored |
| **Data quality** | Demo saved-run quality panels or selected import validation/missing-value/rejection evidence, with explicit counting units |
| **Settings & Governance** | Source settings, numerical authority, tool/result contracts, model and access boundaries, and value-estimate limitations |
| **Project notes** | Data lineage, executable SQL examples, skills demonstrated, reproducibility instructions, and simulation/model limitations |

Design: warm paper `#F7F6F3`, black panels, orange `#FF512B`, pink display typography, and purple/cyan/green connector lines. Risk bands are always written out (Low / Medium / High), so the meaning never relies on color alone. The interface uses system fonts and an original SVG asset; it requires no external image or font service.

---

## Project layout

```
├── app.py                    Streamlit dashboard
├── requirements.txt
├── pytest.ini
├── .streamlit/config.toml    light theme
├── src/
│   ├── config.py             paths + business rules
│   ├── generate_data.py      synthetic incident simulator
│   ├── etl.py                validation + cleaning pipeline
│   ├── event_ingestion.py    mapping, raw provenance, events, snapshots
│   ├── database.py           SQLite schema, writes, SQL metrics
│   ├── calculations.py       registry, results, evidence, deterministic rules
│   ├── calculation_tools.py  strict read-only interpretation interface
│   ├── train_model.py        features, training, evaluation, scoring
│   ├── demo.py               isolated review state and audit trail
│   ├── quality.py            reconciled quality measures and denominators
│   ├── charts.py             shared chart theme and quality figures
│   ├── design.py             shared color, geometry, typography, brand tokens
│   ├── ui.py                 presentation helpers
│   ├── views.py              original queue, model evidence, SQL notes
│   └── intelligence_views.py source-aware analysis and calculation inspection
├── data/
│   ├── raw/                  incidents_raw.csv (committed, reproducible)
│   ├── processed/            signal.db, okai_imports.db, demo CSVs (generated)
│   └── imports/              exact raw copies, rejection/warning exports (ignored)
├── models/                   sla_model.joblib, metrics.json (generated)
├── assets/                   connector and reflected wordmark SVGs
├── docs/                     architecture, metrics, case study, brand, validation
└── tests/                    ETL, database, model, and demo workspace tests
```

## Limitations and next milestone

- The model's data is synthetic. Its patterns exist because the generator put them there; its score is not real-world predictive validation.
- About 450 labelled synthetic rows is a small sample. Class-weighted scores are uncalibrated and useful for relative ranking rather than exact odds.
- The supplied UCI file is historical and all final incident states are Closed. It supports retrospective process investigation, not a live backlog.
- Source-reported SLA outcomes are not independently verified contractual compliance. Actual response time, business calendars, pause rules, source timezone, financial costs, and causal savings cannot be invented.
- Persona login is simulated. SQLite is local, permits multiple readers and serializes writes, and has not been workload-tested for organizational deployment. No backup/restore, retention, real access control, or enterprise certification is established.
- Minimum-version dependencies provide a simple local setup, not a locked deployment environment.

The next milestone is a **validated source contract and measured operational trial**: agree on timestamp/SLA semantics with a source owner, establish access and retention controls, define an investigation workflow, and measure its outcomes. A future database, worker, identity provider, or AI integration should follow a demonstrated requirement. Migrating to a managed platform would require compatibility and workload testing; the SQL and rules are not assumed to port unchanged.

## Dataset attribution

The optional real-file validation uses Amaral, C., Fantinato, M., & Peres, S. (2018), *Incident management process enriched event log*, UCI Machine Learning Repository, [DOI: 10.24432/C57S4H](https://doi.org/10.24432/C57S4H), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). OKai adds validation, normalization, snapshots, and analysis. The raw third-party CSV is not committed to this repository.
