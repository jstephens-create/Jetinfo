"""ETL pipeline: raw CSV -> validate -> standardize -> SQLite.

Extract   : read the raw CSV as plain text (so nothing is silently converted).
Transform : profile quality, drop duplicates, validate, standardize, derive SLA fields.
Load      : upsert valid rows into SQLite; log rejected rows with a reason.

Safe to rerun: incidents are keyed by incident_id and upserted.

Run:  python -m src.etl
"""
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src import database
from src.config import (CATEGORIES, DB_PATH, OPEN_STATUSES, PROCESSED_CSV, RAW_CSV,
                        REJECTED_CSV, RESOLVED_STATUSES, SLA_TARGET_MINUTES, VALID_STATUSES)

log = logging.getLogger("signal.etl")

REQUIRED_COLUMNS = ["incident_id", "created_at", "priority", "category", "affected_service",
                    "assignment_group", "response_time_minutes", "resolution_time_minutes",
                    "sla_target_minutes", "status", "sla_breached"]
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Every spelling we have seen in the source system -> the one official value.
PRIORITY_MAP = {"p1": "Critical", "critical": "Critical", "crit": "Critical",
                "p2": "High", "high": "High",
                "p3": "Medium", "medium": "Medium", "med": "Medium",
                "p4": "Low", "low": "Low"}
CATEGORY_MAP = {c.lower(): c for c in CATEGORIES} | {
    "app": "Software", "application": "Software", "h/w": "Hardware",
    "networking": "Network", "iam": "Access", "db": "Database", "e-mail": "Email"}


# ------------------------------------------------------------------ extract
def load_raw(path: Path | str = RAW_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)  # all text: we validate types ourselves
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Raw file is missing columns: {sorted(missing)}")
    return df


# ------------------------------------------------------------------ profile
def profile(df: pd.DataFrame) -> dict:
    """Data-quality snapshot of the raw file, before any cleaning."""
    return {
        "rows": len(df),
        "missing_values": {c: int(n) for c, n in df.isna().sum().items()},
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "duplicate_incident_ids": int(df["incident_id"].duplicated().sum()),
    }


# ------------------------------------------------------------------ transform helpers
def _standardize(value, mapping: dict):
    if not isinstance(value, str):
        return None
    return mapping.get(value.strip().lower())


def standardize_priority(value):
    return _standardize(value, PRIORITY_MAP)


def standardize_category(value):
    return _standardize(value, CATEGORY_MAP)


