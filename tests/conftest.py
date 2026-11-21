"""Shared fixtures: small hand-made datasets so every test is fast and readable."""
import pandas as pd
import pytest


def raw_row(**overrides):
    row = {"incident_id": "INC1", "created_at": "2024-03-04 10:15:00", "priority": "High",
           "category": "Network", "affected_service": "VPN", "assignment_group": "Network Operations",
           "response_time_minutes": "20", "resolution_time_minutes": "300", "sla_target_minutes": "480",
           "status": "Closed", "sla_breached": "No"}
    row.update(overrides)
    return row


@pytest.fixture
def make_raw():
    """make_raw(dict, dict, ...) -> raw-style DataFrame (all strings, like a CSV read)."""
    def _make(*rows):
        return pd.DataFrame([raw_row(**r) for r in rows]).astype(object)
    return _make


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"
