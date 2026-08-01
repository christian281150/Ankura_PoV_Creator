# UR Financial Extractor — Product Requirements Document

> **Generated:** 2026-06-28 · **Branch documented:** `Mapping_update`
> **Application type:** Windows desktop GUI (Python + CustomTkinter)
> **Entry point:** `ur_gui.py` → `main()` → `URExtractorApp().mainloop()`

## System Overview

UR Financial Extractor is a single-user **desktop tool** that pulls German statutory
financial statements from the official company register
([unternehmensregister.de](https://www.unternehmensregister.de) / Bundesanzeiger),
extracts the financial tables out of the published PDFs, and turns a company's
multiple annual filings into one **comparable multi-year model** (Balance sheet,
P&L, Cash flow) that can be exported to Excel.

The product solves three problems for a financial analyst:

1. **Acquisition** — searching the register, solving its CAPTCHA, and downloading the
   right filing PDFs is slow and manual. The app automates the search → select →
   download flow with a headless browser.
2. **Extraction** — statutory PDFs are layout-heavy; tables are scattered across
   pages with German section headings. The app detects and extracts every table and
   classifies each as Bilanz (balance sheet), GuV (P&L), Kapitalfluss (cash flow), or
   Sonstige (other/notes).
3. **Standardisation & comparison** — the same line item is labelled differently
   across years and companies. The app maps each label to a canonical **HGB §266/§275**
   position, joins filings into a year-over-year grid, and lets the analyst correct the
   consolidation (which tables feed it, merging differently-named rows) with every
   correction **remembered** for next time.

**Primary user:** one financial analyst running the app locally. There is no
multi-tenant server, no login, and no network API of its own — the only external
service is the public register, driven through a browser automation layer.

## Architecture at a Glance

The app is a **two-thread desktop application**:

- **GUI thread** (`URExtractorApp`, a CustomTkinter `CTk` window) renders all screens
  and never blocks. It talks to the worker through two queues.
- **Worker thread** (`_Worker`) owns an asyncio event loop and a Playwright browser.
  It performs all slow/blocking work: register search, document download, PDF
  extraction, consolidation, and Excel export.

Communication is a small **command/event protocol** (the closest thing this desktop
app has to an "API"):

- GUI → Worker: `self._worker.send(command, payload)`
- Worker → GUI: `self._emit(event, data)`, drained every 100 ms by `self.after(100, self._poll)`

See [appendix/backend-pipeline.md](./appendix/backend-pipeline.md) for the full command
and event inventory and the extraction/consolidation pipeline.

### Source modules

| File | Role |
|------|------|
| `ur_gui.py` (~3,270 lines) | All screens, widgets, worker thread, event loop, persistence wiring |
| `ur_extractor.py` (~3,580 lines) | Browser scraping, PDF table extraction, classification, consolidation, Excel/CSV export, persistence stores, HGB audit |
| `config.py` | Settings loader (`config.cfg`), colour/font constants, theme palettes, currency units, timeouts |
| `tokens.py` | Design-token single-source-of-truth (`T`, `FONT`, `SPACE`, `ROW_H`, `BADGE`, `LAYOUT`) |
| `lib/hgb_map.py` | Canonical HGB §266/§275 mapping (v1.1, GKV/UKV aware); `lookup` / `by_id` / `resolve` |
| `lib/hgb_data/` | Source data for the mapping (taxonomy, label synonyms, account ranges, GKV↔UKV bridge) |

## Module Overview

| Module | Screens / Regions | Core functionality |
|--------|-------------------|--------------------|
| **Acquisition** | Search & batch-select | Search the register, pick filings, batch-download PDFs (CAPTCHA handled) |
| **Consolidation** | OVERVIEW grid (Bilanz / GuV / Cashflow tabs) | Year-over-year canonical grid, per-cell audit, source picker, row-merge |
| **Table workbench** | All Tables (collapsible type→year segments) | Inspect/segment every extracted table; bulk re-segmentation feeds consolidation |
| **Right rail** | Audit · Preview · Sources picker · Needs Review | Drill-down, table preview, choose consolidation inputs, fix unmapped labels |
| **Company workspace** | Left rail (New Searches + Library) | Switch companies; auto-saved library survives restart |
| **Output** | Export dialog | Scope + statement-filtered Excel export |
| **Settings & status** | Settings panel, status track | Theme, currency, number format, folders; breadcrumb, progress, review chips |

## Screen Inventory

| # | Screen / Region | Where | Doc |
|---|-----------------|-------|-----|
| 1 | Search & batch-select | Center canvas (`search` state) | [→](./pages/01-search-and-batch.md) |
| 2 | OVERVIEW consolidated grid | Center canvas (`overview` state) | [→](./pages/02-overview-consolidated-grid.md) |
| 3 | All Tables workbench | Center canvas (`all_tables` state) | [→](./pages/03-all-tables.md) |
| 4 | Right rail (Audit / Preview / Picker / Review) | Right column | [→](./pages/04-right-rail.md) |
| 5 | Company rail & Library | Left column | [→](./pages/05-company-rail-library.md) |
| 6 | Settings panel | Slide-over from right | [→](./pages/06-settings.md) |
| 7 | Export options dialog | Modal | [→](./pages/07-export-dialog.md) |
| 8 | Status track & breadcrumb | Top bar | [→](./pages/08-status-track.md) |

## Appendix

- [enum-dictionary.md](./appendix/enum-dictionary.md) — every code/enum: statement types, badges, match types, row types, currency units, themes, SKR variants, GKV/UKV.
- [screen-relationships.md](./appendix/screen-relationships.md) — navigation & data-coupling map.
- [backend-pipeline.md](./appendix/backend-pipeline.md) — worker command/event protocol + the scraping→extraction→consolidation→export pipeline.
- [data-schemas-and-mapping.md](./appendix/data-schemas-and-mapping.md) — persistence stores (overrides, row-merges, library, prefs, aliases) and the HGB mapping subsystem.

## Global Notes

### Window layout (3-column shell)
A fixed shell: **top status track** (row 0) · **progress bar** (row 1) · **content area**
(row 2). The content area is three columns: **left rail** (240 px companies), **center
canvas** (flexes; hosts the active screen), **right rail** (320 px; collapsed by default,
widens to ~600 px in Preview). The center canvas swaps between three states — `search`,
`overview`, `all_tables` — via `_switch_canvas()`.

### The multi-company session model
`self._session = {"companies": [...], "active_company_id": ...}`. Each *company* is a
plain dict: `id`, `name`, `all_tables`, `overview_tables`, `doc_sections`,
`review_line_items`, `review_tables`. It is fully JSON-serialisable, which is what makes
the Library (save/restore) possible.

### "Learning" corrections (the core product principle)
Every correction the analyst makes is **persisted and re-applied automatically** on the
next extraction of the same company:
- Re-classify a table's type / include-exclude it → `data/table_overrides.csv`.
- Merge two differently-named rows → `data/row_merges.csv`.
- Resolve/remap an unmapped label → `aliases/client_aliases.csv`.
The whole worked-up company is also snapshotted to a **Library** next to the executable.

### Canonical mapping rule (do-not-guess)
Labels are mapped to canonical HGB positions through `lib/hgb_map.py` only. Lookup is
**exact-normalized match**; it never fuzzy-guesses. An unknown or ambiguous label is
surfaced in **Needs Review** rather than silently bucketed. See
[data-schemas-and-mapping.md](./appendix/data-schemas-and-mapping.md).

### Theming
Light (default) / Dark, switched at runtime in Settings. Colours come from the design
tokens (`tokens.py`) and `config.py` theme palettes; no screen hard-codes hex values.
