"""
dev_test.py  -  Pre-bake development test harness
==================================================
Run this INSTEAD of build.bat during development so you can test any change
immediately without waiting for PyInstaller.

Usage
-----
  python dev_test.py                    # run all unit tests (no browser / GUI)
  python dev_test.py gui                # launch the full GUI directly
  python dev_test.py pdf  <file.pdf>    # extract tables from a local PDF and print them
  python dev_test.py excel <file.pdf>   # export a local PDF to Excel, open the result
  python dev_test.py search "<company>" # open browser, search, download interactively

Examples
--------
  python dev_test.py
  python dev_test.py gui
  python dev_test.py pdf  "C:/Downloads/UR_Extracts/CTEC/CTEC_Jahresabschluss_2024.pdf"
  python dev_test.py excel "C:/Downloads/UR_Extracts/CTEC/CTEC_Jahresabschluss_2024.pdf"
  python dev_test.py search "CTEC I GmbH"
"""

import sys
import os
import io
import asyncio
import argparse
import tempfile
import unittest
from pathlib import Path

# This dev/test harness lives under dev/; put the project root on the path so
# `import ur_extractor` / `import ur_gui` resolve when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force UTF-8 output so special chars survive on any terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Make sure we import from this folder, not an installed package
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Colour helpers (work in Windows Terminal / VS Code; plain text in old cmd.exe)
_IS_TTY = sys.stdout.isatty()
def _c(code, txt): return f"\033[{code}m{txt}\033[0m" if _IS_TTY else txt
def green(t):  return _c("92", t)
def red(t):    return _c("91", t)
def yellow(t): return _c("93", t)
def cyan(t):   return _c("96", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)


# ============================================================================
# Unit tests - pure functions, no browser, no GUI, instant feedback
# ============================================================================

class TestNumberParsing(unittest.TestCase):
    """_parse_num_cell: German locale number disambiguation."""

    @classmethod
    def setUpClass(cls):
        from ur_extractor import _parse_num_cell
        cls.p = staticmethod(_parse_num_cell)

    def _g(self, val):
        """Parse with German separators (. thousands, , decimal)."""
        return self.p(val, thousand_sep=".", decimal_sep=",")

    # Valid German numbers
    def test_german_thousands_simple(self):
        self.assertAlmostEqual(self._g("166.825"), 166825.0)

    def test_german_thousands_with_decimal(self):
        self.assertAlmostEqual(self._g("1.234,56"), 1234.56)

    def test_german_large_with_decimal(self):
        self.assertAlmostEqual(self._g("10.696.470,77"), 10696470.77)

    def test_german_negative_thousands(self):
        self.assertAlmostEqual(self._g("-1.879.466"), -1879466.0)

    def test_german_negative_with_decimal(self):
        self.assertAlmostEqual(self._g("-1.234,56"), -1234.56)

    def test_german_1234(self):
        self.assertAlmostEqual(self._g("1.234"), 1234.0)

    def test_plain_integer(self):
        self.assertAlmostEqual(self._g("12345"), 12345.0)

    def test_zero(self):
        self.assertAlmostEqual(self._g("0"), 0.0)

    def test_negative_plain(self):
        self.assertAlmostEqual(self._g("-42"), -42.0)

    def test_comma_decimal_only(self):
        self.assertAlmostEqual(self._g("3,14"), 3.14)

    # Anhang references - must return None, never parsed as a number
    def test_anhang_4_8(self):
        # 1 digit after dot -> not valid German thousands -> Anhang reference
        self.assertIsNone(self._g("4.8"))

    def test_anhang_12_3(self):
        self.assertIsNone(self._g("12.3"))

    def test_single_sep_decimal_1_2345(self):
        # 4 digits after dot -> not valid group-of-3 -> falls through to
        # single-sep-as-decimal path (same as "87.0596") -> 1.2345, not None
        result = self._g("1.2345")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 1.2345, places=4)

    # Non-numeric -> None
    def test_empty(self):
        self.assertIsNone(self._g(""))

    def test_text_only(self):
        self.assertIsNone(self._g("Aktiva"))

    def test_dash_only(self):
        # bare "-" is used as "n/a" in German tables - must not crash
        self.assertIsNone(self._g("-"))

    # Single-separator decimal (no thousands separator present)
    def test_unusual_decimal(self):
        # "87.0596" - 4 digits after dot, no comma -> single-sep-as-decimal path
        result = self._g("87.0596")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 87.0596, places=3)


