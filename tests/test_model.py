"""Model input validation, leakage protection, chronological split, and a smoke train."""
import numpy as np
import pandas as pd
import pytest

from src.train_model import (INPUT_COLUMNS, LEAKAGE_COLUMNS, build_features, chronological_split,
                             evaluate, explain, make_pipeline, predict, validate_model_input)


def _inputs(n=4):
    return pd.DataFrame({"priority": ["High", "Low", "Critical", "Medium"][:n],
                         "category": ["Network", "Email", "Database", "Access"][:n],
                         "affected_service": ["VPN", "Exchange Online", "ERP", "Active Directory"][:n],
                         "assignment_group": ["Network Operations", "Service Desk", "Database Admin",
                                              "Identity & Access"][:n],
                         "created_at": ["2024-03-02 22:00:00", "2024-03-04 10:00:00",
                                        "2024-03-05 03:00:00", "2024-03-06 14:00:00"][:n]})


def test_valid_input_passes():
    validate_model_input(_inputs())


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.drop(columns=["priority"]), "Missing required"),
    (lambda d: d.assign(category=[None, "Email", "Database", "Access"]), "Null values"),
    (lambda d: d.assign(priority=["P1", "Low", "High", "Low"]), "Unknown priority"),
    (lambda d: d.assign(created_at=["garbage"] * 4), "unparseable"),
    (lambda d: d.iloc[0:0], "No rows"),
])
def test_invalid_input_is_rejected(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_model_input(mutate(_inputs()))


def test_features_never_include_leakage_columns():
    df = _inputs().assign(resolution_time_minutes=1.0, response_time_minutes=1.0, status="Closed",
                          sla_breached=1, sla_margin_minutes=0.0)
    X = build_features(df)
    assert not LEAKAGE_COLUMNS & set(X.columns)
    assert not set(INPUT_COLUMNS) - {"created_at"} - set(X.columns)


def test_time_features():
    X = build_features(_inputs())
    assert X["is_weekend"].tolist() == [1, 0, 0, 0]  # 2024-03-02 is a Saturday
    assert X["shift"].tolist() == ["evening", "business hours", "overnight", "business hours"]


def test_chronological_split_tests_on_the_future():
    df = pd.DataFrame({"created_at": [f"2024-01-{d:02d} 00:00:00" for d in range(10, 0, -1)]})
    train, test = chronological_split(df, test_fraction=0.2)
    assert len(test) == 2
    assert train["created_at"].max() < test["created_at"].min()


def test_evaluate_metrics():
    m = evaluate(np.array([0, 0, 1, 1]), np.array([0.1, 0.6, 0.4, 0.9]))
    assert m["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert m["precision"] == m["recall"] == m["f1"] == 0.5
    assert m["roc_auc"] == 0.75


def test_model_trains_and_outputs_probabilities():
    rng = np.random.default_rng(0)
    df = pd.concat([_inputs()] * 10, ignore_index=True)
    y = (df["priority"].isin(["High", "Critical"]) | (rng.random(len(df)) < 0.1)).astype(int)
    pipe = make_pipeline().fit(build_features(df), y)
    p = predict(pipe, _inputs())
    assert ((p >= 0) & (p <= 1)).all()
    assert p[0] > p[1]  # High priority scored riskier than Low
    assert not explain(pipe, _inputs(1)).empty
