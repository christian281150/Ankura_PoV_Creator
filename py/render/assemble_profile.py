"""Assemble a render-contract profile from normalised evidence.

This adapter never calculates financial values or validation flags.  It only
selects already-normalised rows, preserves their metadata/provenance, and
creates explicit gap blocks when the normalise output contains no evidence for
one of the canonical four slots.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from coverage.probe import compute_coverage_dimensions
from validate.validator import validate_normalised


class AssemblyError(ValueError):
    """The upstream evidence cannot support a contract profile."""


def assemble_profile(
    normalised: Mapping[str, Any],
    segments: Mapping[str, Any] | None = None,
    validation_flags: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create contract blocks from supplied evidence, without silent defaults."""
    entity = dict(normalised.get("entity") or {})
    if not entity.get("legal_name") or not entity.get("fiscal_year_end"):
        raise AssemblyError("Normalise output must provide entity legal_name and fiscal_year_end.")
    revenue = _merged_row(normalised.get("rows", []), "PL_GKV-1")
    if revenue is None:
        raise AssemblyError("No mapped Umsatzerlöse row (PL_GKV-1) is available.")
    _require_series_metadata(revenue)
    flags = [dict(flag) for flag in validation_flags or ()]
    revenue_block = {
        "id": "fin.revenue_series",
        "std_id": revenue["std_id"],
        "title": "Revenue in €m",
        "series_label": "Revenue",
        "kind": "chart.column_line",
        "eligible_slots": ["top_right"],
        "coverage": _coverage(revenue["values"]),
        "confidence": _confidence(revenue["values"]),
        "source": "filing",
        "framework": revenue["framework"],
        "pnl_method": revenue["pnl_method"],
        "presentation_basis": revenue["presentation_basis"],
        "unit": revenue["unit"],
        "flags": flags,
        "footnotes_auto": [flag["note"] for flag in flags if flag.get("note")],
        "provenance": revenue["provenance"],
        "series": [{"fy": year, "value": value} for year, value in sorted(revenue["values"].items())],
    }
    blocks = [
        _gap("bo.business_overview_gap", "Business Overview", "top_left", "Business-overview evidence was not supplied."),
        revenue_block,
        _gap("prod.product_grid_gap", "Selected Products and Services", "bottom_left", "Product evidence was not supplied."),
        _geography_block(segments),
    ]
    coverage = [dimension.model_dump() for dimension in compute_coverage_dimensions(blocks)]
    return {"entity": entity, "blocks": blocks, "canonical_layout": {
        "top_left": blocks[0]["id"], "top_right": revenue_block["id"],
        "bottom_left": blocks[2]["id"], "bottom_right": blocks[3]["id"],
    }, "coverage": coverage, "rows": list(normalised.get("rows", []))}


def _merged_row(rows: Iterable[Mapping[str, Any]], std_id: str) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("std_id") == std_id]
    if not matches:
        return None
    first = dict(matches[0])
    values: dict[int, float] = {}
    provenance: list[dict[str, Any]] = []
    for row in matches:
        _require_series_metadata(row)
        if any(row[key] != first[key] for key in ("unit", "presentation_basis", "framework", "pnl_method")):
            raise AssemblyError(f"{std_id} has inconsistent metadata across source rows.")
        for year, value in (row.get("values") or {}).items():
            if value is None:
                continue
            year_int, value_float = int(year), float(value)
            if year_int in values and values[year_int] != value_float:
                raise AssemblyError(f"{std_id} has conflicting values for FY{year_int}.")
            values[year_int] = value_float
        for year, item in (row.get("provenance_by_fy") or {}).items():
            provenance.append(_provenance(item, std_id))
        if not row.get("provenance_by_fy"):
            provenance.append(_provenance(row["provenance"], std_id))
    first["values"] = values
    first["provenance"] = _unique_provenance(provenance)
    return first


def _require_series_metadata(row: Mapping[str, Any]) -> None:
    missing = [key for key in ("unit", "presentation_basis", "framework", "pnl_method", "provenance") if row.get(key) is None]
    if missing:
        raise AssemblyError(f"{row.get('std_id')!r} lacks required upstream metadata: {', '.join(missing)}.")


