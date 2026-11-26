# Agent handoff: GitHub Copilot → Codex

This file is the canonical engineering contract for this milestone, per
`AGENTS.md`'s working agreement. GitHub Copilot is the primary implementation
agent; Codex is the independent architecture, data integrity, and QA
reviewer. Keep one writer per work package; use separate branches/worktrees
for concurrent agent activity. Do not merge into `main` automatically.

## What to review

Session scope: one additive change on top of commit `bf05627` ("Add
evidence-linked investigation workflows"), which already implemented the
import → investigation → persistent review → reopen lifecycle described in
the milestone brief. This session's contribution closes the one clear
remaining gap against the stated acceptance criteria: **exporting a traceable
review summary**.

### Changed files

| File | Change |
|---|---|
| `src/investigations.py` | Added `REVIEW_EXPORT_SCHEMA` and `build_review_export(investigation, events)`, producing a versioned JSON export of a saved investigation's decision fields, reported outcome, immutable trace, and audit history |
| `src/intelligence_views.py` | Added an "Export review summary ↓" `st.download_button` to the Investigations workbench's "Follow-up outcomes" view |
| `tests/test_investigations.py` | Added `test_review_export_reconciles_with_the_stored_trace_and_history` and `test_review_export_omits_history_when_no_events_are_supplied` |
| `docs/ARCHITECTURE.md`, `docs/VALIDATION.md`, `docs/GUIDED_FLOWS.md` | Caught up documentation to the already-merged `investigations.py` module, and recorded the new export |
| `docs/DATA_MODEL.md`, `docs/ROADMAP.md`, `docs/AGENT_HANDOFF.md` (this file) | New: actual + proposed ERD, phase status, and this handoff |

### Specific things to verify independently

1. **No new arithmetic.** `build_review_export` must only reshape already-stored
   fields (`investigation` dict from `read_investigation`, the parsed
   `trace_json`, and `events` from `read_events`). Confirm it performs no
   recalculation and cannot diverge from what `create_investigation` stored.
2. **Immutability is preserved.** Confirm the export reads from
   `calculation_traces`/`investigation_events`, both of which have `BEFORE
   UPDATE`/`BEFORE DELETE` triggers raising `ABORT` (see schema in
   `src/investigations.py`). The export function itself performs no writes.
3. **No format-string/formula-injection surface.** The export is JSON, not
   CSV; there is no spreadsheet formula-injection vector to guard against
   (unlike the CSV exports elsewhere in `intelligence_views.py`, which this
   change does not touch).
4. **Regression evidence.** Full suite: 200 passed, 1 skipped (the skip is the
   pre-existing opt-in real-UCI-file test, unaffected by this change).
   Targeted: `tests/test_investigations.py` 7/7 passed.
5. **Production data safety.** This session never wrote to
   `data/processed/signal.db` or `data/processed/okai_imports.db`. All
   persistence verification used a `tempfile`-copied database, reconfirmed
   with a fresh SQLite connection in an independent Python process (simulating
   an application restart) before being deleted.

## Conventions to preserve

- One SQLite connection context manager per logical transaction
  (`src/database.py:connect`); never partially commit related rows.
- Immutable/append-only tables use SQLite `BEFORE UPDATE`/`BEFORE DELETE`
  triggers that `RAISE(ABORT, ...)`, not just application-level discipline.
- Export payloads are versioned JSON schemas (`okai.*.v1`) with an
  `exported_at_utc` timestamp, following `calculation_tools.build_calculation_evidence_export`.
- Dark operational-intelligence visual language, orange accents, and existing
  `ui.py`/`design.py` tokens — this change added no new UI chrome beyond one
  `st.download_button` using the existing pattern from the Calculation
  Inspector.

## Out of scope for this session (do not assume implemented)

- A structured `operational_actions`/`action_events` lifecycle — now fully
  *designed* (state machine, transition validation, approval, auditability)
  in `docs/DATA_MODEL.md`, but **not implemented**. This is the recommended
  next assignment.
- Real-browser (Playwright) interactive verification — no such tool was
  connected in this environment; confirmed absent in **two** independent
  sessions now (implementer and reviewer). See `docs/ROADMAP.md` known gaps.
- Any change to the UCI event-ingestion contract, the synthetic model, or
  demo-workspace reset behavior.

## Independent reviewer findings (this session)

A second, independent session re-verified the above rather than trusting the
implementer's report, with the following results:

1. **Git diff scope**: reconfirmed clean — exactly the files listed above,
   no unrelated changes.
2. **`build_review_export` correctness**: confirmed no new arithmetic, reads
   only immutable/append-only stored data, purely additive. Found one minor,
   non-functional inconsistency: it uses `json.dumps(..., sort_keys=True)`
   while `calculation_tools.build_calculation_evidence_export` does not.
   Worth aligning later; does not affect correctness or reconciliation.
3. **Skipped UCI test**: investigated and resolved. The real dataset exists
   locally; with `OKAI_UCI_CSV` set, the full suite ran **201 passed, 0
   skipped in 94.45s**, independently confirming the implementer's reported
   200/1-skipped baseline is the correct *default* state (the real-file test
   is intentionally opt-in, not a defect).
4. **Imported-source full-cycle verification (new coverage)**: the
   implementer session only manually drove restart-persistence for the demo
   source; this session independently drove the complete workflow for a real
   imported UCI source across two separate OS processes — import, SLA
   inspection, investigation creation, restart, reopen, outcome recording,
   export, and reconciliation against a **freshly recomputed** engine result
   (not a re-read of the stored value). All values matched exactly: 63.4%
   SLA attainment, 24,918 eligible / 0 excluded. Duplicate-trace reuse,
   invalid-status rejection, and all three immutability triggers were also
   re-confirmed against this imported-source database. Full detail in
   `docs/VALIDATION.md`.
5. **Documentation-vs-code consistency**: spot-checked `README.md` and
   `docs/ARCHITECTURE.md` claims against `src/investigations.py`; no
   inconsistencies found.
6. **Phase 2 (live browser verification): blocked, explicitly unresolved.**
   No Playwright/browser-automation MCP tool is connected in this
   environment (confirmed via tool search). This does not satisfy the stated
   bar that "an HTTP 200 response or Streamlit AppTest alone does not
   constitute successful browser verification." This is the top remaining
   risk before the milestone can be called fully verified.
7. **Phase 3 (operational-action architecture)**: designed, not implemented,
   in `docs/DATA_MODEL.md` — full PK/FK layout, a `draft → approved →
   in_progress → completed/dismissed` state machine with a transition
   validation table, a no-self-approval rule for approvals, advisory-only due
   dates, and an append-only `action_events` audit trail mirroring
   `investigation_events`. Recommended smallest slice: two new tables plus
   `propose_action`/`transition_action`/`read_actions` functions, surfaced as
   a panel inside the existing Investigations workbench — no new page, no
   change to `investigations`/`calculation_traces`.

### Next assignment for GitHub Copilot

Implement the smallest slice from `docs/DATA_MODEL.md`'s "Recommended
smallest implementation slice": `operational_actions` + `action_events`
tables (additive, same immutability-trigger convention), one
creation/transition/read function set, and one read-mostly panel in the
Investigations workbench. Do not automate any transition and do not change
`investigations`/`calculation_traces`. Resolve the `sort_keys` stylistic
inconsistency opportunistically if convenient. Live browser verification
remains the standing, unresolved blocker for both sessions to date — raise it
if a browser-automation tool becomes available.
