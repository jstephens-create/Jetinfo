# OKai roadmap and phase status

Tracks the persistent-operational-intelligence milestone described in the
working agreement. Status reflects the repository at commit `bf05627` plus the
review-export addition documented in [validation](VALIDATION.md). This file
records engineering status, not a product release schedule.

| Phase | Scope | Status |
|---|---|---|
| A. Repository and runtime audit | Inspect existing architecture, classify capabilities, establish a verified test baseline | **Done** — full suite 200 passed / 1 skipped (201 passed / 0 skipped with the optional real-file test enabled; see independent verification below) |
| B. Database integrity and relationship analysis | Actual + proposed ERD, integrity rule review | **Done** — see [data model](DATA_MODEL.md), now including a fully specified operational-action lifecycle (state machine, validation rules, approval, auditability) |
| C. Minimal persistent review implementation | Import → investigation → persistent review → restart → reopen | **Already implemented** (`src/investigations.py`, commit `bf05627`); independently re-verified against **both** the demo source and a real imported (UCI event-log) source, each across two independent processes |
| D. Evidence attachment and export integration | Attach evidence to a proposed action; export a traceable review summary | **Action attachment: minimal (free-text `next_action`), done.** **Review export: implemented, independently verified this session** (`investigations.build_review_export`) |
| E. Regression, browser verification, documentation | Full suite, live server smoke check, docs | **Partial** — full suite, live HTTP health check, and a genuine fresh-recomputation reconciliation all passed; no real-browser (Playwright) click-through was available in this environment (confirmed absent again this session; see below) |

## Independent verification (this session)

An independent reviewer pass (separate from the implementer session above)
re-ran and extended verification rather than trusting the prior report:

- **Git diff scope**: confirmed the working tree still contains exactly the
  originally reported changed files; no unrelated modifications.
- **Code audit of `build_review_export`**: confirmed it performs no new
  arithmetic, reads only already-persisted/immutable fields, and is purely
  additive. One **minor stylistic inconsistency** found (not a bug): it
  passes `sort_keys=True` to `json.dumps`, while
  `calculation_tools.build_calculation_evidence_export` does not. Both are
  deterministic either way; this only affects byte-for-byte diffability of
  repeated exports, not correctness.
- **Previously skipped UCI test investigated and run**: the real dataset was
  located locally and used to run the full suite with `OKAI_UCI_CSV` set:
  **201 passed, 0 skipped in 94.45s** — a genuine zero-skip baseline,
  independently confirming the previously reported count rather than
  assuming it.
- **Full imported-source workflow re-verified end-to-end**, which the prior
  session had not independently covered for the imported source specifically
  (only demo-source restart persistence had been manually driven): import the
  real 46,212,397-byte UCI file into an isolated database → inspect
  `source_sla_attainment` (63.4%, 24,918 eligible, 0 excluded — matching the
  previously documented figures exactly) → create an investigation against a
  real incident (`INC0000045`) → **end that process** → **start a brand-new
  process** → reopen the saved review, confirm decision fields unchanged →
  record an outcome → export → **reconcile the exported trace against a
  freshly recomputed `CalculationEngine.inspect()` call in that same new
  process** (not a re-read of the stored row) → identical result. See
  [validation](VALIDATION.md) for the full evidence.
- **Duplicate/negative/immutability checks repeated on the imported-source
  database**: reusing the same trace for a second investigation did not
  duplicate the `calculation_traces` row; an invalid outcome status was
  rejected with no side effects; direct SQL `UPDATE`/`DELETE` against
  `calculation_traces`, `investigation_events`, and `investigations` decision
  fields were all rejected by the existing triggers.
- **Documentation-vs-code consistency pass**: spot-checked claims in
  `README.md` and `docs/ARCHITECTURE.md` against `src/investigations.py`
  (schema columns, `next_action`, file map) — no inconsistencies found beyond
  the `sort_keys` note above.
- **Phase 2 (live browser verification) could not be completed.** No
  Playwright or other browser-automation MCP tool is connected in this
  environment (confirmed via a tool search; zero results). Per the explicit
  instruction that an HTTP 200 or `AppTest` pass alone does not constitute
  browser verification, this phase is reported as **unverified / blocked**,
  not claimed as done. The strongest available substitute evidence is the
  backend-level, cross-process workflow above plus the existing `AppTest`
  coverage in `tests/test_app_workflows.py` — explicitly not a substitute for
  an actual rendered-page click-through.

## What changed this session

- Added `investigations.build_review_export`: a JSON export (`okai.investigation-review-export.v1`)
  joining an investigation's decision fields, reported outcome, immutable
  calculation trace, and append-only audit history into one file that
  reconciles with what the Calculation Inspector displayed when the trace was
  created.
- Added an "Export review summary ↓" download button to the Investigations
  workbench's "Follow-up outcomes" view.
- Added two focused tests (`tests/test_investigations.py`) proving the export
  reconciles with the stored trace and handles the no-history case.
- Updated `docs/ARCHITECTURE.md`, `docs/VALIDATION.md`, and
  `docs/GUIDED_FLOWS.md`, which had not yet caught up to the `investigations.py`
  module already on `main`.

## Known gaps / next milestone candidates

1. **Structured operational action lifecycle.** Today's `next_action` is a
   free-text field satisfying "minimum necessary action attachment." The next
   milestone should add `operational_actions`/`action_events` tables, now
   with a fully specified state machine, transition validation rules,
   ownership/no-self-approval rule, due-date semantics, and auditability (see
   [data model](DATA_MODEL.md)'s "Proposed target: structured operational
   actions" section), without changing any existing table. **This is the
   recommended next implementation assignment for GitHub Copilot** — design
   only has been completed; implementation was explicitly deferred per this
   session's instructions.
2. **Real-browser interactive verification remains unresolved across two
   sessions.** This environment still has no Playwright/browser automation
   tool connected (re-confirmed by an independent tool search this session).
   Verification instead relied on the project's own Streamlit `AppTest`
   harness plus cross-process backend workflow checks, which the user's own
   instructions explicitly state do not constitute browser verification. This
   is the most significant outstanding risk against the milestone's
   acceptance criteria and should be resolved (by connecting a browser tool,
   or by a human performing the click-through) before this is called
   complete.
3. **Minor stylistic inconsistency**: `investigations.build_review_export`
   passes `sort_keys=True` to `json.dumps`; the older
   `calculation_tools.build_calculation_evidence_export` does not. Not a
   correctness bug; worth aligning for consistency in a future small cleanup.
4. **Cross-file import freshness.** Each import remains its own immutable
   cohort, as documented in validation's "known reliability boundaries";
   incremental/CDC ingestion remains out of scope.
5. **Durable import-attempt ledger / retry workload testing** remain
   unaddressed, as previously documented.

## Independent review

An independent reviewer pass (this session) re-verified the implementer
session's three changed files (`src/investigations.py`,
`src/intelligence_views.py`, `tests/test_investigations.py`) plus
documentation, using fresh evidence rather than re-reading prior claims:
confirmed git diff scope, re-ran the full suite with the real UCI file
enabled (201 passed / 0 skipped), and independently drove the entire
import → investigate → restart → reopen → outcome → export → reconcile
workflow against the real dataset for the imported source specifically (the
one path the implementer session had not manually covered end-to-end). See
"Independent verification (this session)" above and
[validation](VALIDATION.md) for full evidence. Codex remains assigned to
review the same file set and this session's documentation updates; see
[agent handoff](AGENT_HANDOFF.md).
