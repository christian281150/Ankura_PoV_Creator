"""Register acquisition: Playwright session, search, document open/download,
Windows browser-window management, and the interactive-CLI helpers."""

import re
import sys
from pathlib import Path
from typing import Optional
from playwright.async_api import TimeoutError as PlaywrightTimeout
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from config import (
    BASE_URL, PAGE_LOAD_TIMEOUT, SEARCH_TIMEOUT,
    CAPTCHA_TIMEOUT, DOWNLOAD_TIMEOUT, CLICK_TIMEOUT,
)

from ._core import console, sanitize_filename


def parse_fy(date_range: str) -> str:
    """
    Extract FY label from a date-range string.
    '01.01.2024–31.12.2024' → 'FY2024'
    '01.03.2024–28.02.2025' → 'FY2024'  (use START year)
    Falls back to the raw string if parsing fails.
    """
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_range)
    if match:
        return f"FY{match.group(3)}"
    return f"FY_{sanitize_filename(date_range)}"


def detect_doc_type(text: str) -> str:
    """Return 'Jahresabschluss', 'Konzernabschluss', or 'Both'."""
    has_j = "jahresabschluss" in text.lower()
    has_k = "konzernabschluss" in text.lower()
    if has_j and has_k:
        return "Both"
    if has_k:
        return "Konzernabschluss"
    return "Jahresabschluss"


def ask_retry(prompt_text: str) -> bool:
    """Ask a y/n retry question; return True if user says yes."""
    answer = Prompt.ask(prompt_text, choices=["y", "n"], default="n")
    return answer.lower() == "y"


def _alt_tab() -> None:
    """
    Simulate one Alt+Tab keystroke via the Windows API.
    First call: current window → browser (browser gets OS focus).
    Second call: browser → previous window (restores prior focus).
    Safe no-op on non-Windows platforms.
    """
    try:
        import ctypes
        u = ctypes.windll.user32
        VK_MENU, VK_TAB, KEY_UP = 0x12, 0x09, 0x0002
        u.keybd_event(VK_MENU, 0, 0,       0)   # Alt ↓
        u.keybd_event(VK_TAB,  0, 0,       0)   # Tab ↓
        u.keybd_event(VK_TAB,  0, KEY_UP,  0)   # Tab ↑
        u.keybd_event(VK_MENU, 0, KEY_UP,  0)   # Alt ↑
    except Exception:
        pass


def _get_browser_hwnds() -> set:
    """
    Snapshot every Chrome_WidgetWin_1 HWND that exists RIGHT NOW.
    Call this before launching Playwright to record the user's own
    Edge/Chrome windows so they are never touched by our hide logic.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnds  = set()
        PROC   = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def _cb(h, _):
            """EnumWindows callback: collect HWNDs of Chromium top-level windows."""
            b = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, b, 256)
            if b.value == "Chrome_WidgetWin_1":
                hwnds.add(h)
            return True
        user32.EnumWindows(PROC(_cb), 0)
        return hwnds
    except Exception:
        return set()


def _minimize_all_browsers(exclude_hwnds: set = None) -> None:
    """
    Minimise every Chromium browser window EXCEPT those in exclude_hwnds.
    exclude_hwnds should be the snapshot from _get_browser_hwnds() taken
    before Playwright launched, so the user's own windows are preserved.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        skip   = exclude_hwnds or set()
        PROC   = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def _cb(h, _):
            """EnumWindows callback: hide Chromium windows except the caller's own."""
            if h in skip:
                return True
            b = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, b, 256)
            if b.value == "Chrome_WidgetWin_1":
                ctypes.windll.user32.ShowWindow(h, 6)   # SW_MINIMIZE
            return True
        user32.EnumWindows(PROC(_cb), 0)
    except Exception:
        pass