def _provenance(item: Mapping[str, Any], std_id: str) -> dict[str, Any]:
    if not item.get("doc") or "page" not in item:
        raise AssemblyError(f"{std_id} provenance must include doc and page (page may be null).")
    return {"std_id": std_id, "doc": item["doc"], "sheet": item.get("sheet", ""), "row": item.get("row", 0), "page": item["page"]}


def _gap(block_id: str, title: str, slot: str, message: str) -> dict[str, Any]:
    return {"id": block_id, "title": title, "kind": "bullets", "eligible_slots": [slot], "coverage": 0.0, "confidence": "low", "source": "coverage", "framework": None, "pnl_method": None, "presentation_basis": "n/a", "unit": "n/a", "flags": [], "footnotes_auto": [], "provenance": [{"std_id": "COVERAGE-GAP", "doc": "Profile coverage", "sheet": title, "row": 0, "page": None}], "content": [message]}


def _geography_block(segments: Mapping[str, Any] | None) -> dict[str, Any]:
    """Real Anhang §285 Nr. 4 revenue-split content, from normalise.segments.

    The renderer's native chart only draws one flat fy->value series (see
    renderer._render_native_column_chart), so a multi-segment split cannot be
    a "chart.stacked_column" without either crashing or silently mis-drawing
    segments as fiscal years -- both worse than a plain bullet list. This
    renders as ``bullets`` for exactly that reason, using the most recent
    fiscal year the filing actually discloses a geographic split for.
    """
    figures = [item for item in (segments or {}).get("figures", []) if item.get("segment_type") == "geography"]
    if not figures:
        return _gap("geo.revenue_split_gap", "Revenue Split by Geography", "bottom_right", "Geographic revenue split not supplied; no proxy chart is rendered.")
    latest_year = max(int(item["fiscal_year"]) for item in figures)
    latest = [item for item in figures if int(item["fiscal_year"]) == latest_year]
    revenue_figures = [item for item in latest if item.get("metric") == "revenue"]
    if revenue_figures:
        latest = revenue_figures

    provenance: list[dict[str, Any]] = []
    content: list[str] = []
    for figure in sorted(latest, key=lambda item: str(item["segment_name"]).casefold()):
        figure_provenance = figure.get("provenance") or {}
        sheet = figure_provenance.get("sheet")
        row = figure_provenance.get("row")
        if not sheet or row is None:
            raise AssemblyError(f"Geography segment {figure.get('segment_name')!r} lacks sheet/row provenance.")
        # Classifier-tagged sheet titles are "FY2025_..."; the same doc-from-
        # sheet-prefix convention normalise.lagebericht already uses for
        # Anhang/Lagebericht evidence without a filing name of its own.
        doc = str(sheet).split("_", 1)[0]
        provenance.append(_provenance({"doc": doc, "sheet": sheet, "row": row, "page": None}, "SEGMENT-GEO"))
        basis = figure.get("presentation_basis")
        basis_note = f" ({basis})" if basis else " (basis not stated)"
        value = float(figure["value"])
        formatted = f"{value:.1f}%" if figure.get("unit") == "PCT" else f"€{value / 1_000_000:.1f}m"
        content.append(f"{figure['segment_name']}: {formatted}{basis_note} — FY{latest_year}")

    has_eur = any(item.get("unit") == "EUR" for item in latest)
    all_basis_stated = all(item.get("presentation_basis") for item in latest)
    return {
        "id": "geo.revenue_split",
        "title": "Revenue Split by Geography",
        "kind": "bullets",
        "eligible_slots": ["bottom_right"],
        "coverage": 1.0,
        "confidence": "high" if all_basis_stated else "medium",
        "source": "filing",
        "framework": None,
        "pnl_method": None,
        "presentation_basis": latest[0].get("presentation_basis") or "n/a",
        "unit": "EUR" if has_eur else "n/a",
        "flags": [],
        "footnotes_auto": [],
        "provenance": _unique_provenance(provenance),
        "content": content,
    }


