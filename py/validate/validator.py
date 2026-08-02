"""Deterministic implementation of the validation contract V1--V12.

The normalisation layer deliberately does not infer chart assignment, statement
scope, or subtotal composition.  This module therefore consumes those fields
when callers supply them, and never fabricates them when they are absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any, Callable, Iterable, Mapping

from contract.models import Flag


RULE_SEVERITY: dict[str, str] = {
    "V1": "blocking", "V2": "blocking", "V3": "note_required",
    "V4": "note_required", "V5": "note_required", "V6": "note_required",
    "V7": "blocking", "V8": "blocking", "V9": "advisory",
    "V10": "note_required", "V11": "blocking", "V12": "blocking",
}

V5_ABSOLUTE_MATERIALITY_EUR = 1_000_000.0
V11_ONE_OFF_MATERIALITY_REVENUE_PCT = 0.01
V11_ONE_OFF_MATERIALITY_EUR_FLOOR = 1_000_000.0

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
    """Build a Flag validated by the current contract model."""
    return Flag(rule=rule, severity=RULE_SEVERITY[rule], message=message, note=note)  # type: ignore[arg-type]


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


def _is_ebitda_label(value: Any) -> bool:
    return "ebitda" in _normalise_label(value)


def _series_name(item: Mapping[str, Any]) -> str:
    return str(item.get("title") or item.get("label") or item.get("metric") or item.get("raw_label") or item.get("std_id") or "series")


def _assigned_series(
    charted_series: Iterable[Any] | None,
    slot_assignments: Mapping[str, Any] | Iterable[Any] | None,
    axis_labels: Mapping[str, str] | None,
) -> list[dict[str, Any]]:
    """Return only series actually assigned to a slide slot.

    ``slot_assignments`` accepts either ``{slot: series_id}`` or
    ``{slot: {series_id: ..., axis_label: ...}}``.  An assignment may also
    embed a complete series.  ``axis_labels`` is keyed by slot (or series id)
    and is deliberately separate from a source title.
    """
    available = [_model_dump(item) for item in charted_series or ()]
    by_id = {str(item["id"]): item for item in available if item.get("id") is not None}
    if isinstance(slot_assignments, Mapping):
        assignments = [{"slot": slot, "assignment": assignment} for slot, assignment in slot_assignments.items()]
    else:
        assignments = []
        for item in slot_assignments or ():
            assignment = _model_dump(item)
            assignments.append({"slot": assignment.get("slot"), "assignment": assignment})

    selected: list[dict[str, Any]] = []
    for entry in assignments:
        slot = str(entry["slot"])
        assignment = entry["assignment"]
        if isinstance(assignment, str):
            source = by_id.get(assignment)
            assignment_data: dict[str, Any] = {"series_id": assignment}
        else:
            assignment_data = _model_dump(assignment)
            series_id = assignment_data.get("series_id") or assignment_data.get("id") or assignment_data.get("block_id")
            source = by_id.get(str(series_id)) if series_id is not None else assignment_data.get("series")
            if source is not None:
                source = _model_dump(source)
            elif "values" in assignment_data or "row" in assignment_data:
                source = assignment_data
        if source is None:
            continue
        series = {**source, **{key: value for key, value in assignment_data.items() if key not in {"series", "series_id", "block_id"}}}
        series["slot"] = slot
        series_id = str(series.get("id") or assignment_data.get("series_id") or "")
        series["axis_label"] = assignment_data.get("axis_label") or (axis_labels or {}).get(slot) or (axis_labels or {}).get(series_id)
        selected.append(series)
    return selected


def _v5_rows(assigned: Iterable[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Resolve only material, slot-assigned lines for V5."""
    output: list[dict[str, Any]] = []
    row_list = list(rows)
    for series in assigned:
        if series.get("material_line") is False:
            continue
        if series.get("values") is not None:
            output.append(dict(series))
            continue
        embedded = series.get("row")
        if embedded is not None:
            output.append(_model_dump(embedded))
            continue
        std_ids = series.get("std_ids") or ([series["std_id"]] if series.get("std_id") else [])
        output.extend(row for row in row_list if row.get("std_id") in std_ids)
    return output


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


