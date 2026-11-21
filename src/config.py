"""Central configuration: file paths and business rules shared by every component.

Keeping these in one place means the generator, the ETL pipeline, the model and
the dashboard all agree on what "Critical" means and how long its SLA is.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RAW_CSV = ROOT / "data" / "raw" / "incidents_raw.csv"
PROCESSED_CSV = ROOT / "data" / "processed" / "incidents_clean.csv"
REJECTED_CSV = ROOT / "data" / "processed" / "rejected_records.csv"
DB_PATH = ROOT / "data" / "processed" / "signal.db"
MODEL_PATH = ROOT / "models" / "sla_model.joblib"
METRICS_PATH = ROOT / "models" / "metrics.json"

RANDOM_SEED = 42

# SLA policy: the maximum minutes allowed to RESOLVE an incident, by priority.
# This is the business rule; the ETL recalculates targets from it.
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

# Risk bands for predicted breach probability (estimates, not guarantees).
RISK_BANDS = [(0.0, 0.30, "Low"), (0.30, 0.55, "Medium"), (0.55, 1.01, "High")]


def risk_level(probability: float) -> str:
    for low, high, label in RISK_BANDS:
        if low <= probability < high:
            return label
    return "High"
