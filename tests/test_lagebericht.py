from pathlib import Path
import sys

from openpyxl import Workbook

NORMALISE_DIR = Path(__file__).parents[1] / "py" / "normalise"
sys.path.insert(0, str(NORMALISE_DIR))

from lagebericht import extract_lagebericht, parse_lagebericht_sheet


def _sheet() -> object:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "FY2025_3.3 Finanzlage"
    worksheet.append(["Lagebericht in T€"])
    worksheet.append(["Das Betriebsergebnis betrug T€ -993 nach T€ 1.234 im Vorjahr (Jahresergebnis vor Finanzergebnis und Steuern)."])
    worksheet.append(["In den sonstigen betrieblichen Erträgen sind periodenfremde Erträge von T€ 250 enthalten."])
    worksheet.append(["Der Umsatz im Segment Hemden ging aufgrund geringerer Nachfrage zurück."])
    worksheet.append(["Die Fortführungsprognose ist positiv; die bilanzielle Unterdeckung beträgt T€ 500."])
    worksheet.append(["Die Finanzierungsvereinbarung wurde am 15.03.2025 angepasst."])
    worksheet.append(["Die Beispiel Handels GmbH wurde zum 01.01.2025 erstmals in den Konsolidierungskreis einbezogen."])
    worksheet.append(["Ein nicht operativer Sondereffekt wurde erläutert."])
    return worksheet


def test_extracts_stated_lagebericht_facts_with_eur_normalisation_and_provenance() -> None:
    extracted = parse_lagebericht_sheet(_sheet())

    operating = extracted.operating_results[0]
    assert operating.value == -993_000
    assert operating.prior_year_value == 1_234_000
    assert operating.unit == "EUR"
    assert operating.source_unit == "TEUR"
    assert operating.provenance.sheet == "FY2025_3.3 Finanzlage"
    assert operating.provenance.row == 2

    one_off = extracted.one_offs[0]
    assert one_off.value == 250_000
    assert one_off.direction == "income"
    assert one_off.pnl_line == "sonstige betriebliche Erträge"
    assert extracted.movement_explanations[0].metric == "revenue"
    assert extracted.movement_explanations[0].segment_or_division == "Hemden"
    assert extracted.movement_explanations[0].sentence.startswith("Der Umsatz im Segment Hemden")

    underdeckung = next(item for item in extracted.going_concern if item.kind == "bilanzielle_unterdeckung")
    assert underdeckung.value == 500_000
    financing = next(item for item in extracted.going_concern if item.kind == "financing_agreement")
    assert financing.dates == ("15.03.2025",)
    scope = extracted.scope_changes[0]
    assert scope.change == "entered"
    assert scope.entity == "Beispiel Handels GmbH"
    assert scope.dates == ("01.01.2025",)


def test_ambiguous_one_off_is_retained_without_an_inferred_amount() -> None:
    extracted = parse_lagebericht_sheet(_sheet())
    ambiguous = extracted.one_offs[-1]

    assert ambiguous.value is None
    assert ambiguous.unit is None
    assert ambiguous.sentence == "Ein nicht operativer Sondereffekt wurde erläutert."


def test_only_classifier_approved_sheets_are_read() -> None:
    approved = _sheet()
    workbook = approved.parent
    ignored = workbook.create_sheet("FY2025_not_lagebericht")
    ignored.append(["Lagebericht in T€"])
    ignored.append(["Das Betriebsergebnis betrug T€ 999."])

    extracted = extract_lagebericht(workbook, {approved.title: "lagebericht_finanzlage", ignored.title: "unknown"})

    assert len(extracted.operating_results) == 1
    assert extracted.operating_results[0].value == -993_000
