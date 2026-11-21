"""Generate 500 synthetic IT incidents -> data/raw/incidents_raw.csv

The raw file deliberately imitates a messy export from a ticketing tool:
inconsistent spellings, missing values, broken timestamps and duplicate rows.
The ETL pipeline's job is to clean that up. See README "Data generation rules".

Run:  python -m src.generate_data
"""
import numpy as np
import pandas as pd

from src.config import RANDOM_SEED, RAW_CSV, SLA_TARGET_MINUTES

N_INCIDENTS = 500
N_DUPLICATES = 10
START = pd.Timestamp("2024-01-01")
DAYS = 182  # Jan - Jun 2024

PRIORITY_WEIGHTS = {"Critical": 0.05, "High": 0.15, "Medium": 0.45, "Low": 0.35}
# Median first-response time (minutes) by priority
MEDIAN_RESPONSE = {"Critical": 10, "High": 25, "Medium": 90, "Low": 300}
# Typical resolution time as a fraction of the SLA target (tighter SLAs run closer)
MEDIAN_RESOLUTION_RATIO = {"Critical": 0.80, "High": 0.70, "Medium": 0.55, "Low": 0.45}

CATEGORY_WEIGHTS = {"Software": 0.28, "Access": 0.18, "Hardware": 0.16,
                    "Network": 0.16, "Email": 0.12, "Database": 0.10}
CATEGORY_SERVICES = {
    "Software": ["ERP", "CRM", "Payroll", "Website"],
    "Hardware": ["Laptops", "Printers", "Data Center"],
    "Network": ["VPN", "Wi-Fi", "Data Center"],
    "Access": ["Active Directory", "VPN", "ERP"],
    "Database": ["Data Warehouse", "ERP", "CRM"],
    "Email": ["Exchange Online"],
}
CATEGORY_GROUP = {
    "Software": "Application Support", "Hardware": "Desktop Support",
    "Network": "Network Operations", "Access": "Identity & Access",
    "Database": "Database Admin", "Email": "Service Desk",
}

# Hidden "real world" drivers of slow resolution. All are knowable at creation time,
# so the model has genuine signal to learn. Values > 1 slow resolution down.
CATEGORY_FACTOR = {"Database": 1.35, "Network": 1.15, "Software": 1.10,
                   "Hardware": 1.00, "Email": 0.85, "Access": 0.80}
SERVICE_FACTOR = {"ERP": 1.20, "Data Center": 1.20, "Data Warehouse": 1.15}
MISROUTED_FACTOR = 1.30   # ticket left with Service Desk instead of the specialist team
OFF_HOURS_FACTOR = 1.35   # created before 08:00 or after 18:00
WEEKEND_FACTOR = 1.40


def _pick(rng, weights: dict, size=None):
    return rng.choice(list(weights), p=list(weights.values()), size=size)