class TestAccountingIndent(unittest.TestCase):
    """_acct_indent: hierarchy-level detection for Excel indentation."""

    @classmethod
    def setUpClass(cls):
        from ur_extractor import _acct_indent
        cls.ind = staticmethod(_acct_indent)

    # Level 0 - top-level totals and headers
    def test_aktiva(self):             self.assertEqual(self.ind("Aktiva"), 0)
    def test_passiva(self):            self.assertEqual(self.ind("Passiva"), 0)
    def test_bilanzsumme(self):        self.assertEqual(self.ind("Bilanzsumme"), 0)
    def test_summe_aktiva(self):       self.assertEqual(self.ind("Summe Aktiva"), 0)
    def test_summe_passiva(self):      self.assertEqual(self.ind("Summe Passiva"), 0)
    def test_jahresueberschuss(self):  self.assertEqual(self.ind("Jahresueberschuss"), 0)

    # Level 1 - capital-letter sections A. B. C.
    def test_A(self):   self.assertEqual(self.ind("A. Anlagevermogen"), 1)
    def test_B(self):   self.assertEqual(self.ind("B. Umlaufvermogen"), 1)
    def test_C(self):   self.assertEqual(self.ind("C. Rechnungsabgrenzungsposten"), 1)

    # Level 2 - Roman numerals I. II. III. IV. V.
    # These must NOT be level 1 - the old bug matched "I." as capital-letter
    def test_roman_I(self):   self.assertEqual(self.ind("I. Immaterielle Vermoegensgegenstande"), 2)
    def test_roman_II(self):  self.assertEqual(self.ind("II. Sachanlagen"), 2)
    def test_roman_III(self): self.assertEqual(self.ind("III. Finanzanlagen"), 2)
    def test_roman_IV(self):  self.assertEqual(self.ind("IV. Vorrate"), 2)
    def test_roman_V(self):   self.assertEqual(self.ind("V. Forderungen"), 2)
    def test_roman_IX(self):  self.assertEqual(self.ind("IX. Jahresueberschuss"), 2)

    # Level 3 - Arabic numbers 1. or lowercase a)
    def test_arabic_1(self):  self.assertEqual(self.ind("1. Grundstucke"), 3)
    def test_arabic_2(self):  self.assertEqual(self.ind("2. Technische Anlagen"), 3)
    def test_lower_a(self):   self.assertEqual(self.ind("a) Roh- und Hilfsstoffe"), 3)
    def test_lower_b(self):   self.assertEqual(self.ind("b) Fertige Erzeugnisse"), 3)

    # Level 4 - double-letter aa) or davon / darunter
    def test_aa(self):        self.assertEqual(self.ind("aa) davon Steuern"), 4)
    def test_bb(self):        self.assertEqual(self.ind("bb) sonstige"), 4)
    def test_davon(self):     self.assertEqual(self.ind("davon gegenuber Gesellschaftern"), 4)
    def test_darunter(self):  self.assertEqual(self.ind("darunter langfristig"), 4)


class TestAccountingBold(unittest.TestCase):
    """_acct_bold: which description rows get bold font in Excel."""

    @classmethod
    def setUpClass(cls):
        from ur_extractor import _acct_bold
        cls.bold = staticmethod(_acct_bold)

    # Must be bold
    def test_aktiva(self):        self.assertTrue(self.bold("Aktiva"))
    def test_passiva(self):       self.assertTrue(self.bold("Passiva"))
    def test_bilanzsumme(self):   self.assertTrue(self.bold("Bilanzsumme"))
    def test_summe_aktiva(self):  self.assertTrue(self.bold("Summe Aktiva"))
    def test_summe_passiva(self): self.assertTrue(self.bold("Summe Passiva"))
    def test_A(self):             self.assertTrue(self.bold("A. Anlagevermogen"))
    def test_B(self):             self.assertTrue(self.bold("B. Umlaufvermogen"))
    def test_C(self):             self.assertTrue(self.bold("C. Rechnungsabgrenzungsposten"))

    # Must NOT be bold - Roman numerals, Arabic, lowercase
    def test_roman_I(self):   self.assertFalse(self.bold("I. Immaterielle Vermoegensgegenstande"))
    def test_roman_II(self):  self.assertFalse(self.bold("II. Sachanlagen"))
    def test_roman_V(self):   self.assertFalse(self.bold("V. Forderungen"))
    def test_arabic_1(self):  self.assertFalse(self.bold("1. Grundstucke"))
    def test_lower_a(self):   self.assertFalse(self.bold("a) Roh- und Hilfsstoffe"))
    def test_aa(self):        self.assertFalse(self.bold("aa) davon"))
    def test_davon(self):     self.assertFalse(self.bold("davon gegenuber Gesellschaftern"))
    def test_plain(self):     self.assertFalse(self.bold("Jahresueberschuss"))


