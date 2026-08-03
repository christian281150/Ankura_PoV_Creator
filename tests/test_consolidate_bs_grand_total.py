"""Regression tests for the table-closing Bilanz grand-total recognition.

Synthetic, taxonomy-fixture-independent: uses BS-A.C, BS-A.D and BS-P-NEGEQ,
three real, already-resolvable single-line std_ids (the same two used by
test_consolidate_cross_table_merge.py, plus the KG negative-equity line),
so these tests don't depend on any in-progress taxonomy work.

The scenario mirrors a real Bilanz shape: an intermediate blank subtotal row
resets the tier1/tier2 accumulator partway through the table, so only a
separate, never-resetting whole-table accumulator can still recognise the
final "Summe Aktiva" row against everything disclosed above it -- proving
this is genuinely necessary, not just the existing mechanism under another
name.
"""
from __future__ import annotations

from typing import Any

from extractor.consolidate import build_multi_year_tables

LINE_C = "C. Rechnungsabgrenzungsposten"
LINE_D = "D. Aktive latente Steuern"
LINE_NEGEQ = "E. Nicht durch Vermögenseinlagen gedeckte Verlustanteile der Kommanditisten"


def _table(grand_total_fy2024: str, grand_total_fy2023: str) -> dict[str, Any]:
    return {
        "index": 1,
        "heading": "Synthetic Bilanz table",
        "type": 0,
        "_override_applied": True,
        "framework": "hgb",
        "pnl_method": "gkv",
        "doc_label": "",
        "page_start": 1,
        "rows": [
            ["", "2024", "", "2023", "PDF Page"],
            [LINE_C, "", "100,00", "90,00", 1],
            [LINE_D, "", "50,00", "40,00", 1],
            # Intermediate subtotal: ties to [C, D] only, resetting the
            # tier1/tier2 accumulator before the table-closing row is reached.
            ["", "", "150,00", "130,00", 1],
            [LINE_NEGEQ, "", "20,00", "10,00", 1],
            # Table-closing row: only ties to C + D + NEGEQ, i.e. everything
            # since the true top of the table, not just since the reset above.
            ["", "", grand_total_fy2024, grand_total_fy2023, 1],
        ],
    }


def _bilanz(result: list[dict[str, Any]]) -> dict[str, Any]:
    tables = [t for t in result if t.get("type") == 0 and t.get("multi_year")]
    assert len(tables) == 1, f"expected exactly one multi-year Bilanz table, got {len(tables)}"
    return tables[0]


def test_grand_total_row_is_named_bs_a_when_it_ties_to_the_whole_table() -> None:
    result = build_multi_year_tables([_table("170,00", "140,00")])
    bilanz = _bilanz(result)

    matches = [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-A"]
    assert len(matches) == 1, "the table-closing row must resolve to a single named BS-A total"
    assert matches[0]["row_type"] == "subtotal"
    row = bilanz["rows"][bilanz["row_metadata"].index(matches[0]) + 1]
    assert row[1:] == [170.0, 140.0]

    # The intermediate subtotal (an anonymous, unrelated recognition) must
    # still be present and must not itself have been mistaken for BS-A.
    anonymous = [m for m in bilanz["row_metadata"] if m.get("std_id") is None]
    assert len(anonymous) == 1


def test_grand_total_row_stays_unresolved_when_a_component_is_missing() -> None:
    """If the disclosed total doesn't tie to what's actually resolved (e.g. a
    component is still unmapped elsewhere in the real pipeline), the row must
    not be forced into BS-A -- staying queued is the honest outcome."""
    result = build_multi_year_tables([_table("999,00", "999,00")])
    bilanz = _bilanz(result)

    assert not [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-A"]


def test_grand_total_row_is_named_bs_p_for_a_liabilities_side_table() -> None:
    """Swap in a BS-P.* line so the majority-prefix side detection picks
    Passiva instead of Assets -- proving the side isn't hardcoded to Aktiva."""
    table = _table("170,00", "140,00")
    table["rows"][1][0] = "2. Verbindlichkeiten gegenüber Kreditinstituten"  # BS-P.C.2
    table["rows"][2][0] = "3. Erhaltene Anzahlungen auf Bestellungen"  # BS-P.C.3

    result = build_multi_year_tables([table])
    bilanz = _bilanz(result)

    matches = [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-P"]
    assert len(matches) == 1
    row = bilanz["rows"][bilanz["row_metadata"].index(matches[0]) + 1]
    assert row[1:] == [170.0, 140.0]
