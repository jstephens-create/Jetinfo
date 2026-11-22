"""Persistent, isolated demo workspaces layered over the original incident facts.

The personas simulate a product workflow; they are not production authentication.
Reviewing an incident never changes its creation-time model inputs or SLA outcome.
Instead, a workspace stores a small overlay of assignments, owners, and notes.
That separation lets several walkthroughs share the same analytical source data.
"""
import json
from uuid import UUID

import pandas as pd

from src import database
from src.config import DB_PATH

PROFILES = {
    "Analyst": {"name": "Alex Morgan", "title": "Service desk analyst", "initials": "AM"},
    "Manager": {"name": "Jordan Lee", "title": "Operations manager", "initials": "JL"},
    "Admin": {"name": "Casey Brooks", "title": "Data administrator", "initials": "CB"},
}
OWNERS = ["Unassigned"] + [profile["name"] for profile in PROFILES.values()]
REVIEW_STATES = ["Unreviewed", "In review", "Escalated", "Monitoring"]

# The composite review key allows one review per incident *per workspace*. Events
# reference that same pair, so resetting reviews can also remove their history.
SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_workspaces (
    workspace_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    reset_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS demo_reviews (
    workspace_id TEXT NOT NULL REFERENCES demo_workspaces(workspace_id),
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    review_state TEXT NOT NULL CHECK (review_state IN ('Unreviewed','In review','Escalated','Monitoring')),
    assigned_team TEXT NOT NULL,
    owner TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_actor TEXT NOT NULL,
    PRIMARY KEY (workspace_id, incident_id)
);
CREATE TABLE IF NOT EXISTS demo_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    note TEXT NOT NULL,
    FOREIGN KEY (workspace_id, incident_id)
        REFERENCES demo_reviews(workspace_id, incident_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS demo_events_workspace ON demo_events(workspace_id, event_id);
"""

# LEFT JOIN keeps an open incident even when it has no score or saved review.
# COALESCE chooses the first non-NULL value: an overlay wins when it exists,
# otherwise the queue displays source/default values without copying every row.
# The two ? placeholders both receive the workspace ID (notes and review join).
QUEUE_SQL = """
SELECT i.incident_id, i.created_at, i.priority, i.category, i.affected_service,
       i.assignment_group, i.status, i.sla_target_minutes,
       p.breach_probability, p.risk_level,
       COALESCE(r.review_state, 'Unreviewed') AS review_state,
       COALESCE(r.assigned_team, i.assignment_group) AS assigned_team,
       COALESCE(r.owner, 'Unassigned') AS owner,
       r.updated_at, r.last_actor,
       (SELECT COUNT(*) FROM demo_events e
        WHERE e.workspace_id = ? AND e.incident_id = i.incident_id AND e.note != '') AS note_count
FROM incidents i
LEFT JOIN predictions p ON p.incident_id = i.incident_id
LEFT JOIN demo_reviews r ON r.incident_id = i.incident_id AND r.workspace_id = ?
WHERE i.sla_breached IS NULL AND i.status IN ('Open', 'In Progress')
"""


def validate_workspace_id(workspace_id: str) -> str:
    """Parse a URL identifier into one consistent UUID format, or raise ValueError.

    A UUID identifies demo data; it grants no verified user identity or security.
    """
    return UUID(workspace_id).hex


def ensure_workspace(workspace_id: str, db_path=DB_PATH) -> str:
    """Create tables/workspace if absent, making repeated reruns harmless."""
    workspace_id = validate_workspace_id(workspace_id)
    with database.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Bind values separately from SQL syntax. A value containing a quote is
        # still data, not executable SQL; use this pattern for all user input.
        conn.execute("INSERT OR IGNORE INTO demo_workspaces (workspace_id, created_at) VALUES (?, ?)",
                     (workspace_id, database._now()))
    return workspace_id


def read_queue(workspace_id: str, db_path=DB_PATH) -> pd.DataFrame:
    """Read the current overlay without caching it after a save or reset."""
    return database.query(QUEUE_SQL + " ORDER BY p.breach_probability DESC, i.incident_id",
                          db_path, (workspace_id, workspace_id))


def team_summary(workspace_id: str, db_path=DB_PATH) -> pd.DataFrame:
    # The CTE gives this statement a temporary named result (queue), so manager
    # totals use exactly the same open-ticket rules and overlays as the queue.
    return database.query(
        "WITH queue AS (" + QUEUE_SQL + """ )
        SELECT assigned_team AS team, COUNT(*) AS open_incidents,
               SUM(risk_level = 'High') AS high_risk,
               SUM(review_state != 'Unreviewed') AS reviewed,
               SUM(owner = 'Unassigned') AS unassigned
        FROM queue GROUP BY assigned_team ORDER BY high_risk DESC, open_incidents DESC
        """, db_path, (workspace_id, workspace_id))


def save_review(workspace_id: str, incident_id: str, role: str, assigned_team: str,
                owner: str, review_state: str, note: str = "", db_path=DB_PATH) -> bool:
    """Validate a review, then atomically save its current state and history.

    database.connect commits only when the with-block succeeds, or rolls back on
    error. A failed event insert therefore cannot leave an unrecorded review edit.
    """
    if role not in PROFILES:
        raise ValueError("Choose a valid demo role.")
    if owner not in OWNERS or review_state not in REVIEW_STATES:
        raise ValueError("Choose a valid owner and review state.")
    note = note.strip()
    if len(note) > 1500:
        raise ValueError("Notes must be 1,500 characters or fewer.")
    with database.connect(db_path) as conn:
        if not conn.execute("SELECT 1 FROM demo_workspaces WHERE workspace_id = ?",
                            (workspace_id,)).fetchone():
            raise ValueError("Demo workspace not found.")
        incident = conn.execute(
            "SELECT assignment_group, sla_breached, status FROM incidents WHERE incident_id = ?",
            (incident_id,)).fetchone()
        if not incident or incident[1] is not None or incident[2] not in {"Open", "In Progress"}:
            raise ValueError("Only open incidents can be reviewed in this demo.")
        if not conn.execute("SELECT 1 FROM incidents WHERE assignment_group = ? LIMIT 1",
                            (assigned_team,)).fetchone():
            raise ValueError("Choose a team from the sample dataset.")
        existing = conn.execute(
            "SELECT assigned_team, owner, review_state FROM demo_reviews "
            "WHERE workspace_id = ? AND incident_id = ?", (workspace_id, incident_id)).fetchone()
        # An untouched ticket has no review row yet. Reconstruct the same defaults
        # as QUEUE_SQL so the audit event records what the user actually saw.
        before = dict(zip(["assigned_team", "owner", "review_state"],
                          existing or (incident[0], "Unassigned", "Unreviewed")))
        after = {"assigned_team": assigned_team, "owner": owner, "review_state": review_state}
        if before == after and not note:
            return False
        actor, now = PROFILES[role]["name"], database._now()
        # UPSERT inserts the first review or updates the existing composite key.
        # History lives in a separate append-only row; it is not overwritten by
        # later reviews, even though demo_reviews holds only the latest state.
        conn.execute("""
            INSERT INTO demo_reviews
                (workspace_id, incident_id, review_state, assigned_team, owner, updated_at, last_actor)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (workspace_id, incident_id) DO UPDATE SET
                review_state=excluded.review_state, assigned_team=excluded.assigned_team,
                owner=excluded.owner, updated_at=excluded.updated_at, last_actor=excluded.last_actor
            """, (workspace_id, incident_id, review_state, assigned_team, owner, now, actor))
        conn.execute("""
            INSERT INTO demo_events
                (workspace_id, incident_id, actor, role, happened_at, before_json, after_json, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (workspace_id, incident_id, actor, role, now,
                  json.dumps(before), json.dumps(after), note))
    return True


def read_events(workspace_id: str, incident_id: str | None = None, db_path=DB_PATH) -> pd.DataFrame:
    # Only fixed SQL fragments are concatenated. Optional values still use ?, and
    # their tuple order must match placeholder order in the finished statement.
    sql = "SELECT * FROM demo_events WHERE workspace_id = ?"
    params = (workspace_id,)
    if incident_id is not None:
        sql += " AND incident_id = ?"
        params += (incident_id,)
    return database.query(sql + " ORDER BY event_id DESC", db_path, params)


def reset_workspace(workspace_id: str, role: str, db_path=DB_PATH) -> None:
    """Remove one workspace's overlays and history, preserving incident facts."""
    if role != "Admin":
        raise PermissionError("Switch to the Admin demo persona to reset this workspace.")
    with database.connect(db_path) as conn:
        # Foreign keys are enabled by database.connect. ON DELETE CASCADE removes
        # events belonging to deleted reviews; other workspaces are unaffected.
        conn.execute("DELETE FROM demo_reviews WHERE workspace_id = ?", (workspace_id,))
        conn.execute("UPDATE demo_workspaces SET reset_count = reset_count + 1 WHERE workspace_id = ?",
                     (workspace_id,))
