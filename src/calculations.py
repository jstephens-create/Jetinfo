"""OKai's deterministic numerical authority, independent of Streamlit and SQL.

An event describes one observation; an incident snapshot describes one ticket.
The engine deliberately accepts these as separate tables. It refuses repeated
snapshot IDs instead of guessing which historical state a dashboard intended.
Teaching note: a percentage is a value *and* a population. Every result keeps
its numerator, denominator, exclusions, and source beside the displayed value.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd


FORMULA_VERSION = "1.0.0"
RESOLVED_STATES = frozenset({"resolved", "closed"})
KNOWN_STATES = RESOLVED_STATES | frozenset({
    "open", "in progress", "new", "active", "awaiting user info", "awaiting vendor",
    "awaiting problem", "awaiting evidence",
})
HIGH_PRIORITIES = frozenset({"critical", "high", "1 - critical", "2 - high"})
UNKNOWN_TEXT = frozenset({"", "?", "unknown", "unassigned", "none", "null", "nan", "nat"})
COMPLETENESS_FIELDS = frozenset({
    "incident_id", "opened_at", "created_at", "resolved_at", "closed_at", "event_at",
    "status", "priority", "category", "assignment_group", "assigned_to", "affected_service",
    "source_sla_met", "sla_breached", "response_time_minutes", "resolution_time_minutes",
    "reassignment_count", "reopen_count",
})


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    name: str
    business_purpose: str
    required_fields: tuple[str, ...]
    unit_of_analysis: str
    formula: str
    unit: str
    numerator_definition: str
    denominator_definition: str
    filters_and_exclusions: str
    missing_data_behavior: str
    rounding_digits: int = 1
    applicable_window: str = "Selected source cohort; no implicit current-date filter."
    version: str = FORMULA_VERSION
    validation_requirements: str = "One snapshot per nonmissing incident ID; finite valid inputs."

    def to_dict(self) -> dict:
        return asdict(self)


def _definition(metric_id, name, purpose, fields, grain, formula, unit,
                numerator="Not applicable", denominator="Not applicable", exclusions="None",
                missing="Unavailable when required inputs or the denominator are missing.", digits=1):
    return MetricDefinition(metric_id, name, purpose, tuple(fields), grain, formula, unit,
                            numerator, denominator, exclusions, missing, digits)


# Definitions are immutable and shared by the UI, inspector, and tool interface.
# They describe the implemented method, rather than advertising future metrics.
METRIC_REGISTRY = MappingProxyType({definition.metric_id: definition for definition in [
    _definition("unique_incident_count", "Unique incidents", "Count tickets without event inflation.",
                ["incident_id"], "Unique incident", "COUNT(DISTINCT incident_id)", "incidents", digits=0),
    _definition("total_event_count", "Historical events", "Describe observations separately from tickets.",
                ["incident_id", "event_at"], "Event", "COUNT(valid event records)", "events",
                exclusions="Missing incident identifiers or invalid event timestamps.", digits=0),
    _definition("resolved_incident_rate", "Resolved incident rate", "Describe the final known source status.",
                ["status"], "Unique incident", "100 × resolved or closed incidents / incidents with known status", "%",
                "Incidents whose status is Resolved or Closed", "Incidents with recognized status",
                "Missing or unrecognized status; timestamp completeness is measured separately."),
    _definition("source_sla_attainment", "Source-reported SLA attainment", "Summarize source flags without claiming contractual verification.",
                ["source_sla_met", "status"], "Unique incident", "100 × reported met / resolved incidents with known source SLA outcome", "%",
                "Resolved/closed incidents with source_sla_met=True", "Resolved/closed incidents with a known source flag",
                "Unresolved incidents and missing/invalid flags. No demo targets are applied."),
    _definition("demo_sla_attainment", "Demo-policy SLA attainment", "Describe the synthetic elapsed-time policy only.",
                ["sla_breached", "status"], "Unique incident", "100 × demo outcomes not breached / resolved incidents with known demo outcome", "%",
                "Resolved/closed incidents with sla_breached=0", "Resolved/closed incidents with known demo outcome",
                "Unresolved incidents and missing/invalid outcomes; unavailable for event-log sources."),
    _definition("mean_resolution_hours", "Mean gross resolution time", "Describe gross elapsed duration, separately from SLA clocks.",
                ["status", "opened_at", "resolved_at"], "Unique resolved incident", "SUM(valid nonnegative gross resolution hours) / COUNT(valid durations)", "hours",
                "Sum of valid gross duration hours", "Resolved/closed incidents with valid duration",
                "Missing/invalid timestamps, negative intervals, unresolved statuses; legacy demo uses validated duration minutes."),
    _definition("median_resolution_hours", "Median gross resolution time", "Describe typical gross duration without mean sensitivity to outliers.",
                ["status", "opened_at", "resolved_at"], "Unique resolved incident", "Median of valid nonnegative gross resolution hours (linear interpolation)", "hours",
                denominator="Resolved/closed incidents with valid duration",
                exclusions="Same duration eligibility as the mean; pandas quantile(0.5, interpolation='linear')."),
    _definition("assignment_completeness", "Final assignment completeness", "Keep unknown final groups visible.",
                ["assignment_group"], "Unique incident", "100 × incidents with known final assignment group / incidents", "%",
                "Incidents with a nonmissing final assignment group", "All incidents",
                "Unknown remains in the denominator and in grouped reporting."),
    _definition("field_completeness", "Field completeness", "Measure a selected field on incident snapshots.",
                ["field parameter"], "Unique incident", "100 × valid nonmissing field values / incidents", "%",
                "Incidents with a valid, nonmissing selected field", "All incidents",
                "Missing and invalid values remain in the denominator; absent field is unavailable."),
    _definition("unresolved_incident_count", "Unresolved incidents", "Count recognized nonterminal states without assuming missing SLA means open.",
                ["status"], "Unique incident", "COUNT(known nonterminal incident statuses)", "incidents",
                exclusions="Missing or unrecognized status.", digits=0),
    _definition("high_priority_incident_count", "High-priority incidents", "Count known Critical and High priorities.",
                ["priority"], "Unique incident", "COUNT(priority IN Critical, High)", "incidents",
                exclusions="Missing or unrecognized priority.", digits=0),
    _definition("time_saved_hours", "Estimated processing time saved", "Compare explicitly supplied matched baseline and observed processing time.",
                ["baseline_hours", "observed_hours"], "Matched processing scenario", "baseline_hours − observed_hours", "hours",
                exclusions="Missing, nonfinite, or negative inputs; negative savings are retained."),
    _definition("time_reduction_pct", "Estimated processing time reduction", "Express a measured scenario difference relative to its baseline.",
                ["baseline_hours", "observed_hours"], "Matched processing scenario", "100 × (baseline_hours − observed_hours) / baseline_hours", "%",
                "Baseline minus observed hours", "Baseline hours",
                "Zero baseline, missing/nonfinite/negative inputs; negative reductions are retained."),
    _definition("estimated_labor_value", "Estimated labor capacity value", "Value supplied saved hours; this does not establish realized cash savings.",
                ["hours_saved", "hourly_labor_cost", "currency"], "Scenario estimate", "hours_saved × hourly_labor_cost", "currency",
                exclusions="Missing/nonfinite inputs, negative labor cost, or missing currency. Negative hours represent capacity loss.", digits=2),
    _definition("processing_throughput", "Processing throughput", "Measure successfully processed records per elapsed second for a named stage.",
                ["processed_records", "elapsed_seconds"], "Measured processing stage", "processed_records / elapsed_seconds", "records/second",
                "Successfully processed whole records", "Positive elapsed seconds",
                "Missing/nonfinite/negative counts or nonpositive elapsed time.", digits=2),
    _definition("cost_per_incident", "Estimated cost per incident", "Divide supplied eligible operational cost by its explicitly matched incident population.",
                ["operational_cost", "incident_count", "currency"], "Cost allocation scenario", "operational_cost / incident_count", "currency/incident",
                "Eligible supplied operational cost", "Explicit eligible incident count",
                "Missing/nonfinite/negative cost, nonpositive/noninteger count, or missing currency.", digits=2),
]})


@dataclass(frozen=True)
class CalculationContext:
    dataset_id: str
    source_name: str
    source_kind: str = "demo"
    import_id: str | None = None
    timezone: str = "unknown"
    observation_start: str | None = None
    observation_end: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.dataset_id or not self.source_name:
            raise ValueError("dataset_id and source_name are required provenance.")
        if self.source_kind not in {"demo", "event_log"}:
            raise ValueError("source_kind must be demo or event_log.")
        if self.timezone != "unknown":
            # Let pandas validate the actual IANA name instead of treating a typo
            # as UTC. No conversion is inferred when a source omits its zone.
            try:
                pd.Timestamp("2024-01-01").tz_localize(self.timezone)
            except Exception as exc:
                raise ValueError("Unrecognized source timezone.") from exc


@dataclass(frozen=True)
class CalculationResult:
    metric_id: str
    value: int | float | None
    status: str
    unit: str
    observation_window: dict
    dataset_id: str
    source_name: str
    source_kind: str
    import_id: str | None
    eligible_count: int
    excluded_count: int
    formula_version: str
    calculated_at: str
    numerator: int | float | None = None
    denominator: int | float | None = None
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    parameters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_demo_sla(resolution_minutes: pd.Series, target_minutes: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Compatibility helper for the explicitly configured synthetic demo policy.

    Nullable integers preserve three outcomes: met, breached, and unknown. An
    absent/invalid duration or target cannot quietly become an SLA success.
    """
    resolution = pd.to_numeric(resolution_minutes, errors="coerce")
    target = pd.to_numeric(target_minutes, errors="coerce")
    valid = resolution.notna() & target.notna() & resolution.ge(0) & target.ge(0)
    valid &= resolution.map(lambda x: pd.notna(x) and math.isfinite(float(x)))
    valid &= target.map(lambda x: pd.notna(x) and math.isfinite(float(x)))
    breached = pd.Series(pd.NA, index=resolution.index, dtype="Int64")
    breached.loc[valid] = resolution.loc[valid].gt(target.loc[valid]).astype("int64")
    margin = (target - resolution).where(valid).round(1)
    return breached, margin