def calculate_sla(resolution_minutes: pd.Series, target_minutes: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Breached = took longer than the target. Unknown (NA) while unresolved.

    Returns (sla_breached as nullable 0/1, margin in minutes: positive = time to spare).
    """
    margin = target_minutes - resolution_minutes
    breached = (resolution_minutes > target_minutes).astype("Int64")
    breached[resolution_minutes.isna()] = pd.NA
    return breached, margin.round(1)


def clean_incidents(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Returns (clean rows, rejected rows with 'rejection_reason', duplicates removed)."""
    df = raw.copy()
    for col in df.columns:  # trim stray whitespace everywhere; blank -> missing
        df[col] = df[col].str.strip().replace("", np.nan)

    # 1) Duplicates: the same incident_id twice is the same ticket exported twice.
    dup_mask = df["incident_id"].duplicated(keep="first") & df["incident_id"].notna()
    duplicates = df[dup_mask].assign(rejection_reason="duplicate incident_id")
    df = df[~dup_mask]

    # 2) Parse & standardize (failures become NaN/None and are caught below)
    created = pd.to_datetime(df["created_at"], format=TIMESTAMP_FORMAT, errors="coerce")
    priority = df["priority"].map(standardize_priority)
    category = df["category"].map(standardize_category)
    response = pd.to_numeric(df["response_time_minutes"], errors="coerce")
    resolution = pd.to_numeric(df["resolution_time_minutes"], errors="coerce")
    status = df["status"].str.title()
    is_resolved = status.isin(RESOLVED_STATUSES)

    # 3) Validation rules: (rows that FAIL, human-readable reason)
    rules = [
        (df["incident_id"].isna(), "missing incident_id"),
        (df["created_at"].isna(), "missing created_at"),
        (df["created_at"].notna() & created.isna(), "invalid timestamp"),
        (created > pd.Timestamp.now(), "timestamp in the future"),
        (df["priority"].isna(), "missing priority"),
        (df["priority"].notna() & priority.isna(), "unrecognized priority"),
        (df["category"].isna(), "missing category"),
        (df["category"].notna() & category.isna(), "unrecognized category"),
        (df["affected_service"].isna(), "missing affected_service"),
        (df["assignment_group"].isna(), "missing assignment_group"),
        (response.isna(), "response_time not a number"),
        (response < 0, "negative response_time"),
        (~status.isin(VALID_STATUSES), "invalid status"),
        (is_resolved & resolution.isna(), "resolved incident missing resolution_time"),
        (status.isin(OPEN_STATUSES) & resolution.notna(), "open incident has resolution_time"),
        (resolution < response, "resolution_time shorter than response_time"),
    ]
    reasons = pd.Series([[] for _ in range(len(df))], index=df.index)
    for failed, message in rules:
        for idx in failed[failed.fillna(False)].index:
            reasons[idx].append(message)
    bad = reasons.str.len() > 0

    invalid = df[bad].assign(rejection_reason=reasons[bad].str.join("; "))
    rejected = pd.concat([duplicates, invalid])

    # 4) Build the clean table with proper types and derived SLA fields
    good = ~bad
    clean = pd.DataFrame({
        "incident_id": df.loc[good, "incident_id"],
        "created_at": created[good].dt.strftime(TIMESTAMP_FORMAT),
        "priority": priority[good],
        "category": category[good],
        "affected_service": df.loc[good, "affected_service"],
        "assignment_group": df.loc[good, "assignment_group"],
        "response_time_minutes": response[good],
        "resolution_time_minutes": resolution[good],
        "status": status[good],
    })
    # SLA policy is the source of truth for targets; outcome is recalculated, not trusted.
    clean["sla_target_minutes"] = clean["priority"].map(SLA_TARGET_MINUTES).astype(int)
    clean["sla_breached"], clean["sla_margin_minutes"] = calculate_sla(
        clean["resolution_time_minutes"], clean["sla_target_minutes"])
    clean = clean.sort_values("created_at").reset_index(drop=True)
    return clean, rejected.reset_index(drop=True), int(dup_mask.sum())


# ------------------------------------------------------------------ orchestration
def run_pipeline(raw_path=RAW_CSV, db_path=DB_PATH, processed_path=PROCESSED_CSV,
                 rejected_path=REJECTED_CSV) -> dict:
    database.init_db(db_path)
    with database.connect(db_path) as conn:
        run_id = database.start_run(conn, str(raw_path))

    try:
        raw = load_raw(raw_path)
        quality = profile(raw)
        log.info("Read %d rows; %d exact duplicates; missing: %s", quality["rows"],
                 quality["exact_duplicate_rows"],
                 {k: v for k, v in quality["missing_values"].items() if v})

        clean, rejected, n_dupes = clean_incidents(raw)
        for reason, n in rejected["rejection_reason"].value_counts().items():
            log.warning("Rejected %d row(s): %s", n, reason)

        with database.connect(db_path) as conn:  # one transaction: all or nothing
            new = database.upsert_incidents(conn, clean)
            database.insert_rejected(conn, run_id, rejected)
            summary = {"run_id": run_id, "rows_read": len(raw), "rows_loaded": len(clean),
                       "rows_rejected": len(rejected), "duplicates_removed": n_dupes,
                       "new_incidents": new, "missing_values": quality["missing_values"],
                       "status": "success"}
            database.finish_run(conn, run_id, summary)

        Path(processed_path).parent.mkdir(parents=True, exist_ok=True)
        clean.to_csv(processed_path, index=False)
        rejected.to_csv(rejected_path, index=False)
    except Exception:
        with database.connect(db_path) as conn:
            conn.execute("UPDATE pipeline_runs SET status='failed' WHERE run_id=?", (run_id,))
        raise

    log.info("Run %d: loaded %d (new %d), rejected %d (incl. %d duplicates)", run_id,
             summary["rows_loaded"], new, summary["rows_rejected"], n_dupes)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    run_pipeline()
