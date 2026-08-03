"""Regression test for Lane G2: the FY2024 Kapitalflussrechnung resolves.

Before this lane, no "CF" statement type existed in the taxonomy at all
(only PL_GKV/PL_UKV/BS/STAT) -- every one of the KFR's ~30 rows queued as
unmapped. This locks in that the statement now resolves, and that its own
subtotal chain (operating + investing + financing -> net change; net change
+ opening balance +/- FX -> closing balance) ties out to the cent -- the
same discipline V10 applies to the P&L, checked directly here since no CF
validator rule exists yet.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from extractor.consolidate import build_multi_year_tables

FIXTURE = Path(__file__).parent / "fixtures" / "seidensticker_extracted_tables.json"
KFR_TABLE_TYPE = 2
FY = 2024

EXPECTED_STD_IDS = (
    "CF-1", "CF-2", "CF-3", "CF-4", "CF-5", "CF-6", "CF-7", "CF-8", "CF-9", "CF-10",
    "CF-OPERATING",
    "CF-11", "CF-12", "CF-13", "CF-14", "CF-15", "CF-16", "CF-17",
    "CF-INVESTING",
    "CF-18", "CF-19", "CF-20",
    "CF-FINANCING",
    "CF-NETCHANGE", "CF-FX", "CF-BEGIN", "CF-END", "CF-END.1", "CF-END.2",
)


def _extracted_tables() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8-sig"))


def _consolidated_kfr() -> dict[str, Any]:
    result = build_multi_year_tables(_extracted_tables())
    kfr = [t for t in result if t.get("type") == KFR_TABLE_TYPE and t.get("multi_year")]
    assert len(kfr) == 1, f"expected exactly one multi-year KFR table, got {len(kfr)}"
    return kfr[0]


def _series(fiscal_year: int = FY) -> dict[str, float]:
    table = _consolidated_kfr()
    years = table["years"]
    assert fiscal_year in years, f"FY{fiscal_year} absent; table covers {years}"
    column = years.index(fiscal_year) + 1
    return {
        meta["std_id"]: row[column]
        for meta, row in zip(table["row_metadata"], table["rows"][1:])
        if meta.get("std_id") is not None
    }


def test_every_expected_cf_position_resolves() -> None:
    series = _series()
    missing = [std_id for std_id in EXPECTED_STD_IDS if std_id not in series]
    assert not missing, f"unmapped CF positions: {missing}"


def test_operating_investing_financing_sum_to_net_change() -> None:
    series = _series()
    total = series["CF-OPERATING"] + series["CF-INVESTING"] + series["CF-FINANCING"]
    assert total == pytest.approx(series["CF-NETCHANGE"], abs=0.5)


def test_opening_balance_plus_net_change_and_fx_ties_to_closing_balance() -> None:
    series = _series()
    closing = series["CF-BEGIN"] + series["CF-NETCHANGE"] + series["CF-FX"]
    assert closing == pytest.approx(series["CF-END"], abs=0.5)


def test_closing_balance_decomposes_into_the_davon_memo_lines() -> None:
    series = _series()
    assert series["CF-END.1"] + series["CF-END.2"] == pytest.approx(series["CF-END"], abs=0.5)


def test_closing_balance_matches_the_lagebericht_external_witness() -> None:
    """The FY2024 filing's own closing cash figure, -16.642.120 (whole EUR,
    this statement's own presentation), corroborated independently by the
    fixture's raw extracted rows (tests/fixtures/seidensticker_extracted_tables.json,
    table index 3, row 29)."""
    series = _series()
    assert series["CF-END"] == pytest.approx(-16_642_120.0, abs=1.0)
