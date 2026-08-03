"""Regression tests for build_multi_year_tables' cross-table collision guard.

Synthetic, taxonomy-fixture-independent: uses BS-A.C (Rechnungsabgrenzungsposten)
and BS-A.D (Aktive latente Steuern), two real, already-resolvable single-line
std_ids, so these tests don't depend on any lane's in-progress taxonomy work.

Both disputed-row labels differ textually between the two tables (mirroring
the real "E. ..." vs "V. ..." Aktiva/Passiva shape) so the collision guard's
`raw_label != raw_label` branch is actually exercised -- a same-label pair
would never reach it at all, on old code or new.
"""
from __future__ import annotations

from typing import Any

from extractor.consolidate import build_multi_year_tables

DISPUTED_LABEL_A = "C. Rechnungsabgrenzungsposten"
DISPUTED_LABEL_B = "III. Rechnungsabgrenzungsposten"
ANCHOR_LABEL = "D. Aktive latente Steuern"


def _bs_table(index: int, disputed_label: str, disputed_fy2024: str, disputed_fy2023: str) -> dict[str, Any]:
    """A minimal synthetic Bilanz table with one disputed row and one anchor row.

    The anchor row (identical across both tables) guarantees the group still
    clears build_multi_year_tables' `len(yearly) < 2` floor even when the
    disputed row collides and is removed for both years.
    """
    return {
        "index": index,
        "heading": f"Synthetic Bilanz table {index}",
        "type": 0,
        "_override_applied": True,
        "framework": "hgb",
        "pnl_method": "gkv",
        "doc_label": "",
        "page_start": index,
        "rows": [
            ["", "2024", "", "2023", "PDF Page"],
            [disputed_label, "", disputed_fy2024, disputed_fy2023, index],
            [ANCHOR_LABEL, "", "50,00", "40,00", index],
        ],
    }


def _bilanz(result: list[dict[str, Any]]) -> dict[str, Any]:
    tables = [t for t in result if t.get("type") == 0 and t.get("multi_year")]
    assert len(tables) == 1, f"expected exactly one multi-year Bilanz table, got {len(tables)}"
    return tables[0]


def test_same_std_id_same_value_from_two_tables_is_a_confirmed_mirror_not_a_collision() -> None:
    """A GmbH & Co. KG-style mirror: one fact disclosed on two source tables.

    Same std_id, different raw label text (as with a real Aktiva/Passiva
    mirror), but an identical value on both tables -- e.g. a KG's "loss not
    covered by capital contributions" appearing on both Aktiva and Passiva
    with the same figure. This must survive, not be treated as an ambiguous
    collision and discarded.
    """
    tables = [
        _bs_table(1, DISPUTED_LABEL_A, "1.000,00", "900,00"),
        _bs_table(2, DISPUTED_LABEL_B, "1.000,00", "900,00"),
    ]
    result = build_multi_year_tables(tables)
    bilanz = _bilanz(result)

    matches = [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-A.C"]
    assert len(matches) == 1, "the confirmed mirror must produce exactly one row, not zero"
    row = bilanz["rows"][bilanz["row_metadata"].index(matches[0]) + 1]
    assert row[1:] == [1000.0, 900.0]


def test_same_std_id_different_value_from_two_tables_still_collides() -> None:
    """The general collision guard must still fire when values genuinely differ.

    Same std_id, different raw label text, and a different figure on each
    table for both fiscal years is exactly the ambiguous case the guard
    exists for -- confirming the mirror exception is narrow and did not
    loosen collision detection generally.
    """
    tables = [
        _bs_table(1, DISPUTED_LABEL_A, "1.000,00", "900,00"),
        _bs_table(2, DISPUTED_LABEL_B, "1.500,00", "1.200,00"),
    ]
    result = build_multi_year_tables(tables)
    bilanz = _bilanz(result)

    matches = [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-A.C"]
    assert not matches, "genuinely conflicting values must not survive as a resolved row"
    assert any(m.get("std_id") == "BS-A.D" for m in bilanz["row_metadata"]), \
        "the unrelated anchor row must be unaffected"