def _known(series: pd.Series) -> pd.Series:
    return series.notna() & ~series.astype("string").str.strip().str.casefold().isin(UNKNOWN_TEXT)


def _bool_values(series: pd.Series) -> pd.Series:
    normalized = series.astype("string").str.strip().str.casefold()
    return normalized.map({"true": True, "false": False, "1": True, "0": False,
                           "1.0": True, "0.0": False}).astype("boolean")


def _finite_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.where(values.map(lambda value: pd.notna(value) and math.isfinite(float(value))))


def _safe_json_value(value):
    """Convert unknown/nonfinite observations to JSON null without inventing zero.

    Finite operands can still overflow during multiplication or summation. The
    result boundary therefore checks intermediates as well as the final value.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe_json_value(item) for item in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (int, float)):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    return None


def _round_result(value: float, digits: int) -> float:
    """Preserve SQLite ROUND midpoint behavior at one shared result boundary."""
    decimal = Decimal(str(value))
    with localcontext() as context:
        # Large finite values may have hundreds of integer digits. The default
        # Decimal precision would reject their quantization even when finite.
        context.prec = max(28, decimal.adjusted() + digits + 3)
        return float(decimal.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def _timestamp(value, zone: str):
    if pd.isna(value) or str(value).strip().casefold() in UNKNOWN_TEXT:
        return pd.NaT
    if isinstance(value, (int, float, bool)):
        # A number without an explicit epoch/unit contract is not a timestamp.
        return pd.NaT
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            return pd.NaT
        if stamp.tzinfo is not None:
            return stamp.tz_convert("UTC")
        if zone != "unknown":
            return stamp.tz_localize(zone, ambiguous="NaT", nonexistent="NaT").tz_convert("UTC")
        return stamp
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


class CalculationEngine:
    """Calculate from an explicitly selected snapshot and its optional history.

    The caller owns source selection and authorization. This class never reads a
    file, writes SQL, trains a model, imports data, or changes a source frame.
    """
    registry = METRIC_REGISTRY

    def __init__(self, incidents: pd.DataFrame, events: pd.DataFrame | None = None,
                 context: CalculationContext | None = None):
        if "incident_id" not in incidents.columns:
            raise ValueError("Incident snapshots require incident_id.")
        self.context = context or CalculationContext("synthetic-demo", "Seeded synthetic incidents")
        self.incidents = incidents.copy(deep=True).reset_index(drop=True)
        identifiers = self.incidents.incident_id.astype("string").str.strip()
        if not _known(identifiers).all() or identifiers.duplicated().any():
            raise ValueError("Expected one snapshot per nonmissing incident_id; pass event history separately.")
        self.incidents["incident_id"] = identifiers
        event_columns = [c for c in ["incident_id", "source_row", "event_id", "event_at", "source_sequence"]
                         if events is not None and c in events.columns]
        self.events = events[event_columns].copy(deep=True).reset_index(drop=True) if events is not None else None
        self._duration_cache = None
        self._event_cache = None

    def _series(self, name) -> pd.Series:
        if name in self.incidents:
            return self.incidents[name]
        return pd.Series(pd.NA, index=self.incidents.index, dtype="object")

    def _states(self):
        return self._series("status").astype("string").str.strip().str.casefold()

    def _membership(self, included=None, reason=None, numerator=None, values=None, frame=None):
        source = self.incidents if frame is None else frame
        rows = pd.DataFrame(index=source.index)
        for name in ["incident_id", "source_row", "event_id"]:
            if name in source:
                rows[name] = source[name]
        rows["included"] = True if included is None else included.fillna(False).astype(bool)
        rows["reason"] = "Included" if reason is None else reason
        if numerator is not None:
            rows["numerator_member"] = numerator.fillna(False).astype(bool)
        if values is not None:
            rows["contribution_value"] = values
        return rows.reset_index(drop=True)

    def _result(self, metric_id, value, eligible, excluded, numerator=None, denominator=None,
                warnings=(), assumptions=(), reason=None, parameters=None, unit=None):
        definition = self.registry[metric_id]
        clean_numerator, clean_denominator = _safe_json_value(numerator), _safe_json_value(denominator)
        if ((numerator is not None and clean_numerator is None)
                or (denominator is not None and clean_denominator is None)):
            value, reason = None, "Calculation exceeded finite numerical precision."
            warnings = (*warnings, "A nonfinite intermediate result was replaced with explicit unknown.")
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                value = None
            if value is None or not math.isfinite(value):
                value, reason = None, "Calculation did not produce a finite value."
            elif definition.rounding_digits == 0:
                value = int(value)
            else:
                value = _round_result(value, definition.rounding_digits)
        return CalculationResult(
            metric_id, value, "available" if value is not None else "unavailable", unit or definition.unit,
            {"start": self.context.observation_start, "end": self.context.observation_end,
             "timezone": self.context.timezone}, self.context.dataset_id, self.context.source_name,
            self.context.source_kind, self.context.import_id, int(eligible), int(excluded), definition.version,
            datetime.now(timezone.utc).isoformat(), clean_numerator, clean_denominator,
            tuple(dict.fromkeys((*self.context.warnings, *warnings))), tuple(assumptions), reason,
            _safe_json_value(parameters or {}))

    def _duration_evidence(self):
        if self._duration_cache is not None:
            return self._duration_cache
        n = len(self.incidents)
        duration = pd.Series(float("nan"), index=self.incidents.index, dtype=float)
        reasons = pd.Series("Missing or unrecognized resolution status", index=self.incidents.index)
        resolved = self._states().isin(RESOLVED_STATES)
        warnings = []
        if self.context.source_kind == "demo" and "resolution_time_minutes" in self.incidents:
            minutes = _finite_numeric(self.incidents.resolution_time_minutes)
            valid = resolved & minutes.notna() & minutes.ge(0)
            duration.loc[valid] = minutes.loc[valid] / 60.0
            reasons.loc[resolved] = "Missing, invalid, or negative duration minutes"
            warnings.append("Synthetic demo uses validated resolution_time_minutes; no business-hours SLA clock is reconstructed.")
        else:
            opened = self._series("opened_at").map(lambda value: _timestamp(value, self.context.timezone))
            closed = self._series("resolved_at").map(lambda value: _timestamp(value, self.context.timezone))
            reasons.loc[resolved] = "Missing or invalid opened/resolved timestamp"
            # Subtract timestamps pairwise: a naive/aware mismatch is invalid,
            # rather than a reason to silently assign the missing time zone.
            for idx in self.incidents.index[resolved]:
                if pd.isna(opened[idx]) or pd.isna(closed[idx]):
                    continue
                try:
                    hours = (closed[idx] - opened[idx]).total_seconds() / 3600
                except (TypeError, ValueError, OverflowError):
                    reasons[idx] = "Incompatible timestamp timezones"
                    continue
                if not math.isfinite(hours) or hours < 0:
                    reasons[idx] = "Negative or invalid resolution interval"
                    continue
                duration[idx] = hours
            if self.context.timezone == "unknown":
                warnings.append("Source timezone is unknown; naive source-clock durations may be affected by daylight-saving changes.")
        valid = duration.notna()
        reasons.loc[valid] = "Included: valid gross resolution duration"
        if (~valid).any():
            warnings.append(f"{int((~valid).sum())} of {n} incident snapshots excluded from duration calculations.")
        self._duration_cache = (duration, reasons, warnings)
        return self._duration_cache

    def _field_valid(self, name):
        values = self._series(name)
        valid = _known(values)
        if name.endswith("_at"):
            return valid & values.map(lambda value: pd.notna(_timestamp(value, self.context.timezone)))
        if name in {"source_sla_met", "sla_breached"}:
            return _bool_values(values).notna()
        if name in {"response_time_minutes", "resolution_time_minutes", "reassignment_count", "reopen_count"}:
            numeric = _finite_numeric(values)
            valid = numeric.notna() & numeric.ge(0)
            if name.endswith("_count"):
                valid &= numeric.mod(1).eq(0)
            return valid
        if name == "status":
            return self._states().isin(KNOWN_STATES)
        if name == "priority":
            return values.astype("string").str.strip().str.casefold().isin(
                HIGH_PRIORITIES | {"medium", "moderate", "low", "3 - moderate", "4 - low"})
        return valid

    def _compute(self, metric_id: str, parameters: Mapping[str, Any] | None = None):
        if metric_id not in self.registry:
            raise ValueError(f"Unknown metric_id: {metric_id}")
        parameters = dict(parameters or {})
        if metric_id in SCENARIO_PARAMETERS:
            return self._scenario(metric_id, parameters)
        allowed = {"field"} if metric_id == "field_completeness" else set()
        if set(parameters) - allowed:
            raise ValueError(f"Unexpected parameters for {metric_id}: {sorted(set(parameters) - allowed)}")
        n = len(self.incidents)
        if metric_id == "total_event_count":
            if self.events is None or not {"incident_id", "event_at"}.issubset(self.events.columns):
                result = self._result(metric_id, None, 0, 0, reason="No event history with identifiers and timestamps was supplied.")
                return result, self._membership(frame=pd.DataFrame())
            if self._event_cache is None:
                valid_id = _known(self.events.incident_id)
                valid_time = self.events.event_at.map(lambda value: pd.notna(_timestamp(value, self.context.timezone)))
                included = valid_id & valid_time
                reasons = pd.Series("Included: valid event observation", index=self.events.index)
                reasons.loc[~valid_id] = "Missing event incident identifier"
                reasons.loc[valid_id & ~valid_time] = "Missing or invalid event timestamp"
                self._event_cache = included, reasons
            included, reasons = self._event_cache
            count = int(included.sum())
            return self._result(metric_id, count, count, len(included) - count), self._membership(included, reasons, frame=self.events)
        if metric_id == "unique_incident_count":
            return self._result(metric_id, n, n, 0), self._membership()
        states = self._states()
        resolved = states.isin(RESOLVED_STATES)
        if metric_id in {"resolved_incident_rate", "unresolved_incident_count"}:
            known = states.isin(KNOWN_STATES)
            member = resolved if metric_id == "resolved_incident_rate" else known & ~resolved
            denominator = int(known.sum())
            value = 100.0 * member.sum() / denominator if denominator else None
            if metric_id == "unresolved_incident_count":
                value = int(member.sum()) if denominator or n == 0 else None
            reasons = pd.Series("Included: recognized source status", index=self.incidents.index)
            reasons.loc[~known] = "Missing or unrecognized status"
            result = self._result(metric_id, value, denominator, n - denominator,
                                  int(member.sum()), denominator,
                                  reason="No incidents with a recognized status." if value is None else None)
            return result, self._membership(known, reasons, member)
        if metric_id in {"source_sla_attainment", "demo_sla_attainment"}:
            source = metric_id == "source_sla_attainment"
            field_name = "source_sla_met" if source else "sla_breached"
            basis_supported = source or self.context.source_kind == "demo"
            values = _bool_values(self._series(field_name))
            included = resolved & values.notna() & basis_supported
            met = included & (values.eq(True) if source else values.eq(False)).fillna(False)
            denominator, numerator = int(included.sum()), int(met.sum())
            reasons = pd.Series("Included: known final source outcome" if source else "Included: known resolved demo outcome",
                                index=self.incidents.index)
            reasons.loc[~resolved] = "Unresolved or unknown status; terminal outcome not eligible"
            reasons.loc[resolved & values.isna()] = "Missing or invalid SLA outcome"
            warning = ("Source-reported SLA field; contractual policy and compliance are not independently verified."
                       if source else "Simplified synthetic demo policy in elapsed minutes; not a customer SLA agreement.")
            if not basis_supported:
                reasons[:] = "Demo policy is not applicable to this source"
            value = numerator * 100.0 / denominator if denominator else None
            reason = ("Demo-policy outcomes are unavailable for event-log sources." if not basis_supported
                      else "No resolved incidents with known eligible SLA outcomes.")
            result = self._result(metric_id, value, denominator, n - denominator, numerator, denominator,
                                  warnings=(warning,), reason=reason if value is None else None)
            return result, self._membership(included, reasons, met)
        if metric_id in {"mean_resolution_hours", "median_resolution_hours"}:
            durations, reasons, warnings = self._duration_evidence()
            included, count = durations.notna(), int(durations.notna().sum())
            try:
                numerator = math.fsum(durations.loc[included].tolist()) if count else None
            except OverflowError:
                numerator = float("inf")  # converted to explicit unknown at the result boundary
            value = (numerator / count if metric_id == "mean_resolution_hours"
                     else durations.quantile(0.5, interpolation="linear")) if count else None
            result = self._result(metric_id, value, count, n - count,
                                  numerator if metric_id == "mean_resolution_hours" else None, count,
                                  warnings=warnings,
                                  assumptions=("Gross elapsed duration includes waiting; no pause, holiday, or business calendar adjustment.",),
                                  reason="No valid resolved-incident durations." if not count else None)
            return result, self._membership(included, reasons, values=durations)
        if metric_id in {"assignment_completeness", "field_completeness"}:
            field_name = "assignment_group" if metric_id == "assignment_completeness" else parameters.get("field")
            if field_name not in COMPLETENESS_FIELDS:
                raise ValueError("field must name a supported completeness field.")
            valid = self._field_valid(field_name)
            present = field_name in self.incidents
            value = 100.0 * valid.sum() / n if n and present else None
            reasons = pd.Series("Included in denominator: known valid field", index=self.incidents.index)
            reasons.loc[~valid] = "Included in denominator: missing or invalid field"
            result = self._result(metric_id, value, n if present else 0, 0 if present else n,
                                  int(valid.sum()) if present else None, n if present else 0,
                                  warnings=(f"Unknown {field_name} values are retained in the incident denominator.",),
                                  parameters={"field": field_name},
                                  reason=("No incident snapshots." if present else f"Source field {field_name} is unavailable.") if value is None else None)
            return result, self._membership(pd.Series(present, index=self.incidents.index), reasons, valid)
        if metric_id == "high_priority_incident_count":
            valid = self._field_valid("priority")
            high = self._series("priority").astype("string").str.strip().str.casefold().isin(HIGH_PRIORITIES)
            reasons = pd.Series("Included: known priority", index=self.incidents.index)
            reasons.loc[~valid] = "Missing or unrecognized priority"
            count = int(high.sum())
            value = count if valid.any() or n == 0 else None
            return self._result(metric_id, value, int(valid.sum()), int((~valid).sum()), count,
                                reason="No recognized priorities." if value is None else None), self._membership(valid, reasons, high)
        raise AssertionError("Registered metric has no implementation.")

    def calculate(self, metric_id: str, parameters: Mapping[str, Any] | None = None) -> CalculationResult:
        return self._compute(metric_id, parameters)[0]

    def inspect(self, metric_id: str, parameters: Mapping[str, Any] | None = None) -> dict:
        result, records = self._compute(metric_id, parameters)
        return {"definition": self.registry[metric_id].to_dict(), "result": result.to_dict(), "records": records}

    def summary(self) -> dict[str, CalculationResult]:
        return {metric_id: self.calculate(metric_id) for metric_id in self.registry
                if metric_id not in SCENARIO_PARAMETERS and metric_id != "field_completeness"}

    def by_dimension(self, dimension: str) -> pd.DataFrame:
        if dimension not in {"priority", "category", "assignment_group", "affected_service"}:
            raise ValueError("Unsupported reporting dimension.")
        groups = self._series(dimension).astype("string").str.strip().where(_known(self._series(dimension)), "Unknown")
        metric = "demo_sla_attainment" if self.context.source_kind == "demo" else "source_sla_attainment"
        rows = []
        for name in groups.drop_duplicates():
            subset = self.incidents.loc[groups.eq(name)].reset_index(drop=True)
            child = CalculationEngine(subset, context=self.context)
            sla = child.calculate(metric)
            mean = child.calculate("mean_resolution_hours")
            rows.append({"dimension": str(name), "incidents": len(subset),
                         "breaches": int(sla.denominator - sla.numerator) if sla.denominator else None,
                         "compliance_pct": sla.value, "avg_resolution_hours": mean.value,
                         "eligible_outcomes": sla.eligible_count, "excluded_outcomes": sla.excluded_count,
                         "valid_duration_count": mean.eligible_count})
        return pd.DataFrame(rows, columns=["dimension", "incidents", "breaches", "compliance_pct", "avg_resolution_hours",
                                           "eligible_outcomes", "excluded_outcomes", "valid_duration_count"]).sort_values(
            "compliance_pct", na_position="first", kind="stable").reset_index(drop=True)

    def monthly_trend(self) -> pd.DataFrame:
        field_name = "opened_at" if "opened_at" in self.incidents else "created_at"
        months = self._series(field_name).map(lambda value: _timestamp(value, self.context.timezone)).map(
            lambda value: value.strftime("%Y-%m") if pd.notna(value) else "Unknown")
        metric = "demo_sla_attainment" if self.context.source_kind == "demo" else "source_sla_attainment"
        rows = []
        for month in sorted(months.unique()):
            child = CalculationEngine(self.incidents.loc[months.eq(month)], context=self.context)
            result = child.calculate(metric)
            rows.append({"month": month, "incidents": len(child.incidents), "compliance_pct": result.value,
                         "eligible_outcomes": result.eligible_count, "excluded_outcomes": result.excluded_count})
        return pd.DataFrame(rows, columns=["month", "incidents", "compliance_pct", "eligible_outcomes", "excluded_outcomes"])

    def _scenario(self, metric_id, parameters):
        allowed = SCENARIO_PARAMETERS[metric_id]
        if set(parameters) - allowed:
            raise ValueError(f"Unexpected scenario parameters: {sorted(set(parameters) - allowed)}")
        assumptions = ("Scenario inputs are supplied by the caller, not measured automatically by OKai.",
                       "Baseline and observed values must describe the same scope and processing stage.")
        missing = sorted(allowed - set(parameters))
        reason = f"Required scenario inputs are missing: {', '.join(missing)}." if missing else None
        values = {}
        for name in allowed - {"currency"}:
            value = parameters.get(name)
            if isinstance(value, bool):
                reason = "Scenario numeric inputs cannot be booleans."
                continue
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                reason = reason or f"{name} must be a finite number."
                continue
            if not math.isfinite(number):
                reason = f"{name} must be a finite number."
                continue
            if number < 0 and name != "hours_saved":
                reason = f"{name} cannot be negative."
            values[name] = number
        currency = parameters.get("currency")
        if "currency" in allowed and (not isinstance(currency, str) or len(currency.strip()) != 3 or not currency.isalpha()):
            reason = reason or "Provide an explicit three-letter currency code."
        for name in allowed & {"incident_count", "processed_records"}:
            if name in values and values[name] % 1:
                reason = f"{name} must be a whole record count."
        if metric_id == "time_reduction_pct" and values.get("baseline_hours") == 0:
            reason = "Baseline hours must be greater than zero."
        if metric_id == "processing_throughput" and values.get("elapsed_seconds") == 0:
            reason = "Elapsed seconds must be greater than zero."
        if metric_id == "cost_per_incident" and values.get("incident_count") == 0:
            reason = "Eligible incident count must be greater than zero."
        value = numerator = denominator = None
        unit = self.registry[metric_id].unit
        if not reason:
            if metric_id in {"time_saved_hours", "time_reduction_pct"}:
                numerator = values["baseline_hours"] - values["observed_hours"]
                denominator = values["baseline_hours"]
                value = numerator if metric_id == "time_saved_hours" else 100 * numerator / denominator
            elif metric_id == "estimated_labor_value":
                value = values["hours_saved"] * values["hourly_labor_cost"]
                unit = currency.upper() + " estimated capacity value"
                assumptions += ("Estimated labor capacity value is not evidence of realized cash savings.",)
            elif metric_id == "processing_throughput":
                numerator, denominator = values["processed_records"], values["elapsed_seconds"]
                value = numerator / denominator
            elif metric_id == "cost_per_incident":
                numerator, denominator = values["operational_cost"], values["incident_count"]
                value = numerator / denominator
                unit = currency.upper() + "/incident"
        result = self._result(metric_id, value, 1 if not reason else 0, 0 if not reason else 1,
                              numerator, denominator, assumptions=assumptions, reason=reason,
                              parameters=parameters, unit=unit)
        records = pd.DataFrame([{"included": not bool(reason), "reason": reason or "Included: explicit scenario inputs",
                                 "contribution_value": result.value}])
        return result, records

    def alerts(self, config: ThresholdConfig | None = None, *, as_of: str | None = None) -> pd.DataFrame:
        """Evaluate explainable investigation rules, never predictions or compliance.

        `as_of` is mandatory for age/deadline rules. In particular, a historical
        source with an unknown zone is never silently compared with today's UTC.
        """
        config = config or ThresholdConfig()
        states = self._states()
        unresolved = states.isin(KNOWN_STATES) & ~states.isin(RESOLVED_STATES)
        rows = []
        def append(rule, incident_id, observed, threshold, message):
            rows.append({"rule_id": rule, "incident_id": incident_id, "observed_value": observed,
                         "threshold": threshold, "message": message, "rule_basis": config.rule_basis,
                         "as_of": as_of, "dataset_id": self.context.dataset_id, "import_id": self.context.import_id,
                         "source_name": self.context.source_name, "formula_version": FORMULA_VERSION})
        backlog = int(unresolved.sum())
        if backlog > config.backlog_threshold:
            append("unresolved_backlog", None, backlog, config.backlog_threshold,
                   "Investigate unresolved incident volume above the configured threshold.")
        high = self._series("priority").astype("string").str.strip().str.casefold().isin(HIGH_PRIORITIES)
        no_group = ~_known(self._series("assignment_group"))
        if config.high_priority_unassigned:
            for idx in self.incidents.index[unresolved & high & no_group]:
                append("high_priority_unassigned", str(self.incidents.at[idx, "incident_id"]), 1, 0,
                       "Investigate a high-priority unresolved incident without a known assignment group.")
        stamp = _timestamp(as_of, self.context.timezone) if as_of is not None else pd.NaT
        if as_of is not None and pd.isna(stamp):
            raise ValueError("as_of must be a valid timestamp in the explicitly selected source timezone.")
        if pd.notna(stamp):
            snapshot_end = _timestamp(self.context.observation_end, self.context.timezone)
            if self.context.observation_end is not None and pd.isna(snapshot_end):
                raise ValueError("The source observation_end is invalid; temporal rules cannot establish snapshot timing.")
            if pd.isna(snapshot_end):
                if "event_at" in self.incidents:
                    observations = self.incidents.event_at
                elif self.events is not None and "event_at" in self.events:
                    observations = self.events.event_at
                elif self.context.source_kind == "demo":
                    observations = self._series("created_at")
                else:
                    observations = pd.Series(dtype=object)
                valid_observations = [value for value in observations.map(
                    lambda value: _timestamp(value, self.context.timezone)) if pd.notna(value)]
                try:
                    snapshot_end = max(valid_observations) if valid_observations else pd.NaT
                except TypeError as exc:
                    raise ValueError("Source snapshot observations use incompatible timezone awareness.") from exc
            if pd.isna(snapshot_end):
                raise ValueError("Temporal rules require an observation_end or valid snapshot event timestamp.")
            try:
                earlier_than_snapshot = stamp < snapshot_end
            except TypeError as exc:
                raise ValueError("as_of and snapshot observation_end must have compatible timezone awareness.") from exc
            if earlier_than_snapshot:
                raise ValueError("as_of precedes the latest source snapshot; historical point-in-time replay is not implemented.")
            opened_field = "opened_at" if "opened_at" in self.incidents else "created_at"
            for idx in self.incidents.index[unresolved]:
                opened = _timestamp(self._series(opened_field)[idx], self.context.timezone)
                if pd.notna(opened):
                    try:
                        age = (stamp - opened).total_seconds() / 3600
                    except TypeError as exc:
                        raise ValueError("as_of and source timestamps must have compatible timezone awareness.") from exc
                    if age > config.age_hours:
                        append("incident_age", str(self.incidents.at[idx, "incident_id"]), round(age, 2), config.age_hours,
                               "Investigate an unresolved incident older than the configured age threshold.")
                deadline = _timestamp(self._series("sla_deadline_at")[idx], self.context.timezone)
                if pd.notna(deadline):
                    try:
                        remaining = (deadline - stamp).total_seconds() / 60
                    except TypeError as exc:
                        raise ValueError("Provided SLA deadline and as_of use incompatible timezones.") from exc
                    if 0 <= remaining <= config.sla_warning_minutes:
                        append("provided_sla_deadline", str(self.incidents.at[idx, "incident_id"]), round(remaining, 2),
                               config.sla_warning_minutes,
                               "Review an approaching source-provided deadline; policy validity remains the source owner's responsibility.")
        return pd.DataFrame(rows, columns=["rule_id", "incident_id", "observed_value", "threshold", "message", "rule_basis",
                                           "as_of", "dataset_id", "import_id", "source_name", "formula_version"])


SCENARIO_PARAMETERS = MappingProxyType({
    "time_saved_hours": frozenset({"baseline_hours", "observed_hours"}),
    "time_reduction_pct": frozenset({"baseline_hours", "observed_hours"}),
    "estimated_labor_value": frozenset({"hours_saved", "hourly_labor_cost", "currency"}),
    "processing_throughput": frozenset({"processed_records", "elapsed_seconds"}),
    "cost_per_incident": frozenset({"operational_cost", "incident_count", "currency"}),
})


@dataclass(frozen=True)
class ThresholdConfig:
    age_hours: float = 72.0
    backlog_threshold: int = 100
    sla_warning_minutes: float = 60.0
    high_priority_unassigned: bool = True
    rule_basis: str = "Configurable investigation thresholds; not verified contractual SLA rules."

    def __post_init__(self):
        for name in ["age_hours", "backlog_threshold", "sla_warning_minutes"]:
            value = getattr(self, name)
            try:
                valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f"{name} must be a finite nonnegative threshold.")
        if self.backlog_threshold % 1:
            raise ValueError("backlog_threshold must be a whole incident count.")
        if not isinstance(self.high_priority_unassigned, bool) or not isinstance(self.rule_basis, str) or not self.rule_basis.strip():
            raise ValueError("Provide a Boolean assignment rule and a nonempty rule basis.")
