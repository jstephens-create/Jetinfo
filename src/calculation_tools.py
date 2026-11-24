"""Strict, read-only local tools for validated calculations and explanations.

This is an ordinary Python boundary, not an MCP server or a connected LLM. A
future assistant receives only an already-authorized engine; it cannot choose a
database path, issue SQL, mutate facts, or substitute its own arithmetic.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Mapping

import pandas as pd

from src.calculations import (COMPLETENESS_FIELDS, METRIC_REGISTRY,
                              CalculationEngine, ThresholdConfig)


TOOL_SCHEMA = {
    "name": "okai_calculation",
    "description": "Retrieve deterministic metrics and source membership from an authorized OKai dataset.",
    "permissions": ["read:authorized_calculations"],
    "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["list_metrics", "calculate", "inspect", "alerts"]},
            "metric_id": {"type": "string", "enum": list(METRIC_REGISTRY)},
            "parameters": {
                "type": "object", "additionalProperties": False,
                "description": "Only the selected metric's registered parameters; runtime validation enforces their combination.",
                "properties": {
                    "field": {"type": "string", "enum": sorted(COMPLETENESS_FIELDS)},
                    "baseline_hours": {"type": ["number", "null"], "minimum": 0},
                    "observed_hours": {"type": ["number", "null"], "minimum": 0},
                    "hours_saved": {"type": ["number", "null"]},
                    "hourly_labor_cost": {"type": ["number", "null"], "minimum": 0},
                    "currency": {"type": ["string", "null"], "pattern": "^[A-Za-z]{3}$"},
                    "processed_records": {"type": ["integer", "null"], "minimum": 0},
                    "elapsed_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0},
                    "operational_cost": {"type": ["number", "null"], "minimum": 0},
                    "incident_count": {"type": ["integer", "null"], "minimum": 1},
                },
            },
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "as_of": {"type": "string"},
            "thresholds": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "age_hours": {"type": "number", "minimum": 0},
                    "backlog_threshold": {"type": "integer", "minimum": 0},
                    "sla_warning_minutes": {"type": "number", "minimum": 0},
                    "high_priority_unassigned": {"type": "boolean"},
                    "rule_basis": {"type": "string"},
                },
            },
        },
    },
}


def _json_records(frame: pd.DataFrame) -> list[dict]:
    # pandas handles numpy scalars, nullable Booleans, timestamps, and NaN here.
    # JSON null is explicit unknown; it is never changed to a numeric zero.
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def build_calculation_evidence_export(engine, inspection: Mapping, parameters: Mapping,
                                      parameter_origins: Mapping, supporting_records: pd.DataFrame | None = None) -> bytes:
    """Create a portable trace joining a calculation to its source and evidence."""
    result_records = inspection["records"]
    evidence = {"record_count": len(result_records), "records": _json_records(result_records)}
    if supporting_records is not None and not supporting_records.equals(result_records):
        evidence["supporting_incident_record_count"] = len(supporting_records)
        evidence["supporting_incident_records"] = _json_records(supporting_records)
    origins = {name: parameter_origins.get(name, "Selected in Calculation Inspector")
               for name in parameters}
    payload = {
        "schema": "okai.calculation-evidence.v1",
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": asdict(engine.context),
        "metric_definition": inspection["definition"],
        "result": inspection["result"],
        "inputs": {"values": dict(parameters), "origins": origins},
        "evidence": evidence,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def explain_result(result: Mapping) -> str:
    """Render an explanation using authoritative values, without new arithmetic."""
    if result["status"] == "unavailable":
        return f"Unavailable: {result.get('unavailable_reason') or 'Required source inputs are unavailable.'}"
    text = (f"{result['metric_id']}: {result['value']} {result['unit']}. "
            f"Eligible records: {result['eligible_count']}; excluded records: {result['excluded_count']}. "
            f"Source: {result['source_name']}; formula version: {result['formula_version']}.")
    if result.get("warnings"):
        text += " " + " ".join(result["warnings"])
    return text


def execute_metric_tool(engine: CalculationEngine, request: Mapping) -> dict:
    """Validate an allowlisted request and return a serializable success/error.

    Programmer/configuration errors become bounded validation responses. No
    request can turn this read interface into a file or database write tool.
    """
    try:
        if not isinstance(request, Mapping):
            raise ValueError("Request must be an object.")
        action = request.get("action")
        action_fields = {
            "list_metrics": {"action"},
            "calculate": {"action", "metric_id", "parameters"},
            "inspect": {"action", "metric_id", "parameters", "offset", "limit"},
            "alerts": {"action", "as_of", "thresholds", "offset", "limit"},
        }
        if not isinstance(action, str) or action not in action_fields:
            raise ValueError("action must be list_metrics, calculate, inspect, or alerts.")
        extra = set(request) - action_fields[action]
        if extra:
            raise ValueError(f"Unexpected request fields: {sorted(map(str, extra))}")
        limit, offset = request.get("limit", 100), request.get("offset", 0)
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError("limit must be an integer from 1 to 1000; offset must be a nonnegative integer.")
        if action == "list_metrics":
            return {"ok": True, "metrics": [definition.to_dict() for definition in engine.registry.values()]}
        if action == "alerts":
            thresholds = request.get("thresholds", {})
            if not isinstance(thresholds, Mapping) or set(thresholds) - set(ThresholdConfig.__dataclass_fields__):
                raise ValueError("thresholds must contain only registered rule fields.")
            as_of = request.get("as_of")
            if as_of is not None and not isinstance(as_of, str):
                raise ValueError("as_of must be a timestamp string.")
            records = engine.alerts(ThresholdConfig(**thresholds), as_of=as_of)
            return {"ok": True, "alerts": _json_records(records.iloc[offset:offset + limit]),
                    "total_records": len(records), "offset": offset, "limit": limit,
                    "temporal_rules_evaluated": as_of is not None,
                    "notice": "Investigation rules support human review; they are not statistical predictions or verified SLA compliance."}
        metric_id = request.get("metric_id")
        if not isinstance(metric_id, str) or metric_id not in engine.registry:
            raise ValueError("metric_id must name a registered metric.")
        parameters = request.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ValueError("parameters must be an object.")
        for key, value in parameters.items():
            if not isinstance(key, str) or value is not None and type(value) not in {str, int, float}:
                raise ValueError("Metric parameters must use named scalar string/number/null values.")
            if isinstance(value, (float, int)):
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("Numeric parameters must be finite.")
        if action == "calculate":
            result = engine.calculate(metric_id, parameters).to_dict()
            return {"ok": True, "result": result, "explanation": explain_result(result)}
        inspection = engine.inspect(metric_id, parameters)
        records = inspection["records"]
        return {"ok": True, "definition": inspection["definition"], "result": inspection["result"],
                "explanation": explain_result(inspection["result"]),
                "records": _json_records(records.iloc[offset:offset + limit]),
                "total_records": len(records), "offset": offset, "limit": limit}
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {"ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
