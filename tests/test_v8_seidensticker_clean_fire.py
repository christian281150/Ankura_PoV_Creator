"""Regression test: V8 (Aktiva == Passiva) fires clean end-to-end on the real
Seidensticker FY2024 fixture.

This is the completion of the V8 grand-total work started in
wire-p1-and-verify: the whole-table accumulator mechanism (consolidate.py)
was proven correct with synthetic data there, but real Seidensticker data
still failed to resolve BS-A/BS-P at the time, due to five separate gaps:
one taxonomy synonym (intangible assets, fixed already), the
Genussrechtskapital equity/debt collision (fixed via section-aware
routing), and four more label gaps fixed here (two synonyms, two new
taxonomy entries). This test is the honest proof none of those gaps remain
on this fixture -- not an assumption from fixing each one individually.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from extractor.consolidate import build_multi_year_tables
from validate.validator import validate_normalised

FY2024_FIXTURE = Path(__file__).parent / "fixtures" / "seidensticker_extracted_tables.json"


def _all_rows() -> list[dict[str, Any]]:
    tables = build_multi_year_tables(json.loads(FY2024_FIXTURE.read_text(encoding="utf-8-sig")))
    rows: list[dict[str, Any]] = []
    for table in tables:
        if not table.get("multi_year"):
            continue
        for meta, row in zip(table["row_metadata"], table["rows"][1:]):
            if meta.get("std_id") is None:
                continue
            values = {year: row[i + 1] for i, year in enumerate(table["years"]) if row[i + 1] != ""}
            rows.append({"std_id": meta["std_id"], "values": values})
    return rows


def test_bs_a_and_bs_p_both_resolve_and_tie_out_on_the_real_fixture() -> None:
    rows = _all_rows()
    by_id = {row["std_id"]: row for row in rows}

    assert "BS-A" in by_id, "the Aktiva grand total must resolve on this fixture"
    assert "BS-P" in by_id, "the Passiva grand total must resolve on this fixture"
    assert by_id["BS-A"]["values"] == {2024: 65313762.68, 2023: 76143694.64}
    assert by_id["BS-P"]["values"] == {2024: 65313762.68, 2023: 76143694.64}


def test_v8_fires_clean_on_the_real_seidensticker_fixture() -> None:
    result = validate_normalised({"rows": _all_rows()})

    v8_flags = [flag for flag in result.flags if flag.rule == "V8"]
    assert not v8_flags, f"V8 should not fire when Aktiva ties to Passiva; got {v8_flags}"

    # V6 and V9 are real, independent findings on this fixture (cost-ratio
    # breaks and the KG's negative equity) -- confirm they're unaffected by
    # this fix, not accidentally suppressed alongside V8.
    assert any(flag.rule == "V6" for flag in result.flags)
    assert any(flag.rule == "V9" for flag in result.flags)
