"""Regression tests for Seidensticker FY2024 GuV consolidation.

Locks in what `tests/fixtures/seidensticker_extracted_tables.json` must
produce. That fixture is the raw output of `extract_tables_from_pdf` over
`Textilkontor_HRA8217_Konzernabschluss_FY2024.pdf`, committed so that
consolidation can be exercised without a PDF, a browser, or the GUI.

`test_no_value_bearing_row_is_silently_discarded` locks in the
unlabelled-subtotal fix in `_column_actuals`: blank-label rows are recognised
as subtotals only by exact arithmetic verification against already-resolved
component lines, never by position or guesswork.

The EBIT assertion is the only figure in this file with an external
witness: the FY2024 Lagebericht states an operating result of T-993, and
`tests/test_lagebericht.py` asserts -993_000 from a different code path.
Every other number here is self-reported by the pipeline.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from extractor.consolidate import build_multi_year_tables

FIXTURE = Path(__file__).parent / "fixtures" / "seidensticker_extracted_tables.json"

FY = 2024
GUV_TABLE_TYPE = 1
GUV_SOURCE_INDEX = 2  # KONZERN-GEWINN- UND VERLUSTRECHNUNG, after _pin_key_tables

# Operating positions of the GKV P&L in HGB s275(2) order. Summing these
# gives EBIT; PL_GKV-3 (aktivierte Eigenleistungen) is absent from this
# filing, and PL_GKV-7b (write-downs on current assets) is not reported.
OPERATING_STD_IDS = (
    "PL_GKV-1",   # Umsatzerloese
    "PL_GKV-2",   # Bestandsveraenderung
    "PL_GKV-4",   # sonstige betriebliche Ertraege
    "PL_GKV-5a",  # Roh-, Hilfs- und Betriebsstoffe
    "PL_GKV-5b",  # bezogene Leistungen
    "PL_GKV-6a",  # Loehne und Gehaelter
    "PL_GKV-6b",  # soziale Abgaben
    "PL_GKV-7a",  # Abschreibungen immat. / Sachanlagen
    "PL_GKV-8",   # sonstige betriebliche Aufwendungen
)


def _extracted_tables() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8-sig"))


def _consolidated_guv() -> dict[str, Any]:
    """Run a live consolidation and return the multi-year GuV table."""
    result = build_multi_year_tables(_extracted_tables())
    guv = [t for t in result if t.get("type") == GUV_TABLE_TYPE and t.get("multi_year")]
    assert len(guv) == 1, f"expected exactly one multi-year GuV table, got {len(guv)}"
    return guv[0]


def _series(fiscal_year: int = FY) -> dict[str, float]:
    """std_id -> value for one fiscal year."""
    table = _consolidated_guv()
    years = table["years"]
    assert fiscal_year in years, f"FY{fiscal_year} absent; table covers {years}"
    column = years.index(fiscal_year) + 1  # column 0 is the label
    return {
        meta["std_id"]: row[column]
        for meta, row in zip(table["row_metadata"], table["rows"][1:])
        if meta.get("std_id") is not None
    }


def test_revenue_is_umsatzerloese_not_gesamtleistung() -> None:
    """The published deck charted Gesamtleistung labelled as Revenue.

    Umsatzerloese is 103.2m; Gesamtleistung for the same year is 102.1m.
    They are close enough here to pass a smell test and different enough
    to change the growth headline, which is why this is pinned exactly.
    """
    assert _series()["PL_GKV-1"] == pytest.approx(103_152_036.57, abs=0.01)


def test_depreciation_resolves_to_the_7a_child_not_the_7_parent() -> None:
    """The filing reports s275(2) Nr. 7a only; there is no 7b in this year.

    PL_GKV-7 is deliberately absent from the taxonomy so that an aggregate
    heading can never resolve to one of its own children. Anything deriving
    EBITDA must therefore sum the 7-family rather than read a parent.
    """
    series = _series()
    assert series["PL_GKV-7a"] == pytest.approx(-1_217_094.39, abs=0.01)
    assert "PL_GKV-7" not in series
    assert "PL_GKV-7b" not in series


def test_ebit_reconciles_to_the_lagebericht() -> None:
    """Derived EBIT must match a figure this pipeline did not produce."""
    series = _series()
    missing = [std_id for std_id in OPERATING_STD_IDS if std_id not in series]
    assert not missing, f"unmapped operating positions: {missing}"

    ebit = sum(series[std_id] for std_id in OPERATING_STD_IDS)
    assert ebit == pytest.approx(-993_758.07, abs=0.01)

    # External witness: FY2024 Lagebericht, Ertragslage, stated in TEUR.
    assert round(ebit / 1_000) == -994 or round(ebit / 1_000) == -993

    ebitda = ebit - series["PL_GKV-7a"]
    assert ebitda == pytest.approx(223_336.32, abs=0.01)


def test_v10_subtotal_tie_out_fires_clean_on_the_recognised_subtotals() -> None:
    """V10 (validator.py:392) has real subtotal rows to check for the first time.

    Each blank-label row `_column_actuals` recognises (Gesamtleistung, the
    Materialaufwand and Personalaufwand totals, the operating-expense block)
    carries its own disclosed component std_ids, so V10 must reconcile every
    one of them to zero delta -- not just fail to find anything to check.
    """
    from validate.validator import validate_normalised

    table = _consolidated_guv()
    years = table["years"]
    rows = [
        {**meta, "values": {year: row[i + 1] for i, year in enumerate(years) if row[i + 1] != ""}}
        for meta, row in zip(table["row_metadata"], table["rows"][1:])
    ]
    subtotal_rows = [row for row in rows if row.get("row_type") == "subtotal"]
    assert len(subtotal_rows) >= 4, "expected Gesamtleistung, both cost totals, and the expense block"

    result = validate_normalised({"rows": rows})
    v10_flags = [flag for flag in result.flags if flag.rule == "V10"]
    assert not v10_flags, [flag.message for flag in v10_flags]


def test_no_value_bearing_row_is_silently_discarded() -> None:
    """Every input row carrying a value must be mapped or queued, never dropped.

    Blank-label subtotal rows (Gesamtleistung, the Materialaufwand and
    Personalaufwand totals, the operating-expense block) are recognised in
    ``_column_actuals`` by verifying their disclosed value against an exact
    window of already-resolved component lines -- never guessed. One blank
    row, Finanzergebnis (row 22), cannot be verified this way: one of its
    three components -- "Gewinne aus Beteiligungen an assoziierten
    Unternehmen" -- resolves to no taxonomy entry at all (the open
    "Associates" gap in final-push-lanes.md). It is correctly left queued
    rather than forced, which this test accepts as "not dropped".
    """
    from extractor.consolidate import _year_blocks

    source = next(t for t in _extracted_tables() if t.get("index") == GUV_SOURCE_INDEX)
    header_row, _blocks = _year_blocks(source["rows"])

    def carries_a_value(row: list[Any]) -> bool:
        return any(str(cell or "").strip().rstrip(".,") not in ("", "PDF Page")
                   and any(ch.isdigit() for ch in str(cell))
                   for cell in row[1:4])

    unlabelled_with_values = [
        index for index, row in enumerate(source["rows"])
        if index > header_row and not str(row[0] or "").strip() and carries_a_value(row)
    ]

    with TemporaryDirectory() as tmp_dir:
        queue_path = Path(tmp_dir) / "unmapped_queue.csv"
        result = build_multi_year_tables(_extracted_tables(), queue_path=queue_path)
        guv = next(t for t in result if t.get("type") == GUV_TABLE_TYPE and t.get("multi_year"))
        accounted_for = {meta.get("provenance", {}).get("row") for meta in guv["row_metadata"]}
        with queue_path.open(encoding="utf-8") as handle:
            # Row numbers are only unique within one table -- another table's
            # row happening to share a number is not evidence this table's
            # row was queued, so scope to entries from the GuV table itself.
            accounted_for |= {
                int(row["row"]) for row in csv.DictReader(handle)
                if row["row"] and row["heading"] == source["heading"]
            }

    lost = [index for index in unlabelled_with_values if index not in accounted_for]
    assert not lost, f"input rows dropped without a queue entry: {lost}"