class TestFinancialContentFilter(unittest.TestCase):
    """_has_financial_content: reject text-only phantom tables, keep real financial tables."""

    @classmethod
    def setUpClass(cls):
        from ur_extractor import _has_financial_content
        cls.check = staticmethod(_has_financial_content)

    def _make(self, rows):
        return {"rows": rows}

    # ── text-only phantom tables (Aufsichtsratsbericht etc.) → must be False ─
    def test_prose_words_rejected(self):
        t = self._make([
            ["Beschreibung", "Spalte2", "Spalte3"],
            ["Jahresabschluss", "zum", "Geschaeftsjahr"],
            ["Bericht", "des", "Aufsichtsrats"],
            ["Der", "Aufsichtsrat", "hat"],
            ["Im", "Berichtszeitraum", "kam"],
            ["Die", "Zusammensetzung", "des"],
        ])
        self.assertFalse(self.check(t))

    def test_years_only_rejected(self):
        # stray years like "2024" must NOT count as financial numbers
        t = self._make([
            ["Beschreibung", "2024", "2025"],
            ["Jahresabschluss", "2024", "2025"],
            ["Lagebericht",    "2024", "2025"],
            ["Pruefung",       "2024", "2025"],
            ["Bericht",        "2024", "2025"],
            ["Erstellung",     "2024", "2025"],
        ])
        self.assertFalse(self.check(t))

    def test_list_numbers_rejected(self):
        # "1", "2", "3" as list items must not pass
        t = self._make([
            ["Thema",                  "Detail"],
            ["1. Jahresabschluss",     "Pruefung"],
            ["2. Geschaeftsordnung",   "Freigabe"],
            ["3. Strategie",           "Eroerterung"],
            ["4. Nachhaltigkeit",      "Bericht"],
            ["5. Weiteres",            "Sonstiges"],
        ])
        self.assertFalse(self.check(t))

    def test_dates_rejected(self):
        # "01.01.2025" has 2-digit groups (not 3), must not match German thousands
        t = self._make([
            ["Geschaeftsjahr", "von",        "bis"],
            ["FY2025",         "01.01.2025", "31.12.2025"],
            ["FY2024",         "01.01.2024", "31.12.2024"],
            ["FY2023",         "01.01.2023", "31.12.2023"],
            ["FY2022",         "01.01.2022", "31.12.2022"],
            ["FY2021",         "01.01.2021", "31.12.2021"],
        ])
        self.assertFalse(self.check(t))

    # ── real financial tables → must be True ─────────────────────────────────
    def test_bilanz_accepted(self):
        # real Bilanz column with German-formatted numbers
        t = self._make([
            ["Aktiva",                      "31.12.2024",  "31.12.2023"],
            ["A. Anlagevermogen",            "95.691,92",   "38.357,00"],
            ["I. Immaterielle",             "85.853,92",   "28.799,00"],
            ["II. Sachanlagen",              "9.838,00",    "9.558,00"],
            ["B. Umlaufvermogen",           "921.858,72",  "877.921,10"],
            ["I. Vorrate",                   "50.000,00",   "48.000,00"],
            ["II. Forderungen",             "871.858,72",  "829.921,10"],
            ["Summe Aktiva",               "1.028.718,63","929.907,77"],
        ])
        self.assertTrue(self.check(t))

    def test_guv_accepted(self):
        t = self._make([
            ["Ergebnisrechnung",            "2024",        "2023"],
            ["Umsatzerlose",               "5.234.567,00","4.891.234,00"],
            ["Materialaufwand",            "2.100.000,00","1.950.000,00"],
            ["Personalaufwand",            "1.500.000,00","1.400.000,00"],
            ["Abschreibungen",               "234.567,00",  "210.000,00"],
            ["Jahresueberschuss",            "400.000,00",  "331.234,00"],
        ])
        self.assertTrue(self.check(t))

    def test_with_zeros_accepted(self):
        # tables that include "0" entries must still pass
        t = self._make([
            ["Position",             "2024",      "2023"],
            ["Anlagevermogen",      "1.234,56",  "1.100,00"],
            ["Umlaufvermogen",      "5.678,90",  "5.000,00"],
            ["Verbindlichkeiten",   "2.345,67",  "2.000,00"],
            ["Rueckstellungen",     "0",         "0"],
            ["Bilanzsumme",        "10.000,00",  "9.500,00"],
        ])
        self.assertTrue(self.check(t))