def _hide_from_taskbar(exclude_hwnds: set = None) -> None:
    """
    Remove Playwright browser windows from the Windows taskbar.

    Only windows NOT present in exclude_hwnds are touched.
    Pass the result of _get_browser_hwnds() (captured before launch) to
    preserve the user's existing Edge/Chrome windows.

    Technique: WS_EX_TOOLWINDOW removes the window from the taskbar;
    hiding and re-showing forces Windows to re-evaluate the taskbar entry.
    """
    try:
        import ctypes
        user32           = ctypes.windll.user32
        GWL_EXSTYLE      = -20
        WS_EX_APPWINDOW  = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        skip             = exclude_hwnds or set()
        PROC             = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

        def _cb(h, _):
            """EnumWindows callback: minimise Chromium windows, leaving the user's untouched."""
            if h in skip:                       # <- preserve user's windows
                return True
            b = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, b, 256)
            if b.value == "Chrome_WidgetWin_1":
                user32.ShowWindow(h, 0)         # SW_HIDE  — flush taskbar
                ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
                ex = (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
                user32.SetWindowLongW(h, GWL_EXSTYLE, ex)
                user32.ShowWindow(h, 6)         # SW_MINIMIZE — re-show hidden
            return True

        user32.EnumWindows(PROC(_cb), 0)
    except Exception:
        pass


def _hide_hwnds(hwnds: set) -> None:
    """
    Hide a SPECIFIC set of browser window handles from the taskbar.
    Called with exactly the HWNDs Playwright created (after - before snapshot),
    so the user's existing Edge/Chrome windows are never affected.
    """
    try:
        import ctypes
        user32           = ctypes.windll.user32
        GWL_EXSTYLE      = -20
        WS_EX_APPWINDOW  = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        for h in hwnds:
            user32.ShowWindow(h, 0)                         # SW_HIDE
            ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
            ex = (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
            user32.SetWindowLongW(h, GWL_EXSTYLE, ex)
            user32.ShowWindow(h, 6)                         # SW_MINIMIZE
    except Exception:
        pass


def _minimize_hwnds(hwnds: set) -> None:
    """Minimise a specific set of window handles (no taskbar change)."""
    try:
        import ctypes
        for h in hwnds:
            ctypes.windll.user32.ShowWindow(h, 6)           # SW_MINIMIZE
    except Exception:
        pass


def _minimize_browser() -> None:
    """Minimize the topmost Chromium browser window on Windows."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW("Chrome_WidgetWin_1", None)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)   # SW_MINIMIZE
    except Exception:
        pass


def prompt_company_name() -> str:
    """
    Prompt for a company name with validation.
    Allows up to 5 attempts before exiting.
    Returns the validated name, or raises SystemExit.
    """
    for attempt in range(1, 6):
        raw = Prompt.ask("\n[bold]Enter company name[/bold] (or 'quit' to exit)")
        if raw.strip().lower() == "quit":
            console.print("Goodbye.")
            sys.exit(0)
        if len(raw.strip()) >= 2:
            return raw.strip()
        console.print(f"[yellow]Name too short. Please enter a valid company name. "
                      f"({attempt}/5 attempts)[/yellow]")
    console.print("[red]Too many invalid attempts. Exiting.[/red]")
    sys.exit(1)


async def launch_browser(playwright, interactive: bool = True):
    """
    Launch a headed browser and navigate to BASE_URL.

    Tries Microsoft Edge first (always present on Windows 10/11), then Chrome,
    then falls back to Playwright's own bundled Chromium.
    Launches off-screen (--window-position=9999,9999) so the window never
    flashes in front of the user before _wait_and_minimize() hides it.

    Args
    ----
    playwright   : Playwright context (from async_playwright().__aenter__).
    interactive  : When False (GUI mode) all ask_retry() prompts are skipped
                   and the function auto-retries instead of waiting for input.

    Returns
    -------
    (browser, context, page)
    """
    launch_error = None
    browser      = None
    # Try system-installed browsers only (no bundled Chromium fallback).
    # Microsoft Edge is always present on Windows 10/11; Chrome is a bonus.
    # Falling back to channel=None would require a separately installed
    # Playwright-managed Chromium (not bundled in the exe) and would fail.
    for channel in ("msedge", "chrome"):
        try:
            browser = await playwright.chromium.launch(
                channel=channel,
                headless=False,
                args=["--window-position=9999,9999"],
            )
            break
        except Exception as exc:
            launch_error = exc
            continue

    if browser is None:
        msg = (
            "Could not launch Microsoft Edge or Google Chrome.\n\n"
            "Please make sure Microsoft Edge is installed and up to date\n"
            "(it comes pre-installed on Windows 10 / 11).\n\n"
            f"Technical detail: {launch_error}"
        )
        console.print(f"[red]{msg}[/red]")
        # Show a GUI message box if tkinter is available (frozen exe mode)
        try:
            import tkinter.messagebox as _mb
            _mb.showerror("Browser not found", msg)
        except Exception:
            pass
        sys.exit(1)

    # Fixed viewport so element coordinates are reproducible across sessions.
    context = await browser.new_context(
        accept_downloads=True,
        viewport={"width": 1280, "height": 900},
    )
    page = await context.new_page()

    for attempt in range(1, 4):
        try:
            console.print(
                f"[cyan]Navigating to {BASE_URL} (attempt {attempt}/3)\u2026[/cyan]")
            await page.goto(BASE_URL, timeout=PAGE_LOAD_TIMEOUT)
            await page.wait_for_load_state("domcontentloaded",
                                           timeout=PAGE_LOAD_TIMEOUT)
            console.print("[green]Homepage loaded.[/green]")
            return browser, context, page
        except PlaywrightTimeout:
            console.print(
                "[red]Cannot reach unternehmensregister.de. "
                "Check your connection.[/red]")
            should_retry = ask_retry("Retry?") if interactive else True
            if attempt < 3 and should_retry:
                continue
            else:
                await browser.close()
                if interactive:
                    console.print("Exiting.")
                sys.exit(0)


def prompt_company_name() -> str:
    """
    Prompt for a company name (CLI mode only).
    Allows up to 5 attempts before exiting.
    """
    for attempt in range(1, 6):
        raw = Prompt.ask("\n[bold]Enter company name[/bold] (or 'quit' to exit)")
        if raw.strip().lower() == "quit":
            console.print("Goodbye.")
            sys.exit(0)
        if len(raw.strip()) >= 2:
            return raw.strip()
        console.print(
            f"[yellow]Name too short. Please enter a valid company name. "
            f"({attempt}/5 attempts)[/yellow]")
    console.print("[red]Too many invalid attempts. Exiting.[/red]")
    sys.exit(1)


async def run_search(page, company_name: str, interactive: bool = True) -> Optional[list[dict]]:
    """
    Type company_name into the Schnellsuche field and submit.
    Returns a list of result dicts with keys:
        company, doc_type, fy, date_filed, element (the clickable link)
    Returns None to signal 'go back to name prompt'.
    """
    # --- Submit the search ---
    for attempt in range(1, 3):
        try:
            # Accept cookie banner if present
            try:
                cookie_btn = page.locator("button:has-text('Alle akzeptieren'), "
                                          "button:has-text('Akzeptieren'), "
                                          "#accept-all-cookies")
                await cookie_btn.first.click(timeout=3_000)
            except Exception:
                pass  # No banner or already dismissed

            # "Firmenname / EUID" input — id confirmed as quick_search:company_search_term
            search_input = page.locator(
                "input[name='companySearchTerm'], "
                "#quick_search\\:company_search_term, "
                "input[id*='company_search_term'], "
                "input[id*='firmenName'], "
                "input[type='text']"
            ).first
            await search_input.click(timeout=5_000)
            await search_input.fill(company_name, timeout=5_000)

            # Click the primary "Suchen" submit button
            suchen_btn = page.locator(
                "button[class*='buttonPrimary'], "
                "button[type='submit'][class*='button']"
            ).first
            await suchen_btn.click(timeout=5_000)
            console.print(f"[cyan]Searching for '{company_name}'…[/cyan]")
            break
        except PlaywrightTimeout:
            console.print("[red]Search timed out. The site may be slow.[/red]")
            if attempt < 2 and (ask_retry("Retry search?") if interactive else True):
                continue
            else:
                return None   # back to name prompt

    # --- Wait for results to render (SPA: wait for result rows, not networkidle) ---
    try:
        await page.wait_for_selector(
            "table tr td, "
            "[class*='result'] tr, "
            "[class*='Result'] tr, "
            "[class*='searchResult'], "
            "[class*='tableRow'], "
            "tbody tr",
            timeout=SEARCH_TIMEOUT,
        )
    except PlaywrightTimeout:
        console.print("[red]Search timed out waiting for results.[/red]")
        if ask_retry("Retry search?") if interactive else False:
            return None
        return None

    # --- Filter to "Veröffentlichungen" section if available ----------------
    # Large companies show an aggregated overview page with many categories.
    # Clicking the "Veröffentlichungen" chip filters to the publications that
    # contain Jahresabschluss / Konzernabschluss filings.
    try:
        veroeff = page.locator(
            "a:has-text('Veröffentlichungen'), "
            "button:has-text('Veröffentlichungen')"
        )
        if await veroeff.count() > 0:
            await veroeff.first.click(timeout=4_000)
            await page.wait_for_load_state("domcontentloaded", timeout=8_000)
            await page.wait_for_selector("tbody tr", timeout=8_000)
            console.print("[cyan]Filtered to Veröffentlichungen.[/cyan]")
    except Exception:
        pass  # filter chip not present — results page already shows filings

    # --- Scrape result rows ---
    results = await _parse_result_rows(page)

    # Handle zero total results
    if results is None:
        console.print(f"[red]No results found for '{company_name}'.[/red]")
        console.print("[dim]Tip: Try a shorter name, check spelling, or include the legal "
                      "entity suffix (GmbH, AG, etc.)[/dim]")
        return None

    # Handle results found but no financial filings
    if len(results) == 0:
        console.print("[yellow]Company found but no financial filings available.[/yellow]")
        console.print("[dim]This may mean: filings are pending, company is exempt "
                      "(small company §264 HGB), or filed under a different entity name.[/dim]")
        return None

    return results


async def _parse_result_rows(page) -> Optional[list[dict]]:
    """
    Parse the search-results page.
    Returns None  → no results at all (company not found)
    Returns []    → results exist but none are Rechnungslegung
    Returns [...]  → matching financial filing rows
    """
    # Wait for result rows or a "no results" message
    try:
        await page.wait_for_selector(
            "table tr td, tbody tr, "
            "[class*='result'] tr, [class*='Result'] tr, "
            "[class*='searchResult'], [class*='tableRow'], "
            "[class*='noResult'], [class*='emptyState']",
            timeout=SEARCH_TIMEOUT,
        )
    except PlaywrightTimeout:
        body_text = (await page.inner_text("body")).lower()
        if any(kw in body_text for kw in ["keine ergebnisse", "keine treffer", "kein ergebnis"]):
            return None
        return None

    # Collect all rows from result tables, capturing each row's first link href
    rows_data = await page.evaluate("""
        () => {
            const rows = [];
            const tableRows = document.querySelectorAll(
                'table tr, .ergebnisListe tr, .result-table tr'
            );
            tableRows.forEach(tr => {
                const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                if (cells.length > 0) {
                    const link = tr.querySelector('a');
                    rows.push({
                        cells: cells,
                        linkHref: link ? link.getAttribute('href') : null,
                        linkText: link ? link.innerText.trim() : null
                    });
                }
            });
            return rows;
        }
    """)

    if not rows_data:
        return None  # truly no results

    # Filter to Rechnungslegung / Finanzberichte rows
    results = []
    for row in rows_data:
        cells_text = " ".join(row["cells"]).lower()

        # Skip amendment entries ("Ergänzung der Veröffentlichung vom …").
        # When a filing is amended the register creates two rows:
        #   Original  → "Ergänzt am <date>"          ← we WANT this one
        #   Amendment → "Ergänzung der Veröffentlichung vom <date>"  ← skip
        # Taking the original (earliest publication) gives the base annual report.
        if "ergänzung der veröffentlichung" in cells_text:
            console.print("[dim]Skipping amendment row (Ergänzung der Veröffentlichung).[/dim]")
            continue

        # Must contain financial report keywords.
        # Use prefix "jahresabschl" / "konzernabschl" to match both the singular
        # ("Jahresabschluss") and plural ("Jahresabschlüsse") — the ü makes a
        # direct substring check on the full word fail for the plural form.
        if not any(kw in cells_text for kw in [
                "rechnungslegung", "finanzberichte",
                "jahresabschl",    # covers singular + plural
                "konzernabschl",   # covers singular + plural
                "hinterlegte",     # "Hinterlegte Jahresabschlüsse" overview rows
        ]):
            continue

        # --- Extract fields ---
        cells = row["cells"]
        full_text = " ".join(cells)

        # Company name: usually first or second cell
        company = cells[0] if cells else "Unknown"

        # Doc type
        doc_type = detect_doc_type(full_text)

        # Financial year: grab the LAST year from "bis zum 31.12.YYYY" if present,
        # otherwise fall back to the first year found.  This correctly identifies
        # "FY2024" from "01.01.2024 bis zum 31.12.2024" even when "Ergänzt am
        # 27.03.2026" adds a later year at the end of the row text.
        bis_match = re.search(r"bis\s+zum\s+\d{2}\.\d{2}\.(\d{4})", full_text, re.IGNORECASE)
        if bis_match:
            fy = f"FY{bis_match.group(1)}"
        else:
            fy_match = re.search(r"\d{2}\.\d{2}\.(\d{4})", full_text)
            fy = f"FY{fy_match.group(1)}" if fy_match else "FY_unknown"

        # Date filed: the date immediately after "Datum:" if present, otherwise
        # the last dd.mm.yyyy found in the row.
        datum_match = re.search(r"Datum[:\s]+(\d{2}\.\d{2}\.\d{4})", full_text, re.IGNORECASE)
        if datum_match:
            date_filed = datum_match.group(1)
        else:
            date_match = re.findall(r"\d{2}\.\d{2}\.\d{4}", full_text)
            date_filed = date_match[-1] if date_match else "—"

        results.append({
            "company":    company,
            "doc_type":   doc_type,
            "fy":         fy,
            "date_filed": date_filed,
            "link_href":  row.get("linkHref"),
            "link_text":  row.get("linkText"),
        })

    return results


def display_results(results: list[dict]) -> None:
    """Render a numbered Rich table of matching filing rows."""
    tbl = Table(title="Financial Filings Found", show_header=True, header_style="bold cyan")
    tbl.add_column("#",          style="bold", width=4)
    tbl.add_column("Company",    min_width=25)
    tbl.add_column("Doc Type",   min_width=18)
    tbl.add_column("FY",         width=8)
    tbl.add_column("Date Filed", width=12)

    for i, r in enumerate(results, 1):
        tbl.add_row(
            str(i),
            r["company"],
            r["doc_type"],
            r["fy"],
            r["date_filed"],
        )
    console.print(tbl)


async def select_document(page, results: list[dict]) -> Optional[dict]:
    """
    Prompt user to pick a result row.
    Returns the selected result dict, or None to go back.
    Raises SystemExit on 'quit'.
    """
    n = len(results)
    for attempt in range(1, 4):
        raw = Prompt.ask(
            f"\n[bold]Select document number[/bold] "
            f"(1–{n}, 'back' to search again, 'quit' to exit)"
        )
        token = raw.strip().lower()
        if token == "quit":
            console.print("Goodbye.")
            sys.exit(0)
        if token == "back":
            return None
        try:
            idx = int(token)
            if 1 <= idx <= n:
                return results[idx - 1]
            console.print(f"[yellow]Invalid selection. Enter a number between 1 and {n}.[/yellow]")
        except ValueError:
            console.print(f"[yellow]Invalid selection. Enter a number between 1 and {n}.[/yellow]")

    console.print("[red]Too many invalid attempts. Returning to search.[/red]")
    return None


async def open_document(page, result: dict, confirm_func=None, interactive: bool = True) -> bool:
    """
    Click the link for the selected result row and wait through CAPTCHA.
    Returns True if document loaded successfully, False to go back to selection.
    """
    # --- Click the document chevron link on the results page ---
    for attempt in range(1, 3):
        try:
            href      = result.get("link_href")
            link_text = result.get("link_text", "")
            clicked   = False

            # Strategy 1: click by exact href attribute — avoids any URL construction
            if href:
                loc = page.locator(f'a[href="{href}"]')
                if await loc.count() > 0:
                    await loc.first.click(timeout=CLICK_TIMEOUT)
                    clicked = True

            # Strategy 2: click by link text fragment
            if not clicked and link_text:
                try:
                    await page.get_by_text(link_text[:40], exact=False).first.click(
                        timeout=CLICK_TIMEOUT
                    )
                    clicked = True
                except Exception:
                    pass

            # Strategy 3: first link in any result row that mentions a filing keyword
            if not clicked:
                links = page.locator("table tr a, tbody tr a")
                count = await links.count()
                for li in range(count):
                    txt = (await links.nth(li).inner_text()).lower()
                    if any(kw in txt for kw in ("abschluss", "rechnungslegung", "§§ 264")):
                        await links.nth(li).click(timeout=CLICK_TIMEOUT)
                        clicked = True
                        break

            if not clicked:
                raise Exception("Could not locate document link on page.")
            break

        except PlaywrightTimeout:
            console.print("[red]Document page failed to load.[/red]")
            if attempt < 2 and (ask_retry("Retry?") if interactive else True):
                continue
            return False
        except Exception as exc:
            console.print(f"[red]Could not click document link: {exc}[/red]")
            if attempt < 2 and (ask_retry("Retry?") if interactive else True):
                continue
            return False

    # --- Wait for the Sicherheitsabfrage page to load ---
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    except PlaywrightTimeout:
        console.print("[red]Document page failed to load after click.[/red]")
        if ask_retry("Retry?") if interactive else False:
            return await open_document(page, result, confirm_func=confirm_func, interactive=interactive)
        return False

    # --- Auto-click "Ich bin ein Mensch" checkbox ---
    console.print("[cyan]Looking for 'Ich bin ein Mensch' checkbox…[/cyan]")
    await page.wait_for_timeout(1_500)   # let JS finish rendering
    checkbox_clicked = False

    # Strategy 1: click the <label> that wraps "Ich bin ein Mensch".
    # Clicking a label toggles its associated input — robust even with custom-styled checkboxes.
    try:
        label_loc = page.locator("label").filter(has_text="Ich bin ein Mensch")
        if await label_loc.count() > 0:
            await label_loc.first.click(force=True, timeout=5_000)
            checkbox_clicked = True
            console.print("[green]Checkbox label clicked.[/green]")
    except Exception:
        pass

    # Strategy 2: get bounding box of the "Ich bin ein Mensch" text and click the
    # left edge — the checkbox square sits just to the left of (or at the start of)
    # the label text.
    if not checkbox_clicked:
        try:
            txt_loc = page.get_by_text("Ich bin ein Mensch", exact=False)
            if await txt_loc.count() > 0:
                bb = await txt_loc.first.bounding_box()
                if bb:
                    # x = left edge of the bounding box + 15 px lands in the checkbox square
                    await page.mouse.click(bb["x"] + 15, bb["y"] + bb["height"] / 2)
                    checkbox_clicked = True
                    console.print("[green]Checkbox clicked via 'Ich bin ein Mensch' text anchor.[/green]")
        except Exception:
            pass

    # Strategy 3: find the "Sicherheitsabfrage" section header and move down ~85 px —
    # that is the fixed vertical distance to the checkbox row regardless of whether
    # the "Suchoptionen" form above is expanded or collapsed.
    if not checkbox_clicked:
        try:
            hdr_loc = page.get_by_text("Sicherheitsabfrage", exact=False)
            if await hdr_loc.count() > 0:
                bb = await hdr_loc.first.bounding_box()
                if bb:
                    await page.mouse.click(bb["x"] + 25, bb["y"] + 85)
                    checkbox_clicked = True
                    console.print("[green]Checkbox clicked via 'Sicherheitsabfrage' header offset.[/green]")
        except Exception:
            pass

    if not checkbox_clicked:
        console.print("[yellow]Could not auto-click checkbox — please click it manually.[/yellow]")

    # --- If auto-click succeeded: flash browser to front for 2 s then minimize ---
    if checkbox_clicked:
        _alt_tab()                        # bring browser to OS foreground
        await page.wait_for_timeout(500)  # let OS finish switch
        console.print("[cyan]Waiting 2 s for CAPTCHA to verify…[/cyan]")
        await page.wait_for_timeout(2_000)
        _alt_tab()                        # back to previous window
        _minimize_browser()               # hide browser — document loads in background
        console.print("[cyan]Waiting for document to load…[/cyan]")
        await page.wait_for_timeout(8_000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except PlaywrightTimeout:
            pass

        # URL-based check (most reliable)
        if any(kw in page.url for kw in ("veroeffentlichung", "publication", "payload=")):
            console.print("[green]Document loaded automatically after CAPTCHA.[/green]")
            return True

        # Also look for the PDF download button as confirmation
        try:
            await page.wait_for_selector(
                "xpath=/html/body/div[2]/main/div/div/div/section"
                "/div/div/div[2]/div/div/button[2], "
                "button[title*='herunterladen'], button[title*='PDF']",
                timeout=3_000,
            )
            console.print("[green]Document loaded automatically after CAPTCHA.[/green]")
            return True
        except PlaywrightTimeout:
            pass

        console.print("[yellow]Auto-click may not have resolved the CAPTCHA yet.[/yellow]")

    # --- Manual fallback: prompt only when auto-click failed or document not yet visible ---
    if confirm_func:
        await confirm_func()
    else:
        console.print(Panel(
            "[bold yellow]>>> ACTION REQUIRED <<<[/bold yellow]\n"
            "Check the [bold]'Ich bin ein Mensch'[/bold] box in the browser if not already checked.\n"
            "Then press [bold]ENTER[/bold] here to continue.",
            title="Human Verification",
            border_style="yellow",
            expand=False,
        ))
        input()

    # --- Detect document page loaded after manual confirmation ---
    console.print("[cyan]Waiting for document to render…[/cyan]")
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=CAPTCHA_TIMEOUT)
    except PlaywrightTimeout:
        pass

    if any(kw in page.url for kw in ("veroeffentlichung", "publication", "payload=")):
        console.print("[green]Document loaded successfully.[/green]")
        return True

    try:
        await page.wait_for_selector(
            "th:has-text('Firma'), th:has-text('Bezeichnung'), "
            "button:has-text('Zurück'), td:has-text('Konzernabschluss'), "
            "td:has-text('Jahresabschluss'), td:has-text('Rechnungslegung')",
            timeout=10_000,
        )
        console.print("[green]Document loaded successfully.[/green]")
        return True
    except PlaywrightTimeout:
        pass

    console.print("[red]Document did not load after verification.[/red]")
    return False


async def download_pdf(page, result: dict, captcha_cb=None,
                       interactive: bool = True,
                       pdf_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Click the PDF download button and save the file.

    Args:
        page:         Playwright page object (must be on the document view page).
        result:       Dict with keys company, doc_type, fy (from _parse_result_rows).
        captcha_cb:   Optional async callable invoked instead of input() for CAPTCHA
                      confirmation (GUI mode).
        interactive:  When False, all ask_retry() prompts are skipped (GUI mode).
        pdf_dir:      Directory in which to save the PDF.  Defaults to cwd().

    Returns:
        Path to the saved PDF on success, None on failure.
    """
    company   = sanitize_filename(result["company"])
    doc_type  = sanitize_filename(result["doc_type"])
    fy        = result["fy"]
    filename  = f"{company}_{doc_type}_{fy}.pdf"
    base_dir  = pdf_dir or Path.cwd()
    base_dir.mkdir(parents=True, exist_ok=True)
    out_path  = base_dir / filename

    async def _find_dl_link_in(ctx):
        """
        Try every known selector pattern inside *ctx* (a Page or FrameLocator).
        Returns the first matching locator, or None.
        """
        # Primary: title contains "PDF" — works in ALL languages because the site
        # translates the tooltip (German: "Als PDF herunterladen", English: "Download as PDF",
        # French: "Télécharger en PDF", Italian: "Scarica come PDF", Spanish: "Descargar como PDF")
        # but every variant contains the word "PDF".
        loc = ctx.locator("button[title*='PDF'], a[title*='PDF']")
        if await loc.count() > 0:
            return loc.first

        # aria-label fallback (same reason — "PDF" appears in every language)
        loc = ctx.locator("button[aria-label*='PDF'], a[aria-label*='PDF']")
        if await loc.count() > 0:
            return loc.first

        # Absolute XPath for the live site layout (last-resort — breaks if site updates)
        try:
            loc = ctx.locator(
                "xpath=/html/body/div[2]/main/div/div/div/section/div/div/div[2]/div/div/button[2]"
            )
            if await loc.count() > 0:
                return loc.first
        except Exception:
            pass

        # Direct PDF href
        loc = ctx.locator("a[href$='.pdf'], a[href*='.pdf?']")
        if await loc.count() > 0:
            return loc.first

        return None

    async def _try_download() -> Optional[Path]:
        """
        Locate the PDF button and trigger the download.
        Searches the main page first, then any iframes (Bundesanzeiger embeds the
        document viewer in an iframe for some filing types).
        Returns the saved Path, or None if no button was found.
        """
        # --- Search main page ---
        dl_link = await _find_dl_link_in(page)

        # --- Search iframes when not found on main page ---
        if dl_link is None:
            frames = page.frames
            console.print(f"[dim]Checking {len(frames)} frame(s) for PDF button…[/dim]")
            for frame in frames:
                if frame == page.main_frame:
                    continue
                try:
                    frame_loc = await _find_dl_link_in(frame)
                    if frame_loc is not None:
                        dl_link = frame_loc
                        console.print(f"[dim]PDF button found in iframe: {frame.url}[/dim]")
                        break
                except Exception:
                    pass

        if dl_link is None:
            # Emit a diagnostic so the debug log shows what buttons ARE on the page
            try:
                all_btns = page.locator("button, a[href]")
                count = await all_btns.count()
                samples = []
                for i in range(min(count, 20)):
                    try:
                        btn = all_btns.nth(i)
                        txt  = (await btn.inner_text()).strip()[:60]
                        title = (await btn.get_attribute("title") or "")[:60]
                        href  = (await btn.get_attribute("href")  or "")[:80]
                        samples.append(f"  [{i}] txt={txt!r} title={title!r} href={href!r}")
                    except Exception:
                        pass
                console.print(f"[yellow]Page URL: {page.url}[/yellow]")
                console.print(f"[yellow]Buttons/links on page ({count} total, showing first 20):[/yellow]")
                for s in samples:
                    console.print(f"[dim]{s}[/dim]")
            except Exception:
                pass
            return None

        with console.status("[cyan]Downloading PDF…[/cyan]", spinner="dots"):
            async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as dl_info:
                await dl_link.click(timeout=CLICK_TIMEOUT)
            download = await dl_info.value

        await download.save_as(str(out_path))
        console.print(f"[green]Downloaded: {out_path}[/green]")
        return out_path

    # --- 3 automatic attempts with a short pause between each ---
    for attempt in range(1, 4):
        console.print(f"[cyan]Looking for PDF download button (attempt {attempt}/3)…[/cyan]")
        try:
            result_path = await _try_download()
            if result_path:
                return result_path
            console.print(f"[yellow]Attempt {attempt}/3: PDF button not found.[/yellow]")
        except (PlaywrightTimeout, Exception) as exc:
            console.print(f"[yellow]Attempt {attempt}/3: {exc}[/yellow]")

        if attempt < 3:
            await page.wait_for_timeout(2_000)

    # --- All 3 attempts failed — diagnose why ---
    captcha_present = False
    try:
        cap = page.locator(
            "label[for='fox-captcha-checkbox'], "
            "[class*='fox-internal-captcha'], "
            "#fox-widget"
        )
        captcha_present = await cap.count() > 0
    except Exception:
        pass

    if captcha_present:
        # CAPTCHA is still blocking — give the user a chance to complete it manually
        if captcha_cb:
            await captcha_cb()
        else:
            console.print(Panel(
                "The CAPTCHA ('Ich bin ein Mensch') appears to still be unchecked.\n"
                "Please click it manually in the browser, then press [bold]ENTER[/bold].",
                title="CAPTCHA Required",
                border_style="yellow",
                expand=False,
            ))
            input()
        # One final download attempt after manual CAPTCHA
        try:
            result_path = await _try_download()
            if result_path:
                return result_path
        except Exception as exc:
            console.print(f"[red]Download still failed after manual CAPTCHA: {exc}[/red]")
    else:
        # Something else is wrong (wrong page, session expired, etc.)
        console.print("[red]PDF download button could not be found and no CAPTCHA is visible.[/red]")
        if interactive and ask_retry("Start over with a new search?"):
            return None   # caller will reset to SEARCH state

    return None


def _readable_label(text: str) -> bool:
    """Return True if text has enough alphanumeric content to be worth showing."""
    if not text:
        return False
    alnum = sum(1 for c in text if c.isalnum() or c in " .,:-/()%")
    return alnum / max(len(text), 1) >= 0.45


def display_table_list(tables: list[dict]) -> None:
    """Compact Rich table: one row per extracted table with heading and size."""
    tbl = Table(show_header=True, header_style="bold cyan", padding=(0, 1))
    tbl.add_column("#",      width=4,  style="bold")
    tbl.add_column("Pages",  width=8)
    tbl.add_column("Size",   min_width=18)
    tbl.add_column("Heading / First Row", min_width=60)

    for t in tables:
        page_str = (str(t["page_start"]) if t["page_start"] == t["page_end"]
                    else f"{t['page_start']}–{t['page_end']}")
        size_str = f"{t['col_count']} cols × {t['row_count']} rows"

        label = ""

        # 1. Use extracted heading if it looks readable (collapse any embedded newlines)
        raw_heading = " ".join((t.get("heading") or "").split())
        if raw_heading and _readable_label(raw_heading):
            label = raw_heading[:75]

        # 2. Fall back to first readable preview row (skip garbage / arrow-only rows)
        if not label:
            for row in t.get("preview", []):
                cells = [str(c).strip() for c in row if str(c).strip()][:5]
                candidate = " | ".join(c[:20] for c in cells)
                if _readable_label(candidate):
                    label = candidate[:75]
                    break

        if not label:
            label = "—"

        tbl.add_row(str(t["index"]), page_str, size_str, label)

    console.print(tbl)


def select_tables(tables: list[dict]) -> Optional[list[dict]]:
    """
    Prompt user for comma-separated table numbers or 'all'.
    Returns selected table dicts, or None to abort.
    """
    n = len(tables)
    for attempt in range(1, 3):
        raw = Prompt.ask(
            f"\n[bold]Enter table numbers to export[/bold] "
            f"(comma-separated, e.g. 1,3 — or 'all')"
        )
        token = raw.strip().lower()
        if token == "all":
            return tables
        if not token:
            if attempt < 2:
                console.print("[yellow]No input. Please enter table numbers or 'all'.[/yellow]")
                continue
            return None

        parts = [p.strip() for p in token.split(",")]
        invalid = []
        selected_indices = []
        for p in parts:
            try:
                idx = int(p)
                if 1 <= idx <= n:
                    selected_indices.append(idx)
                else:
                    invalid.append(p)
            except ValueError:
                invalid.append(p)

        if invalid:
            console.print(f"[yellow]Invalid table numbers: {', '.join(invalid)}. "
                          f"Valid range: 1–{n}. Please try again.[/yellow]")
            continue

        seen = set()
        deduped = []
        for i in selected_indices:
            if i not in seen:
                seen.add(i)
                deduped.append(i)
        return [t for t in tables if t["index"] in deduped]

    return None
