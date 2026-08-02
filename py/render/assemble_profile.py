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
    return {"entity": entity, "blocks": blocks, "canonical_layout": {
        "top_left": blocks[0]["id"], "top_right": revenue_block["id"],
        "bottom_left": blocks[2]["id"], "bottom_right": blocks[3]["id"],
    }, "coverage": []}


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
    figures = (segments or {}).get("figures", [])
    if not any(item.get("segment_type") == "geography" for item in figures):
        return _gap("geo.revenue_split_gap", "Revenue Split by Geography", "bottom_right", "Geographic revenue split not supplied; no proxy chart is rendered.")
    return _gap("geo.revenue_split_unimplemented", "Revenue Split by Geography", "bottom_right", "Geographic evidence is present but the chart payload is not yet modelled.")


def _coverage(values: Mapping[int, float]) -> float:
    years = sorted(values)
    return 0.0 if not years else len(years) / (years[-1] - years[0] + 1)


def _confidence(values: Mapping[int, float]) -> str:
    return "high" if _coverage(values) >= 0.9 else "medium" if _coverage(values) >= 0.6 else "low"


def _unique_provenance(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({(item["doc"], item["sheet"], item["row"], item["page"]): item for item in items}.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("normalised", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--segments", type=Path)
    parser.add_argument("--flags", type=Path)
    args = parser.parse_args()
    normalised = json.loads(args.normalised.read_text(encoding="utf-8"))
    segments = json.loads(args.segments.read_text(encoding="utf-8")) if args.segments else None
    flags = json.loads(args.flags.read_text(encoding="utf-8")) if args.flags else None
    args.output.write_text(json.dumps(assemble_profile(normalised, segments, flags), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
