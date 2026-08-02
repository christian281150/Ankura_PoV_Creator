"""Exact, standards-derived IFRS presentation taxonomy (IAS 1 and IAS 7).

This is intentionally independent from ``hgb_map``.  Captions are limited to
IAS 1.54, 82/82A, 91, 99--105 and IAS 7 presentation categories; issuer-made
subtotals and note disclosures belong in review, not this catalogue.
"""
from __future__ import annotations

import re
from typing import Any


def normalize(text: str) -> str:
    text = str(text or "").lower()
    for old, new in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(old, new)
    return "".join(char for char in text if char.isalnum())


def _record(std_id: str, statement: str, row_type: str, de: str, en: str,
            *synonyms: str, oci: bool = False) -> dict[str, Any]:
    return {"std_id": std_id, "statement": statement, "row_type": row_type,
            "canonical_de": de, "canonical_en": en, "oci": oci,
            "synonyms": (de, en, *synonyms)}


# IAS 1.54 statement of financial position.  IAS 1 permits disaggregation, so
# only the required presentation categories are catalogued here.
_RECORDS = [
    _record("IFRS_BS-01", "IFRS_BS", "line", "Sachanlagen", "Property, plant and equipment", "property plant and equipment"),
    _record("IFRS_BS-02", "IFRS_BS", "line", "Als Finanzinvestition gehaltene Immobilien", "Investment property"),
    _record("IFRS_BS-03", "IFRS_BS", "line", "Immaterielle Vermögenswerte", "Intangible assets"),
    _record("IFRS_BS-04", "IFRS_BS", "line", "Finanzielle Vermögenswerte", "Financial assets"),
    _record("IFRS_BS-05", "IFRS_BS", "line", "Nach der Equity-Methode bilanzierte Beteiligungen", "Investments accounted for using the equity method"),
    _record("IFRS_BS-06", "IFRS_BS", "line", "Biologische Vermögenswerte", "Biological assets"),
    _record("IFRS_BS-07", "IFRS_BS", "line", "Vorräte", "Inventories"),
    _record("IFRS_BS-08", "IFRS_BS", "line", "Forderungen aus Lieferungen und Leistungen und sonstige Forderungen", "Trade and other receivables", "forderungen aus lieferungen und leistungen"),
    _record("IFRS_BS-09", "IFRS_BS", "line", "Zahlungsmittel und Zahlungsmitteläquivalente", "Cash and cash equivalents"),
    _record("IFRS_BS-10", "IFRS_BS", "line", "Zur Veräußerung gehaltene Vermögenswerte", "Assets held for sale"),
    _record("IFRS_BS-11", "IFRS_BS", "line", "Verbindlichkeiten aus Lieferungen und Leistungen und sonstige Verbindlichkeiten", "Trade and other payables", "verbindlichkeiten aus lieferungen und leistungen"),
    _record("IFRS_BS-12", "IFRS_BS", "line", "Rückstellungen", "Provisions"),
    _record("IFRS_BS-13", "IFRS_BS", "line", "Finanzielle Verbindlichkeiten", "Financial liabilities"),
    _record("IFRS_BS-14", "IFRS_BS", "line", "Laufende Steuerverbindlichkeiten und -forderungen", "Current tax liabilities and assets"),
    _record("IFRS_BS-15", "IFRS_BS", "line", "Latente Steueransprüche und -schulden", "Deferred tax assets and liabilities", "aktive latente steuern", "passive latente steuern"),
    _record("IFRS_BS-16", "IFRS_BS", "line", "Verbindlichkeiten in Verbindung mit zur Veräußerung gehaltenen Vermögenswerten", "Liabilities held for sale"),
    _record("IFRS_BS-17", "IFRS_BS", "line", "Nicht beherrschende Anteile", "Non-controlling interests", "nicht beherrschende gesellschafter"),
    _record("IFRS_BS-18", "IFRS_BS", "line", "Gezeichnetes Kapital und Rücklagen", "Issued capital and reserves", "eigenkapital"),
    _record("IFRS_BS-19", "IFRS_BS", "memo", "Vermögenswerte", "Assets"),
    _record("IFRS_BS-20", "IFRS_BS", "memo", "Schulden und Eigenkapital", "Liabilities and equity"),
    # IAS 1.82/82A and IAS 1.91; OCI lines are explicitly segregated.
    _record("IFRS_PL_UKV-01", "IFRS_PL_UKV", "line", "Umsatzerlöse", "Revenue"),
    _record("IFRS_PL_UKV-02", "IFRS_PL_UKV", "line", "Umsatzkosten", "Cost of sales"),
    _record("IFRS_PL_UKV-03", "IFRS_PL_UKV", "subtotal", "Bruttoergebnis", "Gross profit", "bruttoergebnis vom umsatz"),
    _record("IFRS_PL_UKV-04", "IFRS_PL_UKV", "line", "Vertriebskosten", "Distribution costs", "selling expenses"),
    _record("IFRS_PL_UKV-05", "IFRS_PL_UKV", "line", "Allgemeine Verwaltungskosten", "Administrative expenses", "administrative expenses"),
    _record("IFRS_PL_UKV-06", "IFRS_PL_UKV", "line", "Sonstige Erträge und Aufwendungen", "Other gains and losses", "other income and expenses"),
    _record("IFRS_PL_UKV-07", "IFRS_PL_UKV", "line", "Finanzerträge", "Finance income", "zinserträge und sonstige finanzerträge", "interest income"),
    _record("IFRS_PL_UKV-08", "IFRS_PL_UKV", "line", "Finanzaufwendungen", "Finance costs", "zinsaufwendungen und sonstige finanzaufwendungen", "interest expense"),
    _record("IFRS_PL_UKV-09", "IFRS_PL_UKV", "subtotal", "Ergebnis vor Ertragsteuern", "Profit or loss before tax"),
    _record("IFRS_PL_UKV-10", "IFRS_PL_UKV", "line", "Ertragsteueraufwand oder -ertrag", "Income tax expense or income", "erträge aufwendungen aus ertragsteuern"),
    _record("IFRS_PL_UKV-11", "IFRS_PL_UKV", "subtotal", "Gewinn oder Verlust", "Profit or loss", "jahresfehlbetrag jahresüberschuss"),
    _record("IFRS_PL_UKV-12", "IFRS_PL_UKV", "memo", "Auf Anteilseigner des Mutterunternehmens entfallender Gewinn oder Verlust", "Profit or loss attributable to owners of the parent", "gesellschafter des mutterunternehmens"),
    _record("IFRS_PL_UKV-13", "IFRS_PL_UKV", "memo", "Auf nicht beherrschende Anteile entfallender Gewinn oder Verlust", "Profit or loss attributable to non-controlling interests", "nicht beherrschende gesellschafter"),
    _record("IFRS_PL_UKV-OCI-01", "IFRS_PL_UKV", "subtotal", "Sonstiges Ergebnis", "Other comprehensive income", "sonstiges ergebnis nach ertragsteuern", oci=True),
    _record("IFRS_PL_UKV-OCI-02", "IFRS_PL_UKV", "line", "Neubewertungen leistungsorientierter Pläne", "Remeasurements of defined benefit plans", "ergebnis aus der neubewertung der pensionsrückstellungen", oci=True),
    _record("IFRS_PL_UKV-OCI-03", "IFRS_PL_UKV", "line", "Cashflow-Hedges", "Cash flow hedges", "ergebnis aus cashflow hedges", oci=True),
    _record("IFRS_PL_UKV-OCI-04", "IFRS_PL_UKV", "line", "Währungsumrechnungsdifferenzen", "Exchange differences on translation", "unterschiedsbetrag aus der währungsumrechnung", oci=True),
    _record("IFRS_PL_UKV-OCI-05", "IFRS_PL_UKV", "line", "Ertragsteuern auf sonstiges Ergebnis", "Income tax relating to other comprehensive income", "latente steuern", oci=True),
    _record("IFRS_PL_UKV-OCI-06", "IFRS_PL_UKV", "subtotal", "Gesamtergebnis", "Total comprehensive income", oci=True),
    _record("IFRS_PL_GKV-01", "IFRS_PL_GKV", "line", "Umsatzerlöse", "Revenue"),
    _record("IFRS_PL_GKV-02", "IFRS_PL_GKV", "line", "Materialaufwand", "Cost of materials"),
    _record("IFRS_PL_GKV-03", "IFRS_PL_GKV", "line", "Personalaufwand", "Employee benefits expense"),
    _record("IFRS_PL_GKV-04", "IFRS_PL_GKV", "line", "Abschreibungen", "Depreciation and amortisation expense"),
    _record("IFRS_CF-01", "IFRS_CF", "subtotal", "Cashflow aus betrieblicher Tätigkeit", "Net cash from operating activities"),
    _record("IFRS_CF-02", "IFRS_CF", "subtotal", "Cashflow aus Investitionstätigkeit", "Net cash from investing activities"),
    _record("IFRS_CF-03", "IFRS_CF", "subtotal", "Cashflow aus Finanzierungstätigkeit", "Net cash from financing activities"),
    _record("IFRS_CF-04", "IFRS_CF", "subtotal", "Zahlungsmittel und Zahlungsmitteläquivalente am Ende der Periode", "Cash and cash equivalents at end of period"),
]

_BY_ID = {record["std_id"]: record for record in _RECORDS}
_INDEX: dict[str, list[dict[str, Any]]] = {}
for record in _RECORDS:
    for synonym in record["synonyms"]:
        _INDEX.setdefault(normalize(synonym), []).append(record)


def by_id(std_id: str) -> dict[str, Any] | None:
    return _BY_ID.get(std_id)


def lookup(label: str, pnl_method: str = "unknown") -> dict[str, Any]:
    candidates = list(_INDEX.get(normalize(label), []))
    if pnl_method in {"gkv", "ukv"}:
        candidates = [candidate for candidate in candidates
                      if not candidate["statement"].startswith("IFRS_PL_")
                      or candidate["statement"] == f"IFRS_PL_{pnl_method.upper()}"]
    return {"query": label, "normalized": normalize(label),
            "match_type": "normalized" if len(candidates) == 1 else ("ambiguous" if candidates else "none"),
            "candidates": candidates}