def _one_offs(lagebericht: Any | None, segments: Any | None) -> list[dict[str, Any]]:
    """Return only explicitly stated one-offs from LageberichtExtraction evidence."""
    source = lagebericht if lagebericht is not None else segments
    if source is None:
        return []
    data = _model_dump(source)
    if "one_offs" not in data and data.get("lagebericht") is not None:
        data = _model_dump(data["lagebericht"])
    return [_model_dump(item) for item in data.get("one_offs", ())]


def _provenance_key(value: Any) -> tuple[str, str, int] | None:
    if value is None:
        return None
    provenance = _model_dump(value)
    doc, sheet, row = provenance.get("doc"), provenance.get("sheet"), provenance.get("row")
    if not isinstance(doc, str) or not doc.strip() or not isinstance(sheet, str) or not sheet.strip() or not isinstance(row, int):
        return None
    return (doc, sheet, row)


def _material_one_offs(
    lagebericht: Any | None,
    segments: Any | None,
    revenue_by_fy: Mapping[int, float] | None,
    revenue_pct: float,
    eur_floor: float,
) -> list[dict[str, Any]]:
    return [
        one_off for one_off in _one_offs(lagebericht, segments)
        if one_off.get("unit") == "EUR"
        and one_off.get("value") is not None
        and abs(float(one_off["value"])) >= max(
            eur_floor,
            abs(float((revenue_by_fy or {}).get(int(one_off["fiscal_year"]), 0))) * revenue_pct,
        )
        and _provenance_key(one_off.get("provenance")) is not None
    ]


def _stated_one_offs(lagebericht: Any | None, segments: Any | None) -> list[dict[str, Any]]:
    return [
        one_off for one_off in _one_offs(lagebericht, segments)
        if one_off.get("unit") == "EUR"
        and one_off.get("value") is not None
        and _provenance_key(one_off.get("provenance")) is not None
    ]


def _reported_one_off_footnote(one_off: Mapping[str, Any]) -> str:
    value = abs(float(one_off["value"])) / 1_000_000
    direction = str(one_off.get("direction") or "unknown")
    return f"FY{int(one_off['fiscal_year'])} reported EBITDA includes a €{value:.1f}m stated one-off ({direction}): {one_off['description']}"


def _series_fiscal_years(series: Mapping[str, Any]) -> set[int] | None:
    values = series.get("values")
    if isinstance(values, Mapping):
        return {int(year) for year in values}
    points = series.get("series")
    if isinstance(points, Iterable) and not isinstance(points, (str, bytes, Mapping)):
        years = {int(_model_dump(point)["fy"]) for point in points if _model_dump(point).get("fy") is not None}
        return years or None
    return None


def validate_v11(
    charted_series: Iterable[Any] | None,
    slot_assignments: Mapping[str, Any] | Iterable[Any] | None,
    *,
    axis_labels: Mapping[str, str] | None = None,
    lagebericht: Any | None = None,
    segments: Any | None = None,
    revenue_by_fy: Mapping[int, float] | None = None,
    one_off_materiality_revenue_pct: float = V11_ONE_OFF_MATERIALITY_REVENUE_PCT,
    one_off_materiality_eur_floor: float = V11_ONE_OFF_MATERIALITY_EUR_FLOOR,
) -> list[Flag]:
    """Enforce auditable EBITDA basis and disclosure of material stated one-offs."""
    flags: list[Flag] = []
    material_one_offs = _material_one_offs(
        lagebericht, segments, revenue_by_fy,
        one_off_materiality_revenue_pct, one_off_materiality_eur_floor,
    )
    for series in _assigned_series(charted_series, slot_assignments, axis_labels):
        name = _series_name(series)
        if not (_is_ebitda_label(series.get("axis_label")) or _is_ebitda_label(name)):
            continue
        basis = series.get("earnings_basis")
        if basis not in {"reported", "adjusted"}:
            flags.append(_flag("V11", f"{name} in {series['slot']} is labelled EBITDA but has no valid earnings_basis."))
            continue
        if basis == "adjusted":
            adjustments = series.get("adjustments")
            if not isinstance(adjustments, list) or not adjustments:
                flags.append(_flag("V11", f"{name} in {series['slot']} is adjusted EBITDA without stated Lagebericht adjustments."))
                continue
            stated = {(_provenance_key(one_off.get("provenance")), abs(float(one_off["value"]))) for one_off in _stated_one_offs(lagebericht, segments)}
            for adjustment in adjustments:
                adjustment_data = _model_dump(adjustment)
                amount = adjustment_data.get("amount")
                key = _provenance_key(adjustment_data.get("provenance"))
                if not isinstance(amount, (int, float)) or key is None or (key, abs(float(amount))) not in stated:
                    flags.append(_flag("V11", f"{name} in {series['slot']} has an adjustment not traced to a stated Lagebericht OneOffAmount."))
                    break
        else:
            footnotes = {str(note) for note in (*series.get("footnotes_auto", ()), *series.get("footnotes", ())) }
            series_years = _series_fiscal_years(series)
            for one_off in material_one_offs:
                if series_years is not None and int(one_off["fiscal_year"]) not in series_years:
                    continue
                required_note = _reported_one_off_footnote(one_off)
                if required_note not in footnotes:
                    flags.append(_flag("V11", f"{name} in {series['slot']} is reported EBITDA and omits a material stated one-off footnote.", required_note))
    return flags