# ============================================================================
# Test runner - coloured per-test output, clean summary
# ============================================================================

def _run_class(cls) -> tuple[int, int]:
    """Run one TestCase class; return (passed, failed)."""
    print(bold(f"  {cls.__name__}"))

    # setUpClass must be called manually when we iterate tests individually
    # (TestSuite.run() normally handles this, but we bypass it for per-test output)
    try:
        cls.setUpClass()
    except Exception as exc:
        print(f"    {red('ERR')}  setUpClass: {exc}")
        return 0, 1

    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromTestCase(cls)
    passed = failed = 0

    for test in suite:
        name = test._testMethodName
        # setUpClass was called when we loaded the suite; run individual test
        try:
            test.debug()
            print(f"    {green('PASS')}  {name}")
            passed += 1
        except AssertionError as exc:
            short = str(exc).splitlines()[0][:120]
            print(f"    {red('FAIL')}  {name}")
            print(f"          {red(short)}")
            failed += 1
        except Exception as exc:
            print(f"    {red('ERR ')}  {name}  {red(str(exc)[:120])}")
            failed += 1

    n = passed + failed
    status = green(f"{passed}/{n} passed") if failed == 0 else red(f"{failed}/{n} failed")
    print(f"  {status}\n")
    return passed, failed


def run_unit_tests() -> bool:
    classes = [TestNumberParsing, TestAccountingIndent, TestAccountingBold, TestFinancialContentFilter]
    total_n = sum(
        unittest.TestLoader().loadTestsFromTestCase(c).countTestCases()
        for c in classes
    )

    print(bold(f"\n{'='*54}"))
    print(bold(f"  UR Extractor  unit tests  ({total_n} cases)"))
    print(bold(f"{'='*54}\n"))

    tp = tf = 0
    for cls in classes:
        p, f = _run_class(cls)
        tp += p; tf += f

    print(bold(f"{'='*54}"))
    if tf == 0:
        print(bold(green(f"  ALL {tp}/{tp+tf} TESTS PASSED")))
    else:
        print(bold(red(f"  {tf}/{tp+tf} TESTS FAILED")))
    print(bold(f"{'='*54}\n"))
    return tf == 0


# ============================================================================
# Command: gui - launch the GUI directly (no build needed)
# ============================================================================

def cmd_gui():
    print(cyan("Launching GUI (ur_gui.py)...  close the window to exit.\n"))
    import ur_gui
    ur_gui.main()


# ============================================================================
# Command: pdf - extract tables from a local PDF and print them
# ============================================================================

def cmd_pdf(pdf_path: str):
    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        print(red(f"File not found: {path}"))
        sys.exit(1)

    print(cyan(f"\nExtracting tables from: {path.name}\n"))
    from ur_extractor import extract_tables_from_pdf
    tables = extract_tables_from_pdf(path)

    if not tables:
        print(yellow("No tables found in this PDF."))
        return

    print(bold(f"Found {len(tables)} table(s):\n"))
    for t in tables:
        idx     = t.get("index", "?")
        heading = t.get("heading") or "(no heading)"
        rows    = t.get("rows", [])
        cols    = t.get("col_count", 0)
        p_start = t.get("page_start", "?")
        p_end   = t.get("page_end",   "?")
        print(bold(f"  [{idx}] {heading}"))
        print(dim(f"      {len(rows)} rows x {cols} cols  |  pages {p_start}-{p_end}"))

        # First 6 rows as a quick preview
        for ri, row in enumerate(rows[:6]):
            cells = "  |  ".join(str(c or "")[:24].ljust(24) for c in row[:4])
            print(dim(f"      | {cells}"))
        if len(rows) > 6:
            print(dim(f"      | ... ({len(rows) - 6} more rows)"))
        print()


