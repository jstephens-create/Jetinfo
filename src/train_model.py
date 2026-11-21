"""Train a Logistic Regression that estimates SLA breach probability at ticket creation.

Leakage rule: the model may only see what is known the moment a ticket is opened
(priority, category, service, assignment group, creation time). Resolution time,
response time, status and the SLA outcome happen LATER, so they are banned inputs.

Run:  python -m src.train_model
"""
import json
import logging

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (confusion_matrix, f1_score, precision_score, recall_score,
                             roc_auc_score, roc_curve)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from src import database
from src.etl import TIMESTAMP_FORMAT
from src.config import DB_PATH, METRICS_PATH, MODEL_PATH, PRIORITIES, risk_level

log = logging.getLogger("signal.model")

# What the model needs as RAW input (all known at creation time)
INPUT_COLUMNS = ["priority", "category", "affected_service", "assignment_group", "created_at"]
# What the model actually sees after feature engineering
CATEGORICAL_FEATURES = ["priority", "category", "affected_service", "assignment_group", "shift"]
BINARY_FEATURES = ["is_weekend"]
FEATURES = CATEGORICAL_FEATURES + BINARY_FEATURES
# Known only after the fact -> must never reach the model
LEAKAGE_COLUMNS = {"response_time_minutes", "resolution_time_minutes", "status",
                   "sla_breached", "sla_margin_minutes", "breach_probability", "risk_level"}
TARGET = "sla_breached"
TEST_FRACTION = 0.2
DECISION_THRESHOLD = 0.5