def _v12_fiscal_years(series: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> set[int]:
    years = _series_fiscal_years(series)
    if years is not None:
        return years
    return {year for row in rows for year in _years(row.get("values", {}))}


def _v12_document(row: Mapping[str, Any], year: int) -> str:
    provenance = row.get("provenance_by_fy")
    if isinstance(provenance, Mapping):
        source = provenance.get(year) or provenance.get(str(year))
    else:
        source = row.get("provenance")
    if source is not None:
        document = _model_dump(source).get("doc")
        if isinstance(document, str) and document:
            return document
    return f"FY{year} filing"


def validate_v12(
    normalised: Mapping[str, Any],
    charted_series: Iterable[Any] | None,
    slot_assignments: Mapping[str, Any] | Iterable[Any] | None,
    *,
    axis_labels: Mapping[str, str] | None = None,
) -> list[Flag]:
    """Fail closed when an EBITDA series lacks a PL_GKV-7 child.

    Canonical output cannot tell a missing child apart from an unmapped child.
    Therefore a missing ``PL_GKV-7a`` or ``PL_GKV-7b`` is blocking until the
    analyst records the required confirmation note on the EBITDA series.
    """
    rows = [_model_dump(row) for row in normalised.get("rows", ())]
    by_id = {str(row.get("std_id")): row for row in rows if row.get("std_id")}
    flags: list[Flag] = []
    for series in _assigned_series(charted_series, slot_assignments, axis_labels):
        name = _series_name(series)
        if not (_is_ebitda_label(series.get("axis_label")) or _is_ebitda_label(name)):
            continue
        footnotes = {str(note) for note in (*series.get("footnotes_auto", ()), *series.get("footnotes", ())) }
        for year in sorted(_v12_fiscal_years(series, rows)):
            filing_document = next(
                (_v12_document(row, year) for row in rows if year in _years(row.get("values", {}))),
                f"FY{year} filing",
            )
            for child in ("PL_GKV-7a", "PL_GKV-7b"):
                row = by_id.get(child)
                if row is not None and year in _years(row.get("values", {})):
                    continue
                document = _v12_document(row, year) if row is not None else filing_document
                required_note = f"Confirm {child} is absent from {document}, or map it."
                if required_note not in footnotes:
                    flags.append(_flag("V12", f"{name} in {series['slot']} cannot confirm {child} for FY{year}; EBITDA must not sum only disclosed PL_GKV-7 children.", required_note))
    return flags


def validate_normalised(
    normalised: Mapping[str, Any],
    segments: Any | None = None,
    *,
    charted_series: Iterable[Any] | None = None,
    slot_assignments: Mapping[str, Any] | Iterable[Any] | None = None,
    axis_labels: Mapping[str, str] | None = None,
    v5_absolute_materiality_eur: float = V5_ABSOLUTE_MATERIALITY_EUR,
    one_off_materiality_revenue_pct: float = V11_ONE_OFF_MATERIALITY_REVENUE_PCT,
    one_off_materiality_eur_floor: float = V11_ONE_OFF_MATERIALITY_EUR_FLOOR,
    lagebericht: Any | None = None,
) -> ValidationResult:
    """Validate P0 and segment evidence, returning every applicable Flag.

    V1, V2, V5 and V7 run only for explicit ``slot_assignments``.  Give each
    assigned series an ``id`` and pass ``{slot: series_id}``; use
    ``axis_labels={slot: "Revenue"}`` (or an assignment ``axis_label``) to
    identify its displayed axis label.  Unassigned disclosed series are legal.
    """
    rows = [_model_dump(row) for row in normalised.get("rows", ())]
    flags: list[Flag] = []
    assigned = _assigned_series(charted_series, slot_assignments, axis_labels)

    revenue_by_fy: dict[int, float] = {}
    for row in rows:
        if row.get("std_id") in {"PL_GKV-1", "PL_UKV-1"}:
            revenue_by_fy.update(_years(row.get("values", {})))

    flags.extend(validate_v11(
        charted_series, slot_assignments, axis_labels=axis_labels,
        lagebericht=lagebericht, segments=segments,
        revenue_by_fy=revenue_by_fy,
        one_off_materiality_revenue_pct=one_off_materiality_revenue_pct,
        one_off_materiality_eur_floor=one_off_materiality_eur_floor,
    ))
    flags.extend(validate_v12(normalised, charted_series, slot_assignments, axis_labels=axis_labels))

    # V1, V2 and V7: only an assigned slide series has a presentation label.
    for series in assigned:
        name = _series_name(series)
        basis = series.get("presentation_basis")
        axis_label = series.get("axis_label")
        if _is_revenue_label(axis_label) and basis != "umsatzerloese":
            flags.append(_flag("V1", f"{name} in {series['slot']} is labelled {axis_label!r} but presentation_basis is {basis!r}, not 'umsatzerloese'."))
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

    # V3/V4 apply to all disclosed P0 lines.  V5 applies only to slot-assigned
    # material lines, and demands both percentage and absolute materiality.
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
    for row in _v5_rows(assigned, rows):
        name = _series_name(row)
        values = _years(row.get("values", {}))
        for previous, current in zip(sorted(values), sorted(values)[1:]):
            if current != previous + 1 or values[previous] == 0:
                continue
            delta = values[current] - values[previous]
            change = delta / abs(values[previous])
            if abs(change) > 0.15 and abs(delta) >= v5_absolute_materiality_eur:
                flags.append(_flag("V5", f"{name}: FY{current} changed {change:+.1%} versus FY{previous} ({delta:+,.2f} EUR).", "Explain the material year-on-year movement."))

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


def validate(
    normalised: Mapping[str, Any],
    segments: Any | None = None,
    *,
    charted_series: Iterable[Any] | None = None,
    slot_assignments: Mapping[str, Any] | Iterable[Any] | None = None,
    axis_labels: Mapping[str, str] | None = None,
    v5_absolute_materiality_eur: float = V5_ABSOLUTE_MATERIALITY_EUR,
    one_off_materiality_revenue_pct: float = V11_ONE_OFF_MATERIALITY_REVENUE_PCT,
    one_off_materiality_eur_floor: float = V11_ONE_OFF_MATERIALITY_EUR_FLOOR,
    lagebericht: Any | None = None,
) -> list[Flag]:
    """Convenience API returning the contract Flag objects directly."""
    return validate_normalised(
        normalised, segments, charted_series=charted_series,
        slot_assignments=slot_assignments, axis_labels=axis_labels,
    v5_absolute_materiality_eur=v5_absolute_materiality_eur,
        one_off_materiality_revenue_pct=one_off_materiality_revenue_pct,
        one_off_materiality_eur_floor=one_off_materiality_eur_floor, lagebericht=lagebericht,
    ).flags


# The registry is intentionally tested against contract/rules.json.  Existing
# rules share the normalised-record handler; V11 also exposes its narrow
# handlers so render preflight can apply the same server-side rule.
RULE_HANDLERS: dict[str, Callable[..., Any]] = {
    "V1": validate_normalised, "V2": validate_normalised, "V7": validate_normalised,
    "V8": validate_normalised, "V11": validate_v11, "V12": validate_v12,
}
