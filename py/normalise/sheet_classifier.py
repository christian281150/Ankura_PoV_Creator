"""Content-signature sheet classifier; sheet names are intentionally ignored."""
from __future__ import annotations

from typing import Any

SHEET_TYPES = frozenset({"bilanz", "guv", "kapitalflussrechnung", "anhang_umsatzsplit",
                         "anhang_konsolidierungskreis", "anlagenspiegel", "eigenkapitalspiegel",
                         "fristigkeiten", "lagebericht_vermoegenslage", "lagebericht_finanzlage", "unknown"})


def _text(rows: list[tuple[Any, ...]]) -> str:
    return " ".join(str(cell).lower().replace("\n", " ") for row in rows[:35] for cell in row if cell is not None)


def classify_rows(rows: list[tuple[Any, ...]]) -> str:
    text = _text(rows)
    # Note-table signatures take priority over incidental references to a GuV.
    if "umsatzerlöse setzen sich" in text or ("umsatzerlöse inland" in text and "umsatzerlöse europa" in text) or ("a. segmente" in text and "hemden" in text):
        return "anhang_umsatzsplit"
    if "konsolidierungskreis" in text or ("gesellschaft" in text and "anteil" in text and "erstkonsolidierungszeitpunkt" in text):
        return "anhang_konsolidierungskreis"
    if "eigenkapitalspiegel" in text or "eigenkapital des mutterunternehmens" in text or ("gezeichnetes kapital" in text and "gewinnrücklagen" in text):
        return "eigenkapitalspiegel"
    if "anschaffungskosten" in text or "buchwerte" in text or ("zuschreibungen" in text and "währungsdifferenzen" in text):
        return "anlagenspiegel"
    if "kapitalflussrechnung" in text or ("cashflow" in text and "finanzierungstätigkeit" in text):
        return "kapitalflussrechnung"
    if "gewinn- und verlustrechnung" in text or ("umsatzerlöse" in text and "materialaufwand" in text and "personalaufwand" in text):
        return "guv"
    if ("summe aktiva" in text and "summe passiva" in text) or ("aktiva" in text and "passiva" in text and "anlagevermögen" in text) or ("anlagevermögen" in text and "immaterielle vermögensgegenstände" in text):
        return "bilanz"
    if ("verbindlichkeiten" in text and "1 bis 5" in text and ("über 5" in text or "mehr als 5" in text)):
        return "fristigkeiten"
    if "vermögenslage" in text or ("kurzfristig gebundenes vermögen" in text and "summe aktiva" in text):
        return "lagebericht_vermoegenslage"
    if "finanzlage" in text or ("liquidität" in text and "finanzierung" in text):
        return "lagebericht_finanzlage"
    return "unknown"


def classify_workbook(workbook: Any) -> dict[str, str]:
    return {sheet.title: classify_rows(list(sheet.iter_rows(values_only=True))) for sheet in workbook.worksheets}
