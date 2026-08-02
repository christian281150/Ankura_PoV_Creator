"""Regression checks for the canonical-export P0 consumer."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).parents[1] / "py" / "normalise" / "p0_normalise.py"
_SPEC = importlib.util.spec_from_file_location("p0_normalise", _MODULE_PATH)
assert _SPEC and _SPEC.loader
p0_normalise = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(p0_normalise)


def _canonical_export() -> list[dict[str, object]]:
    years = ["2025", "2024"]
    provenance = {
        year: {"doc": f"Konzernabschluss FY{year}", "sheet": "ALL — GuV", "row": row, "page": row}
        for year, row in zip(years, (7, 8))
    }
    components = [
        ("Umsatzerlöse", "PL_GKV-1", [111_815_106.14, 103_152_036.57]),
        ("Bestandsveränderung", "PL_GKV-2", [2_732_346.13, -8_833_400.55]),
        ("Sonstige betriebliche Erträge", "PL_GKV-4", [1_914_645.32, 7_760_014.88]),
    ]
    return [{
        "type": 1,
        "multi_year": True,
        "framework": "hgb",
        "pnl_method": "gkv",
        "rows": [["Description", *years], *[[label, *values] for label, _, values in components]],
        "row_metadata": [
            {
                "std_id": std_id,
                "row_type": "line",
                "unit": "EUR",
                "presentation_basis": "umsatzerloese" if std_id == "PL_GKV-1" else None,
                "provenance": provenance["2025"],
                "provenance_by_fy": provenance,
            }
            for _, std_id, _ in components
        ],
    }]


def test_consumes_canonical_export_and_preserves_golden_values(tmp_path: Path) -> None:
    source = tmp_path / "canonical.json"
    source.write_text(json.dumps(_canonical_export()), encoding="utf-8")

    result = p0_normalise.consume_canonical_export(source)

    assert result["coverage"]["input_line_count"] == result["coverage"]["output_line_count"] == 3
    assert result["reconciliation"][-1] == {
        "fy": 2025,
        "umsatzerloese": 111_815_106.14,
        "bestandsveraenderung": 2_732_346.13,
        "sonstige_betriebliche_ertraege": 1_914_645.32,
        "gesamtleistung": 116_462_097.59,
    }
    assert result["reconciliation"][0]["gesamtleistung"] == 102_078_650.90
    assert result["rows"][0]["provenance_by_fy"]["2025"]["page"] == 7


def test_refuses_canonical_export_without_page_provenance(tmp_path: Path) -> None:
    payload = _canonical_export()
    payload[0]["row_metadata"][0]["provenance_by_fy"]["2025"]["page"] = None
    source = tmp_path / "canonical.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(p0_normalise.CanonicalExportError, match="incomplete provenance"):
        p0_normalise.consume_canonical_export(source)
