"""Fixture regressions for Lagebericht section boundaries.

Run from the Bundesanzeiger submodule with:
    ..\\..\\..\\..\\.venv\\Scripts\\python.exe -m unittest dev/test_lagebericht.py
"""

import sys
import unittest
from pathlib import Path

import pdfplumber


SUBMODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SUBMODULE_ROOT.parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(SUBMODULE_ROOT))

from extractor.extract import _extract_narrative_sections  # noqa: E402


Vermoegenslage = "Verm" + chr(0x00F6) + "genslage"


class TestLageberichtSections(unittest.TestCase):
    """Known narrative sections retain their own prose and boundaries."""

    def _sections(self, filename: str) -> list[dict]:
        with pdfplumber.open(FIXTURES / filename) as pdf:
            table_bboxes = {
                page_number: [table.bbox for table in page.find_tables()]
                for page_number, page in enumerate(pdf.pages, 1)
            }
            return _extract_narrative_sections(pdf, table_bboxes)

    def _assert_sections(self, filename: str, expected: dict[str, tuple[int, str, str]]) -> None:
        sections = self._sections(filename)
        by_heading = {section["heading"]: section for section in sections}
        for heading, (count, first_sentence, last_sentence) in expected.items():
            with self.subTest(heading=heading):
                rows = by_heading[heading]["rows"][1:]
                self.assertEqual(len(rows), count)
                self.assertTrue(rows[0][1].startswith(first_sentence))
                self.assertTrue(rows[-1][1].endswith(last_sentence))

        self.assertTrue(any(section["heading"].startswith("Unknown section:")
                            for section in sections))

    def test_textilkontor_fy2024_sections(self) -> None:
        self._assert_sections("Textilkontor_HRA8217_Konzernabschluss_FY2024.pdf", {
            "Ertragslage": (
                22,
                "Die Umsatzerl\u00f6se sanken um 18,7 % auf T\u20ac 103.152 (Vorjahr T\u20ac 126.812).",
                "Gegen\u00fcber dem Vorjahr hat sich das Ergebnis um T\u20ac 1.709 verbessert.",
            ),
            Vermoegenslage: (
                10,
                "Aus den Bilanzen zum 30. April 2024 und 30. April 2023 des Konzerns ",
                "Die kurzfristigen sonstigen R\u00fcckstellungen und Steuerr\u00fcckstellungen sanken um "
                "T\u20ac 1.497, die Sonstigen Verbindlichkeiten unter Einbezug des Rechnungsabgrenzungspostens "
                "sanken um T\u20ac 357.",
            ),
            "Nachtragsbericht": (
                3,
                "Trotz Umsetzung diverser Restrukturierungsma\u00dfnahmen in den vergangenen Jahren ",
                "Bei Aufstellung des Konzernabschlusses sind wir daher trotz der zum Abschlussstichtag "
                "ausgewiesenen bilanziellen Unterdeckung (T\u20ac 13.822) von der Fortf\u00fchrung der "
                "Unternehmenst\u00e4tigkeit ausgegangen, da dieser mit \u00fcberwiegender Wahrscheinlichkeit "
                "keine tats\u00e4chlichen oder rechtlichen Gegebenheiten entgegenstehen.",
            ),
        })

    def test_ctec_fy2025_sections(self) -> None:
        self._assert_sections("CTEC_I_HRB784500_Konzernabschluss_FY2025.pdf", {
            "Ertragslage": (
                15,
                "Im Gesch\u00e4ftsjahr 2025 erzielte der CTEC I-Konzern Umsatzerl\u00f6se von TEUR 685.401 ",
                "Auch hier ist der R\u00fcckgang insbesondere auf die im Vergleich zum Vorjahr geringeren "
                "Umsatzerl\u00f6se zur\u00fcckzuf\u00fchren.",
            ),
            Vermoegenslage: (
                30,
                "Die Bilanzsumme des Konzerns betr\u00e4gt zum 31. Dezember 2025 TEUR 3.733.395 ",
                "Alle drei Linien wurden im aktuellen Gesch\u00e4ftsjahr, wie im Vorjahr, nicht in Anspruch genommen.",
            ),
            "Nachtragsbericht": (
                15,
                "Nach dem Abschluss des Gesch\u00e4ftsjahres wurde die Laufzeit der bestehenden "
                "Konsortialfinanzierung fr\u00fchzeitig verl\u00e4ngert.",
                "Auf die Konzern-Kapitalflussrechnung h\u00e4tten sich keine wesentlichen Auswirkungen ergeben, "
                "wenn die Konzern-Kapitalflussrechnung der CTEC II anstelle der in diesem Abschluss dargestellten "
                "Konzern-Kapitalflussrechnung aufgestellt worden w\u00e4re.",
            ),
        })


if __name__ == "__main__":
    unittest.main()