def _coverage(values: Mapping[int, float]) -> float:
    years = sorted(values)
    return 0.0 if not years else len(years) / (years[-1] - years[0] + 1)


def _confidence(values: Mapping[int, float]) -> str:
    return "high" if _coverage(values) >= 0.9 else "medium" if _coverage(values) >= 0.6 else "low"


def _unique_provenance(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({(item["doc"], item["sheet"], item["row"], item["page"]): item for item in items}.values())


def auto_footnote_flags(normalised: Mapping[str, Any], segments: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """The V3-V6 flags real filing evidence needs surfaced as automatic slide
    footnotes, per AGENTS.md's stated design ("Notes written against V3-V6
    become slide footnotes automatically").

    This is the caller assemble_profile's own docstring expects: the adapter
    itself never computes validation flags, so whoever invokes it must. Only
    V3, V4 and V6 can actually fire from rows alone -- V5 also carries a note
    but needs an assigned chart series to evaluate, and no slot assignment
    exists yet at this stage (that happens later, in render_profile); V5 is
    covered separately by renderer.py's render-time preflight, which runs
    after slots are known.
    """
    result = validate_normalised({"rows": normalised.get("rows", [])}, segments)
    return [flag.model_dump() for flag in result.flags if flag.rule in {"V3", "V4", "V5", "V6"}]


def flagged_items(normalised: Mapping[str, Any], segments: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """V9-class advisory findings ("flag, never suppress" -- AGENTS.md's rule
    table), kept deliberately separate from ``auto_footnote_flags``.

    V3-V6 need an analyst-authored note before they can appear anywhere (see
    the V3-V6 ``note_required`` severity and the auto-footnote mechanism
    above); V9 has no note field and must stay visible regardless of whether
    one is ever written, and regardless of which blocks end up in which slot
    -- a KG negative-equity position does not stop being true because nobody
    assigned a chart to bottom_right. Callers must not fold this into
    ``auto_footnote_flags``'s output: a committed regression test
    (test_auto_footnote_flags_excludes_rules_outside_v3_to_v6) asserts V9
    never reaches the revenue block's footnotes via that path, precisely so
    the two surfacing mechanisms cannot be silently conflated.

    Each returned item carries real row-level provenance rather than being a
    bare message, so a renderer can write it to the audit trail the same way
    it does for any other figure.
    """
    rows = list(normalised.get("rows", []))
    result = validate_normalised({"rows": rows}, segments)
    v9_flags = [flag for flag in result.flags if flag.rule == "V9"]
    if not v9_flags:
        return []

    provenance: list[dict[str, Any]] = []
    for row in rows:
        std_id = row.get("std_id")
        if std_id not in {"BS-P-NEGEQ", "BS-P.A"}:
            continue
        by_fy = row.get("provenance_by_fy")
        if by_fy:
            for item in by_fy.values():
                provenance.append(_provenance(item, std_id))
        elif row.get("provenance"):
            provenance.append(_provenance(row["provenance"], std_id))
    if not provenance:
        raise AssemblyError("V9 fired but no BS-P-NEGEQ/BS-P.A row provenance is available to cite.")

    unique_provenance = _unique_provenance(provenance)
    return [
        {"rule": flag.rule, "severity": flag.severity, "message": flag.message, "provenance": unique_provenance}
        for flag in v9_flags
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("normalised", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--segments", type=Path)
    parser.add_argument("--flags", type=Path, help="Pre-computed flags JSON, overriding the automatic V3-V6 validation run")
    args = parser.parse_args()
    normalised = json.loads(args.normalised.read_text(encoding="utf-8"))
    segments = json.loads(args.segments.read_text(encoding="utf-8")) if args.segments else None
    flags = json.loads(args.flags.read_text(encoding="utf-8")) if args.flags else auto_footnote_flags(normalised, segments)
    args.output.write_text(json.dumps(assemble_profile(normalised, segments, flags), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
