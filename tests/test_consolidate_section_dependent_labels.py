"""Regression tests for section-aware label disambiguation.

Genussrechtskapital's HGB equity/debt classification depends on the
instrument's own terms (IDW RS HFA 45) and can legitimately differ between
fiscal years for the same company -- confirmed on the real Seidensticker
fixture, where the identical label "Genussrechtskapital" is disclosed once
under "A. Eigenkapital" (equity, std_id BS-P.A.KG-VI) and once under "D.
Verbindlichkeiten" (debt, std_id BS-P.C-GENUSS), with the values inverted
between FY2023/FY2024. The label text is identical either way -- only the
enclosing lettered Bilanz section disambiguates it, which is why this can't
be solved with a second taxonomy synonym (that would just make the lookup
ambiguous) or with the cross-table "confirmed mirror" exemption (both
disclosures are rows in the very same table, not two tables).
"""
from __future__ import annotations

from typing import Any

from extractor.consolidate import build_multi_year_tables

LINE_C = "C. Rechnungsabgrenzungsposten"
LINE_D = "D. Aktive latente Steuern"


def _passiva_table(*extra_rows: list) -> dict[str, Any]:
    """A minimal synthetic Passiva table with two real, unambiguous anchor
    rows plus whichever Genussrechtskapital disclosure(s) the test supplies."""
    return {
        "index": 1,
        "heading": "Synthetic Passiva table",
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
            *extra_rows,
        ],
    }


def _bilanz(result: list[dict[str, Any]]) -> dict[str, Any]:
    tables = [t for t in result if t.get("type") == 0 and t.get("multi_year")]
    assert len(tables) == 1, f"expected exactly one multi-year Bilanz table, got {len(tables)}"
    return tables[0]


def test_genussrechtskapital_under_eigenkapital_resolves_to_the_equity_std_id() -> None:
    table = _passiva_table(
        ["A. Eigenkapital", "", "", "", 1],
        ["VI. Genussrechtskapital", "", "6.000.000,00", "0,00", 1],
    )
    result = build_multi_year_tables([table])
    bilanz = _bilanz(result)

    matches = [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-P.A.KG-VI"]
    assert len(matches) == 1
    row = bilanz["rows"][bilanz["row_metadata"].index(matches[0]) + 1]
    assert row[1:] == [6000000.0, 0.0]
    assert not any(m.get("std_id") == "BS-P.C-GENUSS" for m in bilanz["row_metadata"])


def test_genussrechtskapital_under_verbindlichkeiten_resolves_to_the_debt_std_id() -> None:
    table = _passiva_table(
        ["D. Verbindlichkeiten", "", "", "", 1],
        ["1. Genussrechtskapital", "0,00", "", "6.000.000,00", 1],
    )
    result = build_multi_year_tables([table])
    bilanz = _bilanz(result)

    matches = [m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-P.C-GENUSS"]
    assert len(matches) == 1
    row = bilanz["rows"][bilanz["row_metadata"].index(matches[0]) + 1]
    assert row[1:] == [0.0, 6000000.0]
    assert not any(m.get("std_id") == "BS-P.A.KG-VI" for m in bilanz["row_metadata"])


def test_both_disclosures_in_one_filing_resolve_distinctly_with_no_collision() -> None:
    """The real Seidensticker shape: the same label disclosed twice in one
    filing, once per side, with inverted values between years -- must
    resolve to two distinct std_ids, not collide."""
    table = _passiva_table(
        ["A. Eigenkapital", "", "", "", 1],
        ["VI. Genussrechtskapital", "", "6.000.000,00", "0,00", 1],
        ["D. Verbindlichkeiten", "", "", "", 1],
        ["1. Genussrechtskapital", "0,00", "", "6.000.000,00", 1],
    )
    result = build_multi_year_tables([table])
    bilanz = _bilanz(result)

    equity = next(m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-P.A.KG-VI")
    debt = next(m for m in bilanz["row_metadata"] if m.get("std_id") == "BS-P.C-GENUSS")
    equity_row = bilanz["rows"][bilanz["row_metadata"].index(equity) + 1]
    debt_row = bilanz["rows"][bilanz["row_metadata"].index(debt) + 1]
    assert equity_row[1:] == [6000000.0, 0.0]
    assert debt_row[1:] == [0.0, 6000000.0]

    # No std_id_collision entry should have been queued for this label.
    queued: list[dict] = []
    from extractor.consolidate import _column_actuals, _load_exact_aliases
    _column_actuals(table, _load_exact_aliases(), queued)
    assert not any("genussrechtskapital" in str(entry.get("normalized_key", "")).lower() for entry in queued)
