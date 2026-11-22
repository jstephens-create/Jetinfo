"""Central configuration: file paths and business rules shared by every component.

Keeping these in one place means the generator, the ETL pipeline, the model and
the dashboard all agree on what "Critical" means and how long its SLA is.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Resolve paths relative to this repository, rather than the terminal's current
# folder. The same modules can then be launched by Streamlit, tests, or a task.
RAW_CSV = ROOT / "data" / "raw" / "incidents_raw.csv"
PROCESSED_CSV = ROOT / "data" / "processed" / "incidents_clean.csv"
REJECTED_CSV = ROOT / "data" / "processed" / "rejected_records.csv"
DB_PATH = ROOT / "data" / "processed" / "signal.db"
MODEL_PATH = ROOT / "models" / "sla_model.joblib"
METRICS_PATH = ROOT / "models" / "metrics.json"

# A seed makes the synthetic example repeatable so a code change can be compared
# with the same starting data. It does not make that data representative of a firm.
RANDOM_SEED = 42

# SLA policy: the maximum minutes allowed to RESOLVE an incident, by priority.
# This is a simplified demo policy in elapsed minutes, without business-hour
# calendars or paused clocks. The ETL recalculates targets from this rule.
SLA_TARGET_MINUTES = {
    "Critical": 240,    # 4 hours
    "High": 480,        # 8 hours
    "Medium": 1440,     # 1 day
    "Low": 4320,        # 3 days
}
PRIORITIES = list(SLA_TARGET_MINUTES)  # ordered most -> least urgent

CATEGORIES = ["Software", "Hardware", "Network", "Access", "Database", "Email"]
RESOLVED_STATUSES = {"Resolved", "Closed"}
OPEN_STATUSES = {"Open", "In Progress"}
VALID_STATUSES = RESOLVED_STATUSES | OPEN_STATUSES

# These bands turn a continuous model score into a display label. They are a demo
# presentation choice, separate from the model's 0.5 evaluation threshold. The
# class-weighted model is not calibrated to provide observed breach frequencies.
RISK_BANDS = [(0.0, 0.30, "Low"), (0.30, 0.55, "Medium"), (0.55, 1.01, "High")]


def risk_level(probability: float) -> str:
    """Map a score to a band; each lower bound is inclusive, upper bound exclusive."""
    for low, high, label in RISK_BANDS:
        if low <= probability < high:
            return label
    return "High"
