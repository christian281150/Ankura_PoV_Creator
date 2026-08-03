"""Regression test for Lane G1: V9 (negative equity) on the FY2024 Konzernbilanz.

Textilkontor Walter Seidensticker GmbH & Co. KG's equity section uses six
KG-specific Roman-numeral positions the taxonomy previously had no entries
for (it modeled GmbH equity only). "Nicht durch Vermoegenseinlagen gedeckte
Verlustanteile der Kommanditisten" -- disclosed on both Aktiva and Passiva,
same value both years -- must resolve to std_id BS-P-NEGEQ so V9 fires,
without the cross-table collision guard discarding it (see the "confirmed
mirror" fix in consolidate.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from extractor.consolidate import build_multi_year_tables
from validate.validator import validate_normalised

FIXTURE = Path(__file__).parent / "fixtures" / "seidensticker_extracted_tables.json"
BILANZ_TABLE_TYPE = 0


def _extracted_tables() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8-sig"))


def _consolidated_bilanz() -> dict[str, Any]:
    result = build_multi_year_tables(_extracted_tables())
    bilanz = [t for t in result if t.get("type") == BILANZ_TABLE_TYPE and t.get("multi_year")]
    assert len(bilanz) == 1, f"expected exactly one multi-year Bilanz table, got {len(bilanz)}"
    return bilanz[0]


def test_kg_equity_positions_resolve() -> None:
    table = _consolidated_bilanz()
    std_ids = {meta.get("std_id") for meta in table["row_metadata"]}
    for expected in ("BS-P-NEGEQ", "BS-P.A.KG-I", "BS-P.A.KG-II.1", "BS-P.A.KG-II.2", "BS-P.A.KG-III"):
        assert expected in std_ids, f"{expected} did not resolve"


def test_v9_fires_on_the_negative_equity_disclosure() -> None:
    table = _consolidated_bilanz()
    years = table["years"]
    rows = [
        {**meta, "values": {year: row[i + 1] for i, year in enumerate(years) if row[i + 1] != ""}}
        for meta, row in zip(table["row_metadata"], table["rows"][1:])
    ]

    result = validate_normalised({"rows": rows})
    v9_flags = [flag for flag in result.flags if flag.rule == "V9"]
    assert len(v9_flags) == 1, [flag.message for flag in result.flags]
    assert "BS-P-NEGEQ" in v9_flags[0].message