# ------------------------------------------------------------------ input contract
def validate_model_input(df: pd.DataFrame) -> None:
    """Raise ValueError if df can't be safely scored. Called before training AND predicting."""
    missing = [c for c in INPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required input columns: {missing}")
    if df.empty:
        raise ValueError("No rows to score")
    nulls = df[INPUT_COLUMNS].isna().sum()
    if nulls.any():
        raise ValueError(f"Null values in model inputs: {nulls[nulls > 0].to_dict()}")
    bad_priority = set(df["priority"]) - set(PRIORITIES)
    if bad_priority:
        raise ValueError(f"Unknown priority values: {sorted(bad_priority)}")
    if pd.to_datetime(df["created_at"], format=TIMESTAMP_FORMAT, errors="coerce").isna().any():
        raise ValueError("created_at contains unparseable timestamps")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Turn raw creation-time fields into model features. Selects ONLY allowed columns."""
    validate_model_input(df)
    created = pd.to_datetime(df["created_at"], format=TIMESTAMP_FORMAT)
    hour = created.dt.hour
    X = df[["priority", "category", "affected_service", "assignment_group"]].copy()
    X["shift"] = np.select([hour.between(8, 17), hour.between(18, 23)],
                           ["business hours", "evening"], default="overnight")
    X["is_weekend"] = (created.dt.dayofweek >= 5).astype(int)
    leaked = LEAKAGE_COLUMNS & set(X.columns)
    assert not leaked, f"Leakage columns in features: {leaked}"
    return X[FEATURES]


def make_pipeline() -> Pipeline:
    encoder = OneHotEncoder(handle_unknown="ignore")
    pre = ColumnTransformer([("cat", encoder, CATEGORICAL_FEATURES),
                             ("bin", "passthrough", BINARY_FEATURES)],
                            verbose_feature_names_out=False)
    # class_weight='balanced' stops the model ignoring the minority class (breaches).
    # Trade-off: probabilities lean higher than the true base rate -> treat as relative risk.
    model = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced")
    return Pipeline([("features", pre), ("model", model)])


# ------------------------------------------------------------------ evaluation
def chronological_split(df: pd.DataFrame, test_fraction: float = TEST_FRACTION):
    """Train on the past, test on the future - exactly how the model will be used."""
    df = df.sort_values("created_at").reset_index(drop=True)
    cut = int(len(df) * (1 - test_fraction))
    return df.iloc[:cut], df.iloc[cut:]


def evaluate(y_true, proba, threshold=DECISION_THRESHOLD) -> dict:
    y_pred = (np.asarray(proba) >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    has_both = len(set(y_true)) == 2
    return {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 3),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 3),
        "roc_auc": round(float(roc_auc_score(y_true, proba)), 3) if has_both else None,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def priority_baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Rule of thumb an ops lead might use: 'breach risk = historical breach rate of this priority'."""
    rates = train.groupby("priority")[TARGET].mean()
    return test["priority"].map(rates).fillna(train[TARGET].mean()).to_numpy()


def feature_names(pipe: Pipeline) -> list[str]:
    """'priority_Critical' -> 'priority = Critical' for readable explanations."""
    pretty = []
    for name in pipe.named_steps["features"].get_feature_names_out():
        col = next((c for c in CATEGORICAL_FEATURES if name.startswith(c + "_")), None)
        pretty.append(f"{col} = {name[len(col) + 1:]}" if col else name)
    return pretty


def coefficients(pipe: Pipeline) -> pd.DataFrame:
    names = feature_names(pipe)
    coefs = pipe.named_steps["model"].coef_[0]
    return (pd.DataFrame({"feature": names, "coefficient": coefs.round(3),
                          "odds_multiplier": np.exp(coefs).round(2)})
            .sort_values("coefficient", ascending=False).reset_index(drop=True))


def explain(pipe: Pipeline, incident: pd.DataFrame) -> pd.DataFrame:
    """Per-incident contribution of each active feature to the log-odds of breach.

    Positive pushes the estimate up, negative pulls it down. This describes what the
    model learned from historical patterns - it is NOT proof of cause and effect.
    """
    X = pipe.named_steps["features"].transform(build_features(incident))
    X = X.toarray() if hasattr(X, "toarray") else X
    contrib = X[0] * pipe.named_steps["model"].coef_[0]
    names = feature_names(pipe)
    out = pd.DataFrame({"feature": names, "contribution": contrib})
    out = out[X[0] != 0]
    return out.reindex(out["contribution"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def predict(pipe: Pipeline, df: pd.DataFrame) -> np.ndarray:
    return pipe.predict_proba(build_features(df))[:, 1]


# ------------------------------------------------------------------ main
def train(db_path=DB_PATH, model_path=MODEL_PATH, metrics_path=METRICS_PATH) -> dict:
    incidents = database.read_incidents(db_path)
    labelled = incidents[incidents[TARGET].notna()].copy()  # open tickets have no outcome yet
    labelled[TARGET] = labelled[TARGET].astype(int)
    train_df, test_df = chronological_split(labelled)
    log.info("Train %d rows (%s -> %s), test %d rows (%s -> %s)",
             len(train_df), train_df.created_at.min()[:10], train_df.created_at.max()[:10],
             len(test_df), test_df.created_at.min()[:10], test_df.created_at.max()[:10])

    pipe = make_pipeline().fit(build_features(train_df), train_df[TARGET])
    proba = predict(pipe, test_df)
    y_test = test_df[TARGET].to_numpy()

    majority = DummyClassifier(strategy="most_frequent").fit(build_features(train_df), train_df[TARGET])
    fpr, tpr, _ = roc_curve(y_test, proba)

    metrics = {
        "model": evaluate(y_test, proba),
        # Fair rule: flag a ticket if its priority breaches more often than average.
        "baseline_priority_rate": evaluate(y_test, priority_baseline(train_df, test_df),
                                           threshold=train_df[TARGET].mean() + 1e-9),
        "baseline_majority_class": evaluate(y_test, majority.predict_proba(build_features(test_df))[:, 1]),
        "roc_curve": {"fpr": fpr.round(4).tolist(), "tpr": tpr.round(4).tolist()},
        "coefficients": coefficients(pipe).to_dict("records"),
        "split": {"train_rows": len(train_df), "test_rows": len(test_df),
                  "train_start": train_df.created_at.min(), "train_end": train_df.created_at.max(),
                  "test_start": test_df.created_at.min(), "test_end": test_df.created_at.max(),
                  "train_breach_rate": round(float(train_df[TARGET].mean()), 3),
                  "test_breach_rate": round(float(y_test.mean()), 3)},
        "features": FEATURES,
        "decision_threshold": DECISION_THRESHOLD,
    }

    # Refit on ALL labelled history for production scoring (evaluation above stays honest).
    final = make_pipeline().fit(build_features(labelled), labelled[TARGET])
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, model_path)
    metrics_path.write_text(json.dumps(metrics, indent=2))

    scores = incidents[["incident_id"]].copy()
    scores["breach_probability"] = predict(final, incidents)
    scores["risk_level"] = scores["breach_probability"].map(risk_level)
    with database.connect(db_path) as conn:
        database.save_predictions(conn, scores)

    for name in ["model", "baseline_priority_rate", "baseline_majority_class"]:
        m = metrics[name]
        log.info("%-24s precision=%.3f recall=%.3f f1=%.3f auc=%s", name, m["precision"],
                 m["recall"], m["f1"], m["roc_auc"])
    return metrics


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    train()