def generate_clean(rng: np.random.Generator) -> pd.DataFrame:
    """Create the 'true' incidents before any data-quality problems are injected."""
    rows = []
    for _ in range(N_INCIDENTS):
        # ---- creation time: 75% during business hours, weekends less common
        day = START + pd.Timedelta(days=int(rng.integers(0, DAYS)))
        if day.dayofweek >= 5 and rng.random() < 0.6:
            day += pd.Timedelta(days=2)  # push most weekend tickets to Mon/Tue
        hour = int(rng.integers(8, 18)) if rng.random() < 0.75 else int(rng.choice(
            [0, 1, 2, 3, 4, 5, 6, 7, 18, 19, 20, 21, 22, 23]))
        created = day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)),
                                     seconds=int(rng.integers(0, 60)))

        priority = _pick(rng, PRIORITY_WEIGHTS)
        category = _pick(rng, CATEGORY_WEIGHTS)
        service = rng.choice(CATEGORY_SERVICES[category])
        group = CATEGORY_GROUP[category]
        misrouted = category != "Email" and rng.random() < 0.15
        if misrouted:
            group = "Service Desk"

        target = SLA_TARGET_MINUTES[priority]
        response = max(1.0, MEDIAN_RESPONSE[priority] * rng.lognormal(0, 0.5))

        factor = CATEGORY_FACTOR[category] * SERVICE_FACTOR.get(service, 1.0)
        if misrouted:
            factor *= MISROUTED_FACTOR
        if hour < 8 or hour >= 18:
            factor *= OFF_HOURS_FACTOR
        if created.dayofweek >= 5:
            factor *= WEEKEND_FACTOR
        ratio = MEDIAN_RESOLUTION_RATIO[priority] * factor * rng.lognormal(0, 0.45)
        resolution = max(response + 5, target * ratio)

        rows.append({
            "incident_id": None,  # assigned after sorting by time
            "created_at": created,
            "priority": priority,
            "category": category,
            "affected_service": service,
            "assignment_group": group,
            "response_time_minutes": round(response, 1),
            "resolution_time_minutes": round(resolution, 1),
            "sla_target_minutes": target,
            "status": rng.choice(["Closed", "Resolved"], p=[0.7, 0.3]),
        })

    df = pd.DataFrame(rows).sort_values("created_at").reset_index(drop=True)
    df["incident_id"] = [f"INC{100001 + i}" for i in range(len(df))]

    # The 25 most recent tickets are still being worked: no resolution yet.
    recent = df.index[-25:]
    df.loc[recent, "status"] = rng.choice(["Open", "In Progress"], size=len(recent))
    df.loc[recent, "resolution_time_minutes"] = np.nan

    resolved = df["resolution_time_minutes"].notna()
    df["sla_breached"] = ""
    df.loc[resolved, "sla_breached"] = np.where(
        df.loc[resolved, "resolution_time_minutes"] > df.loc[resolved, "sla_target_minutes"],
        "Yes", "No")
    df["created_at"] = df["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def inject_quality_issues(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Make the data look like a real export: messy labels, gaps, bad values, duplicates."""
    df = df.astype(object).copy()
    resolved_idx = df.index[df["status"].isin(["Closed", "Resolved"])].to_numpy()
    pool = rng.permutation(resolved_idx)  # distinct rows for each fatal problem
    take = iter(pool)

    def rows(n):
        return [next(take) for _ in range(n)]

    # --- Fatal problems (rows will be REJECTED by the ETL) ---
    for i in rows(5):
        df.at[i, "priority"] = np.nan
    for i in rows(3):
        df.at[i, "category"] = np.nan
    for i, bad in zip(rows(4), ["2024-13-45 10:00:00", "not a date", "31/02/2024", "2024-02-30 25:61:00"]):
        df.at[i, "created_at"] = bad
    for i in rows(4):
        df.at[i, "response_time_minutes"] = -abs(float(df.at[i, "response_time_minutes"]))
    for i in rows(3):
        df.at[i, "response_time_minutes"] = "N/A"
    for i in rows(3):  # resolved faster than first response: impossible
        df.at[i, "resolution_time_minutes"] = 1.0

    # --- Fixable problems (ETL STANDARDIZES these) ---
    priority_variants = {"Critical": ["P1", "critical", "CRITICAL "], "High": ["P2", "high", " High"],
                         "Medium": ["P3", "med", "MEDIUM"], "Low": ["P4", "low", "Low "]}
    category_variants = {"Software": ["software", "App", "SOFTWARE "], "Hardware": ["H/W", "hardware"],
                         "Network": ["Networking", "network "], "Access": ["IAM", "access"],
                         "Database": ["DB", "database"], "Email": ["E-mail", "email"]}
    for i in rng.choice(df.index, size=40, replace=False):
        if isinstance(df.at[i, "priority"], str):
            df.at[i, "priority"] = rng.choice(priority_variants[df.at[i, "priority"]])
    for i in rng.choice(df.index, size=40, replace=False):
        if isinstance(df.at[i, "category"], str):
            df.at[i, "category"] = rng.choice(category_variants[df.at[i, "category"]])
    for i in rng.choice(df.index, size=15, replace=False):
        df.at[i, "assignment_group"] = f"  {df.at[i, 'assignment_group']} "

    # --- Duplicate rows (same ticket exported twice) ---
    dupes = df.loc[rng.choice(df.index, size=N_DUPLICATES, replace=False)]
    df = pd.concat([df, dupes], ignore_index=True)
    return df.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)


def main() -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)
    raw = inject_quality_issues(generate_clean(rng), rng)
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(RAW_CSV, index=False)
    print(f"Wrote {len(raw)} raw rows ({N_INCIDENTS} incidents + {N_DUPLICATES} duplicates) -> {RAW_CSV}")
    return raw


if __name__ == "__main__":
    main()
