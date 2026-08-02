"""Focused regression tests for framework/method mapping guards."""

from __future__ import annotations

import unittest

from extractor._core import _hgb
from extractor.consolidate import _map_actual, build_multi_year_tables
from extractor.extract import _detect_filing_basis, _detect_method_from_statement_signature


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Pdf:
    def __init__(self, *pages: str) -> None:
        self.pages = [_Page(page) for page in pages]


class FrameworkGuardTests(unittest.TestCase):
    def test_explicit_hgb_gkv_basis_is_detected(self) -> None:
        detected = _detect_filing_basis(_Pdf(
            "Der Konzernabschluss ist nach den deutschen handelsrechtlichen "
            "Rechnungslegungsvorschriften nach den Vorschriften des HGB aufgestellt. "
            "Die Gewinn- und Verlustrechnung ist nach dem Gesamtkostenverfahren aufgegliedert."
        ))
        self.assertEqual("hgb", detected["framework"])
        self.assertEqual("gkv", detected["pnl_method"])

    def test_explicit_ifrs_ukv_basis_is_detected(self) -> None:
        detected = _detect_filing_basis(_Pdf(
            "Der Konzernabschluss wird nach § 315e Abs. 3 HGB in Einklang mit "
            "den International Financial Reporting Standards (IFRS) erstellt. "
            "Der im Gewinn oder Verlust erfasste Aufwand wird nach dem "
            "Umsatzkostenverfahren aufgegliedert."
        ))
        self.assertEqual("ifrs", detected["framework"])
        self.assertEqual("ukv", detected["pnl_method"])

    def test_unknown_framework_queues_without_lookup(self) -> None:
        record, reason, _ = _map_actual("Umsatzkosten", {}, "unknown", "ukv")
        self.assertIsNone(record)
        self.assertEqual("framework_undetermined", reason)

    def test_ifrs_cannot_use_hgb_catalogue(self) -> None:
        record, reason, _ = _map_actual("Umsatzkosten", {}, "ifrs", "ukv")
        self.assertIsNone(record)
        self.assertEqual("unsupported_framework", reason)

    def test_hgb_method_mismatch_is_rejected(self) -> None:
        self.assertIsNotNone(_hgb)
        record, reason, _ = _map_actual("Umsatzkosten", {}, "hgb", "gkv")
        self.assertIsNone(record)
        self.assertEqual("pnl_method_mismatch", reason)

    def test_gkv_signature_accepts_bestandsveraenderung(self) -> None:
        detected = _detect_method_from_statement_signature([{
            "heading": "Ergebnisrechnung",
            "page_start": 1,
            "rows": [["Position"], ["Bestandsveranderung"], ["Personalaufwand"]],
        }])
        self.assertEqual("gkv", detected["pnl_method"])

    def test_conflicting_statement_signatures_are_unknown(self) -> None:
        detected = _detect_method_from_statement_signature([{
            "heading": "Ergebnisrechnung",
            "page_start": 1,
            "rows": [["Position"], ["Materialaufwand"], ["Personalaufwand"],
                     ["Umsatzkosten"], ["Vertriebskosten"]],
        }])
        self.assertIsNone(detected)

    def test_standard_hgb_balance_sheet_positions_map_without_aliases(self) -> None:
        expected = {
            "3. Geleistete Anzahlungen": "BS-A.B.I.4",
            "2. Forderungen gegen Gesellschafter": "BS-A.B.II.2a",
            "3. Forderungen gegen Unternehmen, mit denen ein Beteiligungsverhältnis besteht": "BS-A.B.II.3",
            "III. Kassenbestand, Guthaben bei Kreditinstituten und Schecks": "BS-A.B.IV",
            "C. Rechnungsabgrenzungsposten": "BS-A.C",
        }
        for label, std_id in expected.items():
            record, reason, _ = _map_actual(label, {}, "hgb", "gkv")
            self.assertEqual("normalized", reason)
            self.assertEqual(std_id, record["std_id"])

    def test_hgb_aggregate_and_davon_memo_stay_queued(self) -> None:
        for label, reason in (
            ("4. Materialaufwand", "unsafe_aggregate_heading"),
            ("5. Personalaufwand", "unsafe_aggregate_heading"),
            ("- davon für Altersversorgung", "excluded_davon_note"),
        ):
            record, actual_reason, _ = _map_actual(label, {}, "hgb", "gkv")
            self.assertIsNone(record)
            self.assertEqual(reason, actual_reason)

    def test_davon_notes_are_excluded_from_canonical_output(self) -> None:
        canonical = build_multi_year_tables([{
            "type": 1, "_override_applied": True, "heading": "Ergebnisrechnung",
            "framework": "hgb", "pnl_method": "gkv", "page_start": 1,
            "rows": [["Position", "2025", "2024"],
                     ["1. Umsatzerloese", 1.0, 2.0],
                     ["- davon fuer Altersversorgung: EUR 175.312,74", "175.312,74", "175.312,74"]],
        }])
        self.assertEqual([["Description", "2025", "2024"], ["1. Umsatzerloese", 1.0, 2.0]],
                         canonical[0]["rows"])

    def test_canonical_table_carries_guard_and_page_provenance(self) -> None:
        canonical = build_multi_year_tables([{
            "type": 1, "_override_applied": True, "heading": "Ergebnisrechnung",
            "framework": "hgb", "pnl_method": "gkv",
            "framework_evidence": {"page": 4, "reason": "explicit_accounting_basis"},
            "pnl_method_evidence": {"page": 4, "reason": "explicit_declaration"},
            "page_start": 7, "doc_label": "FY2025",
            "rows": [["Position", "2025", "2024"], ["1. Umsatzerloese", 1, 2]],
        }])
        self.assertEqual(1, len(canonical))
        table = canonical[0]
        self.assertEqual("hgb", table["framework"])
        self.assertEqual("gkv", table["pnl_method"])
        self.assertEqual("explicit_accounting_basis", table["framework_evidence"]["reason"])
        self.assertEqual("explicit_declaration", table["pnl_method_evidence"]["reason"])
        self.assertEqual(7, table["row_metadata"][0]["provenance"]["page"])


if __name__ == "__main__":
    unittest.main()
