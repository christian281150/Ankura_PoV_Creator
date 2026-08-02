"""Consume the extractor's canonical, auditable financial export.

The extractor owns table parsing, number and unit normalisation, exact mapping,
framework/method guards, alias loading, collision handling, and page capture.
This module deliberately does none of those things.  It validates the canonical
contract, reshapes GuV rows for downstream consumers, and produces the
Seidensticker reconciliation used as a regression check.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


GUV_TABLE_TYPE = 1
REQUIRED_VALUE_FIELDS = frozenset({"std_id", "unit", "presentation_basis", "provenance"})
REQUIRED_PROVENANCE_FIELDS = frozenset({"doc", "sheet", "row", "page"})

# Keep these as EUR amounts: presentation scaling belongs in render.
GOLDEN_VALUES: dict[tuple[int, str], float] = {
    (2025, "umsatzerloese"): 111_815_106.14,
    (2024, "bestandsveraenderung"): -8_833_400.55,
    (2024, "gesamtleistung"): 102_078_650.90,
}


class CanonicalExportError(ValueError):
    """Raised when an extractor-owned canonical export is incomplete or unsafe."""


def _canonical_tables(payload: Any) -> list[dict[str, Any]]:
    tables = payload.get("tables") if isinstance(payload, dict) else payload
    if not isinstance(tables, list):
        raise CanonicalExportError("canonical export must be a table list or {'tables': [...]}")
    if not all(isinstance(table, dict) for table in tables):
        raise CanonicalExportError("canonical export contains a non-object table")
    return tables


def _guv_tables(tables: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    guv = [table for table in tables if table.get("type") == GUV_TABLE_TYPE and table.get("multi_year")]
    if not guv:
        raise CanonicalExportError("canonical export contains no multi-year GuV table")
    return guv


def _required_provenance(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not REQUIRED_PROVENANCE_FIELDS <= value.keys():
        raise CanonicalExportError(f"{context} has incomplete provenance")
    if any(value[field] is None or value[field] == "" for field in REQUIRED_PROVENANCE_FIELDS):
        raise CanonicalExportError(f"{context} has incomplete provenance")
    return value


def _canonical_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    if table.get("framework") not in {"hgb", "ifrs"}:
        raise CanonicalExportError("canonical GuV table has no supported framework guard")
    if table.get("pnl_method") not in {"gkv", "ukv"}:
        raise CanonicalExportError("canonical GuV table has no supported P&L-method guard")
    metadata = table.get("row_metadata")
    if not isinstance(metadata, list):
        raise CanonicalExportError("canonical GuV table has no row_metadata")
    table_rows = table.get("rows")
    if table_rows is not None and (not isinstance(table_rows, list) or len(table_rows) != len(metadata) + 1):
        raise CanonicalExportError("canonical GuV table rows do not align with row_metadata")
    years = table_rows[0][1:] if table_rows else None
    if years is not None and not all(str(year).isdigit() for year in years):
        raise CanonicalExportError("canonical GuV table has invalid fiscal-year headers")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(metadata, start=1):
        if not isinstance(item, dict) or not (REQUIRED_VALUE_FIELDS - {"provenance"}) <= item.keys():
            raise CanonicalExportError(f"canonical GuV row {index} is missing required fields")
        if item["std_id"] is None or item["unit"] != "EUR":
            raise CanonicalExportError(f"canonical GuV row {index} is not a mapped EUR actual")
        row = dict(item)
        row["framework"] = table["framework"]
        row["method_flag"] = table["pnl_method"].upper()
        if table_rows:
            source_row = table_rows[index]
            if not isinstance(source_row, list) or len(source_row) != len(years) + 1:
                raise CanonicalExportError(f"canonical GuV row {index} has invalid cells")
            row["raw_label"] = source_row[0]
            row["values"] = {
                str(year): value for year, value in zip(years, source_row[1:]) if value != ""
            }
        values = row.get("values")
        if not isinstance(values, dict):
            raise CanonicalExportError(f"canonical GuV row {index} has invalid values")
        provenance = row.get("provenance")
        per_year = row.get("provenance_by_fy", provenance)
        if not isinstance(per_year, dict):
            raise CanonicalExportError(f"canonical GuV row {index} has invalid per-year provenance")
        for year, value in values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise CanonicalExportError(f"canonical GuV row {index}, FY{year} is not numeric EUR")
            source = per_year.get(str(year), per_year.get(year, provenance))
            _required_provenance(source, f"canonical GuV row {index}, FY{year}")
        _required_provenance(provenance, f"canonical GuV row {index}")
        rows.append(row)
    return rows


def _series(rows: Iterable[dict[str, Any]], std_id: str) -> dict[int, float]:
    matches = [row for row in rows if row["std_id"] == std_id and row.get("row_type") != "subtotal"]
    if len(matches) > 1:
        raise CanonicalExportError(f"canonical export contains duplicate {std_id} rows")
    if not matches:
        return {}
    return {int(year): float(value) for year, value in matches[0]["values"].items()}


def reconciliation(rows: Iterable[dict[str, Any]]) -> list[dict[str, float | int | None]]:
    """Reconcile Gesamtleistung from canonical GKV components only."""
    revenue = _series(rows, "PL_GKV-1")
    inventory = _series(rows, "PL_GKV-2")
    other_income = _series(rows, "PL_GKV-4")
    result: list[dict[str, float | int | None]] = []
    for year in sorted(set(revenue) | set(inventory) | set(other_income)):
        components = (revenue.get(year), inventory.get(year), other_income.get(year))
        result.append({
            "fy": year,
            "umsatzerloese": components[0],
            "bestandsveraenderung": components[1],
            "sonstige_betriebliche_ertraege": components[2],
            "gesamtleistung": float(sum(Decimal(str(value)) for value in components))
            if all(value is not None for value in components) else None,
        })
    return result


def verify_golden_table(rows: Iterable[dict[str, Any]]) -> list[dict[str, float | int | None]]:
    """Fail closed if the extractor regresses the Seidensticker golden values."""
    result = reconciliation(rows)
    by_year = {entry["fy"]: entry for entry in result}
    for (year, field), expected in GOLDEN_VALUES.items():
        actual = by_year.get(year, {}).get(field)
        if actual != expected:
            raise CanonicalExportError(
                f"golden reconciliation mismatch for FY{year} {field}: "
                f"expected {expected!r}, got {actual!r}; investigate the extractor export"
            )
    return result


def consume_canonical_export(input_path: str | Path) -> dict[str, Any]:
    """Validate and consume an extractor-produced canonical JSON export."""
    payload = json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    tables = _guv_tables(_canonical_tables(payload))
    if len(tables) != 1:
        raise CanonicalExportError("canonical export contains more than one multi-year GuV table")
    rows = _canonical_rows(tables[0])
    reconciled = verify_golden_table(rows)
    return {
        "coverage": {
            "input_line_count": len(rows),
            "output_line_count": len(rows),
            "source": "canonical_export",
            "framework": tables[0]["framework"],
            "method_flag": tables[0]["pnl_method"].upper(),
        },
        "reconciliation": reconciled,
        "rows": rows,
    }


def main(input_path: str, out_path: str) -> None:
    result = consume_canonical_export(input_path)
    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    coverage = result["coverage"]
    print(f"line count: {coverage['input_line_count']} -> {coverage['output_line_count']}")
    print("golden reconciliation: passed")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: p0_normalise.py CANONICAL_EXPORT.json OUTPUT.json")
    main(*sys.argv[1:])
