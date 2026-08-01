"""Interactive command-line entry point (the GUI is the primary interface)."""

from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from rich.panel import Panel
from config import (
    BASE_URL, PAGE_LOAD_TIMEOUT,
)

from ._core import State, console
from .browser import ask_retry, display_results, display_table_list, download_pdf, launch_browser, open_document, prompt_company_name, run_search, select_document, select_tables
from .extract import extract_tables_from_pdf
from .exporters import export_to_csv


async def main():
    """
    Entry point — drives the full workflow as an explicit state machine.
    Handles KeyboardInterrupt and unexpected exceptions for clean shutdown.
    """
    console.print(Panel(
        "[bold]Unternehmensregister Financial Extractor[/bold]\n"
        "Extracts financial tables from Jahresabschluss / Konzernabschluss PDFs.",
        border_style="blue",
    ))

    playwright_ctx = async_playwright()
    playwright     = await playwright_ctx.start()
    browser = None
    page    = None

    try:
        # ── Step 1: Launch browser ────────────────────────────────────────
        browser, _context, page = await launch_browser(playwright)

        state = State.SEARCH
        result_rows: list[dict]  = []
        selected_result: Optional[dict] = None
        pdf_path: Optional[Path] = None
        pdf_tables: list[dict]   = []
        last_company: str        = ""   # remember last search for retry

        while state != State.QUIT:

            # ── SEARCH state ──────────────────────────────────────────────
            if state == State.SEARCH:
                # Navigate back to homepage for fresh search
                try:
                    await page.goto(BASE_URL, timeout=PAGE_LOAD_TIMEOUT)
                    await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                except PlaywrightTimeout:
                    console.print("[red]Could not navigate back to homepage.[/red]")

                company_name = prompt_company_name()
                last_company = company_name
                rows = await run_search(page, company_name)

                if rows is None:
                    if ask_retry("Search again with a different name?"):
                        state = State.SEARCH
                    else:
                        state = State.QUIT
                    continue

                result_rows = rows
                display_results(result_rows)
                state = State.SELECT_DOC

            # ── SELECT_DOC state ──────────────────────────────────────────
            elif state == State.SELECT_DOC:
                # If we arrived here from a CAPTCHA failure the page may be on
                # the wrong URL — navigate back to results first.
                if not any(kw in page.url for kw in ("suchergebnis", "searchResult", "result")):
                    try:
                        await page.goto(BASE_URL, timeout=PAGE_LOAD_TIMEOUT)
                        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                        rows = await run_search(page, last_company)
                        if rows:
                            result_rows = rows
                            display_results(result_rows)
                    except Exception:
                        pass

                selected_result = await select_document(page, result_rows)
                if selected_result is None:
                    state = State.SEARCH
                else:
                    state = State.CAPTCHA

            # ── CAPTCHA state ─────────────────────────────────────────────
            elif state == State.CAPTCHA:
                success = await open_document(page, selected_result)
                if success:
                    state = State.DOWNLOAD
                else:
                    # Offer to retry the same company (default y) rather than
                    # going back to SELECT_DOC on the wrong page
                    console.print(f"[yellow]Last search: '{last_company}'[/yellow]")
                    if ask_retry(f"Try same company again? (will re-search '{last_company}')"):
                        rows = None
                        try:
                            await page.goto(BASE_URL, timeout=PAGE_LOAD_TIMEOUT)
                            await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                            rows = await run_search(page, last_company)
                        except Exception:
                            pass
                        if rows:
                            result_rows = rows
                            display_results(result_rows)
                            state = State.SELECT_DOC
                        else:
                            state = State.SEARCH
                    else:
                        state = State.SEARCH

            # ── DOWNLOAD state ────────────────────────────────────────────
            elif state == State.DOWNLOAD:
                pdf_path = await download_pdf(page, selected_result)
                if pdf_path is None:
                    state = State.SEARCH   # download_pdf already asked the user what to do
                else:
                    state = State.EXTRACT

            # ── EXTRACT state ─────────────────────────────────────────────
            elif state == State.EXTRACT:
                pdf_tables = extract_tables_from_pdf(pdf_path)

                if pdf_tables is None:
                    # Corrupt or unreadable PDF
                    if ask_retry("Try a different document?"):
                        state = State.SELECT_DOC
                    else:
                        state = State.QUIT
                    continue

                if len(pdf_tables) == 0:
                    if ask_retry("Try a different document?"):
                        state = State.SELECT_DOC
                    else:
                        state = State.QUIT
                    continue

                display_table_list(pdf_tables)
                state = State.EXPORT

            # ── EXPORT state ──────────────────────────────────────────────
            elif state == State.EXPORT:
                # Inner loop: export tables, then offer to export more from the same doc
                while True:
                    selected_tables = select_tables(pdf_tables)
                    if selected_tables is None:
                        break

                    n_exported = export_to_csv(selected_tables, selected_result)
                    console.print(
                        f"\n[bold green]Done. Exported {n_exported} table(s) for "
                        f"{selected_result['company']} {selected_result['fy']}.[/bold green]"
                    )

                    if not ask_retry("Export more tables from this document?"):
                        break

                    # Re-show the table list for another selection round
                    display_table_list(pdf_tables)

                if ask_retry("Search another company?"):
                    state = State.SEARCH
                else:
                    state = State.QUIT

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Closing browser…[/yellow]")

    except Exception as exc:
        console.print(f"\n[red]Unexpected error: {exc}[/red]")
        console.print("[dim]Please report this with the above message.[/dim]")

    finally:
        # Guarantee browser cleanup regardless of how we exit
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        await playwright_ctx.__aexit__(None, None, None)
        console.print("[dim]Browser closed. Goodbye.[/dim]")
