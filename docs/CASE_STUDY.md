# Case study: when the denominator changes the decision

## Problem and source

A dashboard can parse a CSV correctly and still report the wrong business result. OKai's initial synthetic contract had one record per incident, so a repeated incident ID was treated as a duplicate. The UCI Incident Management Process Enriched Event Log instead contains multiple historical events per incident. Its audit records are enriched from a relational database, missing values mean unknown information, and descriptive text is omitted. [UCI dataset documentation](https://archive.ics.uci.edu/dataset/498/incident%2Bmanagement%2Bprocess%2Benriched%2Bevent%2Blog)

That distinction changes both the unit counted and the point in time represented. Renaming columns to fit the original demo would not solve it. Keep-first deduplication would lose later events, while counting every event as a ticket would weight incidents by the number of updates they generated.

## Independently computed reference

The source supplied for this local test was `incident_event_log.csv`, **46,212,397 bytes**, with SHA-256:

```text
fd184bbfd62329cfe093e99da2ea7071905f2ead91900b448eb2635870821bef
```

An independent Python standard-library `csv` scan—not the application adapter or pandas aggregation—counted events and selected the latest whole row for each incident. Ordering was parsed `sys_updated_at`, numeric `sys_mod_count`, then original source row position. It did not forward-fill columns or assemble a hybrid record from different events. These figures were recomputed from the local bytes rather than embedded as application constants.

| Reference measure | Recomputed result |
|---|---:|
| Historical event records | 141,712 |
| Unique incident IDs | 24,918 |
| Final incidents with unknown resolution timestamp | 1,556 |
| Final incidents with unknown assignment group | 2,157 |
| Final incidents in Closed state | 24,918 |
| Events already containing a resolution timestamp later than their update timestamp | 87,471 |

The last result shows why an event's nonnull final outcome timestamp is not proof that the value was available when that event occurred. This data is suitable for retrospective analysis; an imported latest snapshot must not become creation-time predictive input without separate availability validation.

## Incorrect and correct populations

| Method | Source flag true | Source flag false | Eligible population | Reported attainment |
|---|---:|---:|---:|---:|
| Incorrect for ticket reporting: count each historical event | 132,497 | 9,215 | 141,712 events | 93.4974% |
| Incident reporting: latest whole-row outcome per incident | 15,803 | 9,115 | 24,918 incidents | 63.4200% |

```text
Source-reported SLA attainment
  = latest eligible incidents with made_sla = true
    / latest eligible incidents with known made_sla
    × 100
  = 15,803 / 24,918 × 100
  = 63.4200…%
```

The event-weighted answer appears **30.0774 percentage points higher**. It describes update records rather than distinct incidents. It could lead a reviewer to overlook the size of an outcome problem. Missing SLA flags, when present in another import, must be excluded from the known-outcome denominator and disclosed; they cannot silently become success or failure.

## SLA semantics and missing evidence

OKai labels this metric **source-reported SLA attainment**, not verified contractual compliance. ServiceNow documents Made SLA as a legacy task field with opposite polarity to Has breached; current Task SLA processing does not maintain those legacy fields. That documentation supports cautious labeling rather than proving how this historical installation was configured. [ServiceNow legacy SLA fields](https://www.servicenow.com/docs/r/it-service-management/service-level-management/c_LegacySLAFields.html)

The file supplies neither the complete policy/calendar nor pause rules, holidays, business timezone, applicable SLA versions, and acknowledgment events. Therefore:

- Valid resolved-minus-opened intervals describe gross elapsed duration, not contractual business time.
- The 1,556 missing final resolution timestamps are excluded from duration metrics and visible as exclusions.
- The 2,157 unknown final assignment groups remain in an explicit Unknown bucket rather than disappearing from team reporting.
- There is no defensible first-response time, verified deadline, actual cost, realized saving, or real-time open backlog to infer from this file alone.
- Category and group codes are anonymized. Their names do not reveal the underlying department or technical cause.

## Engineering response and business use

The architecture separates preserved raw files, historical events, deterministic latest incident snapshots, and centralized calculation results. Import identity and calculation version make a displayed result traceable. The Calculation Inspector is the review surface for its formula, unit, numerator/denominator, eligible and excluded records, and assumptions. See the [architecture inventory](ARCHITECTURE.md), [metric reference](METRICS.md), and [validation results](VALIDATION.md) for implementation evidence rather than treating the design as proof of completion.

A defensible next action is a historical investigation: identify categories with many source-reported misses, inspect reassignment patterns and missing assignment data, validate the underlying source/SLA definitions with an owner, and measure a prospective intervention. A final-team association is not proof that a team caused delay. A historical pattern is not evidence of savings or model generalization.

For an entry-level data portfolio, the result is a concrete demonstration of grain, denominator selection, data lineage, SQL/Python testing, and honest interpretation. The visible improvement is reproducible reporting and preserved history. Business savings remain unmeasured.

## Attribution

Amaral, C., Fantinato, M., & Peres, S. (2018). *Incident management process enriched event log* [Dataset]. UCI Machine Learning Repository. [https://doi.org/10.24432/C57S4H](https://doi.org/10.24432/C57S4H). The dataset is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). OKai adds normalization, incident-snapshot construction, and analysis; these transformations are not authored or endorsed by the dataset creators.