# ============================================================================
# Command: excel - export a local PDF to Excel and open it
# ============================================================================

def cmd_excel(pdf_path: str):
    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        print(red(f"File not found: {path}"))
        sys.exit(1)

    print(cyan(f"\nExporting to Excel from: {path.name}\n"))
    from ur_extractor import extract_tables_from_pdf, export_to_excel

    tables = extract_tables_from_pdf(path)
    if not tables:
        print(yellow("No tables found - nothing to export."))
        return

    # Build a minimal result dict from the filename
    stem  = path.stem                          # e.g. "CTEC_Jahresabschluss_2024"
    parts = stem.split("_")
    result = {
        "company":  parts[0] if parts else stem,
        "doc_type": parts[1] if len(parts) > 1 else "Abschluss",
        "fy":       parts[-1] if parts else "2024",
    }

    out_path = path.with_suffix(".xlsx")
    export_to_excel(tables, result, out_path)
    print(green(f"\nExcel written to: {out_path}"))

    try:
        os.startfile(str(out_path))
    except Exception:
        print(dim(f"(Could not auto-open - open manually: {out_path})"))


# ============================================================================
# Command: search - full browser flow, interactive, verbose logging
# ============================================================================

def cmd_search(company: str):
    """Open a real browser, search for company, and walk through the download
    flow.  Tests Playwright selectors without needing to build an exe."""

    async def _run():
        from playwright.async_api import async_playwright
        from ur_extractor import launch_browser, run_search, open_document, download_pdf

        pdf_dir = Path(tempfile.mkdtemp(prefix="ur_test_"))
        print(cyan(f"\nBrowser test - searching for: {company!r}"))
        print(dim(f"PDFs will be saved to: {pdf_dir}\n"))

        async with async_playwright() as pw:
            browser, context, page = await launch_browser(pw, interactive=True)
            results = await run_search(page, company, interactive=True)

            if not results:
                print(yellow("No results found."))
                await browser.close()
                return

            print(bold(f"\n{len(results)} result(s) found:\n"))
            for i, r in enumerate(results):
                fy      = r.get("fy", "?")
                filed   = r.get("date_filed", "?")
                doc_t   = r.get("doc_type", "")
                company_ = r.get("company", "")
                print(f"  [{i}] {company_}  |  {doc_t}  |  FY {fy}  |  Filed {filed}")

            while True:
                raw = input(f"\nPick result [0-{len(results)-1}] (or q to quit): ").strip()
                if raw.lower() == "q":
                    break
                if raw.isdigit() and 0 <= int(raw) < len(results):
                    chosen = results[int(raw)]
                    ok = await open_document(page, chosen, interactive=True)
                    if ok:
                        saved = await download_pdf(
                            page, chosen, interactive=True, pdf_dir=pdf_dir
                        )
                        if saved:
                            print(green(f"\nDownloaded: {saved}"))
                        else:
                            print(red("\nDownload failed."))
                    break
                print(yellow("Invalid choice."))

            await browser.close()

    asyncio.run(_run())


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="python dev_test.py",
        description="Pre-bake dev test harness for UR Financial Extractor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("gui",    help="Launch the full GUI (no build needed)")

    p_search = sub.add_parser("search", help="Browser search + download test")
    p_search.add_argument("company", help='Company name, e.g. "CTEC I GmbH"')

    p_pdf = sub.add_parser("pdf",   help="Extract tables from a local PDF and print")
    p_pdf.add_argument("file", help="Path to the PDF file")

    p_xl = sub.add_parser("excel", help="Export a local PDF to Excel and open it")
    p_xl.add_argument("file", help="Path to the PDF file")

    args = parser.parse_args()

    if args.cmd == "gui":
        cmd_gui()
    elif args.cmd == "pdf":
        cmd_pdf(args.file)
    elif args.cmd == "excel":
        cmd_excel(args.file)
    elif args.cmd == "search":
        cmd_search(args.company)
    else:
        # No subcommand -> run unit tests
        passed = run_unit_tests()
        sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
