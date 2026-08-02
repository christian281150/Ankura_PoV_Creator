"""Regression tests for structural HGB-label normalisation."""

from __future__ import annotations

import unittest

from lib import hgb_map
from lib.hgb_data.hgb_lookup_reference import _normalize as build_normalize


class HGBNormalizeTests(unittest.TestCase):
    def test_leading_enumerators_are_structural(self) -> None:
        cases = {
            "1. Umsatzerl\u00f6se": "umsatzerloese",
            "12. Sonstige Steuern": "sonstigesteuern",
            "5a. Aufwendungen f\u00fcr bezogene Leistungen": "aufwendungenfuerbezogeneleistungen",
            "2a. Forderungen gegen Gesellschafter": "forderungengegengesellschafter",
            "a) L\u00f6hne und Geh\u00e4lter": "loehneundgehaelter",
            "b) Sonstige Steuern": "sonstigesteuern",
            "A. Anlageverm\u00f6gen": "anlagevermoegen",
            "E. Aktiver Unterschiedsbetrag": "aktiverunterschiedsbetrag",
            "I. Immaterielle Verm\u00f6gensgegenst\u00e4nde": "immateriellevermoegensgegenstaende",
            "II. Sachanlagen": "sachanlagen",
            "III. Finanzanlagen": "finanzanlagen",
            "IV. Kassenbestand": "kassenbestand",
            "V. Jahres\u00fcberschuss": "jahresueberschuss",
            "VI. Sonstige Steuern": "sonstigesteuern",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(expected, hgb_map.normalize(label))
                self.assertEqual(expected, build_normalize(label))

    def test_only_a_leading_enumerator_with_whitespace_is_removed(self) -> None:
        cases = {
            "3D-Druck": "3ddruck",
            "2025 Umsatz": "2025umsatz",
            "1.Umsatzerl\u00f6se": "1umsatzerloese",
            "a)Umsatzerl\u00f6se": "aumsatzerloese",
            "C.Rechnungsabgrenzungsposten": "crechnungsabgrenzungsposten",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(expected, hgb_map.normalize(label))

    def test_pdf_cleanup_precedes_matching(self) -> None:
        self.assertEqual("anderer", hgb_map.normalize("an-\nderer"))
        self.assertEqual("sachanlagevermoegens", hgb_map.normalize("Sach-\nanlageverm\u00f6gens"))
        self.assertEqual("materialaufwand", hgb_map.normalize("3. Materialaufwand (GKV)"))

    def test_numbered_revenue_maps_exactly(self) -> None:
        result = hgb_map.lookup("1. Umsatzerl\u00f6se")
        self.assertEqual("normalized", result["match_type"])
        self.assertEqual("PL_GKV-1", result["candidates"][0]["std_id"])


if __name__ == "__main__":
    unittest.main()
