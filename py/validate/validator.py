"""Deterministic implementation of the validation contract V1--V10.

The normalisation layer deliberately does not infer chart assignment, statement
scope, or subtotal composition.  This module therefore consumes those fields
when callers supply them, and never fabricates them when they are absent.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isclose
from typing import Any, Iterable, Mapping, Sequence

from contract.models import Flag


RULE_SEVERITY: dict[str, str] = {
    "V1": "blocking", "V2": "blocking", "V3": "note_required",
    "V4": "note_required", "V5": "note_required", "V6": "note_required",
    "V7": "blocking", "V8": "blocking", "V9": "advisory",
    "V10": "note_required",
}

# Each entry is (component std_id, sign).  A definition is only evaluated when
# every component is disclosed for the fiscal year in question.
SUBTOTAL_FORMULAS: dict[str, tuple[tuple[str, int], ...]] = {
    "PL_GKV-GESAMTLEISTUNG": (("PL_GKV-1", 1), ("PL_GKV-2", 1),
                              ("PL_GKV-3", 1), ("PL_GKV-4", 1)),
    "PL_UKV-3": (("PL_UKV-1", 1), ("PL_UKV-2", -1)),
    "PL_UKV-BRUTTOERGEBNIS": (("PL_UKV-1", 1), ("PL_UKV-2", -1)),
}


@dataclass(frozen=True)
class ValidationResult:
    """Flags and the notes that can be copied to a rendered slide."""

    flags: list[Flag]

    @property
    def footnotes_auto(self) -> list[str]:
        return [flag.note for flag in self.flags if flag.rule in {"V3", "V4", "V5", "V6"} and flag.note]


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    raise TypeError(f"Expected a mapping or Pydantic model, got {type(value)!r}")


def _flag(rule: str, message: str, note: str | None = None) -> Flag:
    """Build a contract Flag.

    ``contract.models.RuleId`` currently ends at V9 although ``rules.json``
    defines V10.  ``model_construct`` preserves the contract-shaped Flag for
    V10 without changing files outside this owned package.
    """
    values = {"rule": rule, "severity": RULE_SEVERITY[rule], "message": message, "note": note}
    if rule == "V10":
        return Flag.model_construct(**values)
    return Flag(**values)  # type: ignore[arg-type]


def _years(values: Mapping[Any, Any]) -> dict[int, float]:
    result: dict[int, float] = {}
    for year, value in values.items():
        if value is not None:
            result[int(year)] = float(value)
    return result


def _normalise_label(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _is_revenue_label(value: Any) -> bool:
    # Avoid matching terms such as "revenue growth" differently from a chart
    # entitled "Revenue in EUR m"; both present a Revenue series.
    return "revenue" in _normalise_label(value)


def _series_name(item: Mapping[str, Any]) -> str:
    return str(item.get("title") or item.get("label") or item.get("metric") or item.get("raw_label") or item.get("std_id") or "series")


def _chart_series(charted_series: Iterable[Any] | None, segment_figures: Iterable[Any]) -> list[dict[str, Any]]:
    series = [_model_dump(item) for item in charted_series or ()]
    # SegmentExtraction figures are explicitly revenue/revenue_share series.
    # Their stated basis must survive into V1 even before a GUI block exists.
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for figure in segment_figures:
        value = _model_dump(figure)
        key = (value.get("segment_type"), value.get("segment_name"), value.get("metric"),
               value.get("presentation_basis"), value.get("unit"))
        target = grouped.setdefault(key, {**value, "title": value.get("metric"), "values": {},
                                          "charted": value.get("metric") == "revenue"})
        target["values"][value["fiscal_year"]] = value["value"]
    series.extend(grouped.values())
    return series


def _components(record: Mapping[str, Any]) -> tuple[tuple[str, int], ...] | None:
    explicit = record.get("components") or record.get("component_std_ids")
    if explicit is not None:
        if isinstance(explicit, Mapping):
            return tuple((str(code), int(sign)) for code, sign in explicit.items())
        return tuple((str(code), 1) for code in explicit)
    return SUBTOTAL_FORMULAS.get(str(record.get("std_id") or ""))


def _is_cost(record: Mapping[str, Any]) -> bool:
    std_id = str(record.get("std_id") or "")
    label = _normalise_label(record.get("raw_label"))
    return (std_id.startswith(("PL_GKV-5", "PL_GKV-6", "PL_GKV-7", "PL_GKV-8", "PL_GKV-12", "PL_GKV-13", "PL_GKV-14", "PL_UKV-2", "PL_UKV-4", "PL_UKV-5", "PL_UKV-7", "PL_UKV-11", "PL_UKV-12", "PL_UKV-13"))
            or any(word in label for word in ("aufwendung", "kosten", "abschreibung", "material", "personal", "steuer", "zinsen")))


def validate_normalised(
    normalised: Mapping[str, Any],
    segments: Any | None = None,
    *,
    charted_series: Iterable[Any] | None = None,
) -> ValidationResult:
    """Validate P0 and segment evidence, returning every applicable Flag.

    ``charted_series`` is optional but required for V1/V2/V7 checks on P0
    rows: each item may contain ``title``/``label``, ``presentation_basis``,
    ``unit``, ``values`` and/or ``row``.  Segment figures are validated as
    their own disclosed revenue series.
    """
    rows = [_model_dump(row) for row in normalised.get("rows", ())]
    segment_figures = list(getattr(segments, "figures", ()) if segments is not None else ())
    flags: list[Flag] = []

    # V1 and V2: chart data is the only source that establishes a "series".
    for series in _chart_series(charted_series, segment_figures):
        if not series.get("charted", True):
            continue
        name = _series_name(series)
        basis = series.get("presentation_basis")
        if _is_revenue_label(name) and basis != "umsatzerloese":
            flags.append(_flag("V1", f"{name} is labelled Revenue but presentation_basis is {basis!r}, not 'umsatzerloese'."))
        units = series.get("units")
        if units is None:
            units = [series["unit"]] if series.get("unit") is not None else []
        distinct_units = sorted({str(unit) for unit in units if unit is not None})
        if len(distinct_units) > 1:
            flags.append(_flag("V2", f"{name} mixes units: {', '.join(distinct_units)}."))
        row = series.get("row")
        if row is not None:
            row = _model_dump(row)
        elif "raw_label" in series or "std_id" in series:
            row = series
        if row is not None and not row.get("std_id"):
            flags.append(_flag("V7", f"Charted series {name} uses unmapped label {row.get('raw_label')!r}."))

    # V3/V4/V5 operate on all disclosed P0 lines, not merely selected charts.
    for row in rows:
        name = _series_name(row)
        values = _years(row.get("values", {}))
        scope = row.get("scope_by_fy") or row.get("scope_flag")
        method = row.get("method_by_fy") or row.get("method_flag")
        for previous, current in zip(sorted(values), sorted(values)[1:]):
            if current != previous + 1:
                continue
            if isinstance(scope, Mapping) and scope.get(previous) != scope.get(current):
                flags.append(_flag("V3", f"{name}: consolidation perimeter changes from FY{previous} to FY{current}.", "Explain the perimeter change and comparability impact."))
            if isinstance(method, Mapping) and method.get(previous) != method.get(current):
                flags.append(_flag("V4", f"{name}: method changes from {method.get(previous)} in FY{previous} to {method.get(current)} in FY{current}.", "Explain the GKV/UKV method change and comparability impact."))
            prior = values[previous]
            if prior == 0:
                continue
            change = (values[current] - prior) / abs(prior)
            if abs(change) > 0.15:
                flags.append(_flag("V5", f"{name}: FY{current} changed {change:+.1%} versus FY{previous}.", "Explain the material year-on-year movement."))

    # V6: calculate ratios only where reported revenue and a cost line coexist.
    revenue: dict[int, float] = {}
    for row in rows:
        if row.get("std_id") in {"PL_GKV-1", "PL_UKV-1"}:
            revenue.update(_years(row.get("values", {})))
    for row in rows:
        if not _is_cost(row):
            continue
        ratios = {year: abs(value) / abs(revenue[year]) for year, value in _years(row.get("values", {})).items() if year in revenue and revenue[year] != 0}
        for previous, current in zip(sorted(ratios), sorted(ratios)[1:]):
            if current == previous + 1 and abs(ratios[current] - ratios[previous]) > 0.05:
                flags.append(_flag("V6", f"{_series_name(row)}: cost ratio changed {(ratios[current] - ratios[previous]) * 100:+.1f}pp from FY{previous} to FY{current}.", "Explain the cost-ratio trend break."))

    # V8 uses explicit balance-sheet totals if P0 is extended to balance sheets.
    by_id = {str(row.get("std_id")): row for row in rows if row.get("std_id")}
    assets = by_id.get("BS-A")
    liabilities = by_id.get("BS-P")
    if assets and liabilities:
        for year in sorted(set(_years(assets.get("values", {}))) & set(_years(liabilities.get("values", {})))):
            asset_value, liability_value = _years(assets["values"])[year], _years(liabilities["values"])[year]
            if not isclose(asset_value, liability_value, abs_tol=0.01):
                flags.append(_flag("V8", f"FY{year}: Aktiva is {asset_value:.2f} EUR while Passiva is {liability_value:.2f} EUR (delta {asset_value - liability_value:+.2f} EUR)."))

    # V9 is advisory but must remain visible for both explicit loss coverage and
    # a reported negative total-equity position.
    for row in rows:
        values = _years(row.get("values", {}))
        if row.get("std_id") == "BS-P-NEGEQ":
            flags.append(_flag("V9", f"Negative equity position disclosed: {_series_name(row)}."))
        elif row.get("std_id") == "BS-P.A":
            for year, value in values.items():
                if value < 0:
                    flags.append(_flag("V9", f"FY{year}: total equity is negative at {value:.2f} EUR."))

    # V10 requires row_type plus a stated/known component definition.  Do not
    # infer components from row order or incomplete component sets.
    for subtotal in (row for row in rows if row.get("row_type") == "subtotal"):
        components = _components(subtotal)
        if not components:
            continue
        subtotal_values = _years(subtotal.get("values", {}))
        component_rows = {code: by_id.get(code) for code, _ in components}
        for year, actual in subtotal_values.items():
            if any(component_rows[code] is None or year not in _years(component_rows[code].get("values", {})) for code, _ in components):
                continue
            expected = sum(sign * _years(component_rows[code]["values"])[year] for code, sign in components)
            if not isclose(actual, expected, abs_tol=0.01):
                flags.append(_flag("V10", f"FY{year}: subtotal {_series_name(subtotal)} expected {expected:.2f} EUR, actual {actual:.2f} EUR, delta {actual - expected:+.2f} EUR.", "Reconcile the subtotal to its disclosed component lines."))

    return ValidationResult(flags=flags)


def validate(normalised: Mapping[str, Any], segments: Any | None = None, *, charted_series: Iterable[Any] | None = None) -> list[Flag]:
    """Convenience API returning the contract Flag objects directly."""
    return validate_normalised(normalised, segments, charted_series=charted_series).flags
