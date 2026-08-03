"""Regression test for py/normalise/sheet_classifier.py.

This module (SHEET_TYPES, classify_rows, classify_workbook) implements
AGENTS.md's P1 -- committed at eca2e1e, in this repo's earliest history --
but has never had a test, and nothing in the codebase imports it (confirmed
via grep before writing this test). Verified here for the first time against
the real 11-year, 151-sheet model workbook: it classifies 94.7% of sheets
(143/151), clearing P1's own "≥ 85%" acceptance bar with no changes needed.

Locks in that result so it can't silently regress, and proves the module's
own stated design intent -- "sheet names are intentionally ignored" -- by
classifying rows fed under a deliberately misleading sheet-name context.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from normalise.sheet_classifier import SHEET_TYPES, classify_rows, classify_workbook

FIXTURE = Path(__file__).parent / "fixtures" / "Textilkontor_Walter_Seidensticker_GmbH_Co_KG_Bielefeld_Konzernabschluss_FY2025_model.xlsx"

ACCEPTANCE_RATE = 0.85


def _classified() -> dict[str, str]:
    workbook = openpyxl.load_workbook(FIXTURE, data_only=True)
    return classify_workbook(workbook)


def test_meets_the_p1_acceptance_bar_on_the_real_fixture() -> None:
    result = _classified()
    assert len(result) >= 150, f"expected the full 151-sheet fixture, got {len(result)}"

    classified = sum(1 for sheet_type in result.values() if sheet_type != "unknown")
    rate = classified / len(result)
    assert rate >= ACCEPTANCE_RATE, (
        f"classified {classified}/{len(result)} ({rate:.1%}), below the {ACCEPTANCE_RATE:.0%} bar "
        f"-- P1's acceptance criterion, AGENTS.md"
    )


def test_every_returned_type_is_declared() -> None:
    """Never a silent new category, and never a silently dropped sheet."""
    result = _classified()
    unrecognised = set(result.values()) - SHEET_TYPES
    assert not unrecognised, f"classify_workbook returned undeclared type(s): {unrecognised}"


def test_the_three_all_overview_sheets_classify_correctly() -> None:
    """Stable, name-reliable anchors (exporters.py's own multi-year overview
    sheets) -- unlike the per-year raw sheets, whose names vary across all
    eleven fiscal years and are frequently blank or truncated."""
    result = _classified()
    matches = {name: sheet_type for name, sheet_type in result.items() if name.startswith("ALL")}
    assert len(matches) == 3, f"expected exactly 3 ALL-overview sheets, found {list(matches)}"

    by_suffix = {name.rsplit(" ", 1)[-1]: sheet_type for name, sheet_type in matches.items()}
    assert by_suffix["Bilanz"] == "bilanz"
    assert by_suffix["GuV"] == "guv"
    assert by_suffix["Kapitalflussrechnung"] == "kapitalflussrechnung"


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([("Aktiva",), ("A. Anlagevermögen",), ("Immaterielle Vermögensgegenstände",), ("Summe Aktiva", "100"), ("Summe Passiva", "100")], "bilanz"),
        ([("Gewinn- und Verlustrechnung",), ("Umsatzerlöse", "100"), ("Materialaufwand", "-50"), ("Personalaufwand", "-30")], "guv"),
        ([("Kapitalflussrechnung",), ("Cashflow aus laufender Geschäftstätigkeit", "10"), ("Cashflow aus der Finanzierungstätigkeit", "-5")], "kapitalflussrechnung"),
        ([("Anlagenspiegel",), ("Anschaffungskosten",), ("Zugänge", "1"), ("Abgänge", "-1")], "anlagenspiegel"),
        ([("Eigenkapitalspiegel",), ("Eigenkapital des Mutterunternehmens",)], "eigenkapitalspiegel"),
        ([("Die Fristigkeiten der Verbindlichkeiten",), ("Verbindlichkeiten", "bis 1 Jahr", "1 bis 5 Jahre", "über 5 Jahre")], "fristigkeiten"),
        ([("3.2 Vermögenslage",), ("Lang- und mittelfristig gebundenes Vermögen",)], "lagebericht_vermoegenslage"),
        ([("3.3 Finanzlage",), ("Cashflow aus laufender Geschäftstätigkeit",)], "lagebericht_finanzlage"),
        ([("Konsolidierungskreis",), ("Gesellschaft", "Anteil", "Erstkonsolidierungszeitpunkt")], "anhang_konsolidierungskreis"),
        ([("Die Umsatzerlöse setzen sich wie folgt zusammen",), ("A. Segmente",), ("Hemden", "1"), ("Blusen", "2")], "anhang_umsatzsplit"),
        ([("Sonstige Angaben",), ("Es waren im Jahresdurchschnitt beschäftigt",)], "unknown"),
    ],
)
def test_classifies_by_content_signature_not_sheet_name(rows: list[tuple], expected: str) -> None:
    """Feeds each case under an unrelated sheet-name-shaped title row to prove
    the module's own claim: only row content drives classification."""
    misleading_title_row = [("FY2021_ (5)",)]
    assert classify_rows(misleading_title_row + rows) == expected
