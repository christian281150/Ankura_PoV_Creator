# Search & Batch-Select

> **Canvas state:** `search` · **Module:** Acquisition · **Generated:** 2026-06-28

## Overview
The entry screen for a company. The analyst types a company name, the app searches the
German company register, lists the available filings, and the analyst ticks which annual
reports to download and extract in one batch. This is the only screen that talks to the
external register.

## When a user is here
- On launch (default canvas) and whenever the active company has no extracted tables yet.
- After clicking **+** (add company) in the left rail, or selecting a company that hasn't
  been processed.

## Layout
```
┌──────────────────────────────────────────────┐
│  [ Company name…              ] [ Search ]    │  search area (top, padded)
│  status line / hint                           │
├──────────────────────────────────────────────┤
│  ☐ FY2024  Jahresabschluss  filed 2025-…      │  results list (scrollable
│  ☐ FY2023  Jahresabschluss  filed 2024-…      │  cards, one per filing)
│  ☐ …                                          │
├──────────────────────────────────────────────┤
│  [ Process N selected ]                       │  action button
│  [progress cards while running]               │
└──────────────────────────────────────────────┘
```

## Fields

### Search area
| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| Company name | Text input | Yes | empty | Free text; submitted to register search. Enter key or **Search** button triggers. |
| Search | Button | — | — | Disabled until a company slot is active; shows progress via status track. |

### Results list (one card per filing)
Each result card represents one filing returned by the register and exposes:
| Column | Source field | Notes |
|--------|--------------|-------|
| Select | checkbox | Tick to include in the batch |
| Fiscal year | `fy` | e.g. "FY2024" |
| Document type | `doc_type` | e.g. "Jahresabschluss", "Konzernabschluss" |
| Date filed | `date_filed` | Publication date |
| (hidden) | `company`, `url` | Used to open/download the document |

> Result dict shape (from `run_search`): `{company, doc_type, fy, date_filed, url}`; a
> `pdf_path` is added after download.

### Actions
| Button | Visibility | Behavior |
|--------|-----------|----------|
| Process N selected | When ≥1 filing ticked | Sends the selected filings to the worker for batch download + extraction |

## Interactions

### Search
- **Trigger:** Enter in the name field or **Search** click.
- **Behavior:** GUI sends `search` → worker runs `run_search()` against the register
  (navigates, fills the form, **solves the CAPTCHA**, reads the hit list). Status track
  shows "Searching for '…'". Worker emits `search_results` with the list (or `None`).
- **Result:** Results list populates; the company slot's name is set from the first
  result's company on first document add.
- **Empty / failure:** `search_results=None` → a "no results / could not reach register"
  message via the status track.

### Batch process (download + extract)
- **Trigger:** **Process N selected**.
- **Behavior:** GUI sends `process_batch` with `(selected_filings, pdf_dir)`. The worker
  loops each filing:
  1. `open_document()` → navigate to the filing.
  2. `download_pdf()` → download (handles a second CAPTCHA if prompted; the GUI shows a
     **captcha pending** indicator and waits).
  3. `extract_tables_from_pdf()` → detect & classify tables.
  - Emits `batch_progress` (per-step %), `batch_doc_done` (one filing's `doc` + `tables`),
    or `batch_error` per filing.
- **Per-document completion (`batch_doc_done`):** the filing's tables are appended to the
  active company's `all_tables` and a `doc_sections` entry is recorded. **Saved table
  overrides are re-applied immediately** (`apply_table_overrides`) so prior corrections
  stick.
- **On batch completion (`batch_complete`):** the consolidation is rebuilt, the
  **Needs Review** list recomputed, the canvas switches to **OVERVIEW**, the first
  available statement tab is shown, **Export** is enabled, and the company is
  **auto-saved to the Library**. Status: "✓ N tables extracted".

### CAPTCHA handling
The register protects search and download with a CAPTCHA. The worker solves/awaits it
inside `run_search`/`download_pdf`; the GUI surfaces a pending state and a configurable
wait (`CAPTCHA_WAIT_S`, `CAPTCHA_TIMEOUT`). No analyst action is required unless it times
out, in which case a `batch_error` is shown for that filing.

## API / Backend dependencies
This screen drives the **external register** through the worker (no app-owned HTTP API).

| Worker command | Trigger | Backend function | Emits |
|----------------|---------|------------------|-------|
| `search` | Search | `run_search()` | `status`, `search_results` |
| `process_batch` | Process selected | `_process_batch()` → `open_document` + `download_pdf` + `extract_tables_from_pdf` | `batch_progress`, `batch_doc_done`, `batch_error`, `batch_complete` |
| `navigate_home` | reset/new search | browser back to base URL | `ready` |

See [../appendix/backend-pipeline.md](../appendix/backend-pipeline.md) for the extraction internals.

## Page relationships
- **From:** App launch; left-rail **+**; selecting an unprocessed company.
- **To:** **OVERVIEW** (automatically, after `batch_complete`).
- **Data coupling:** writes into the active company's `all_tables` / `doc_sections`,
  which feed both the OVERVIEW grid and the All Tables workbench.

## Business rules
- PDFs are downloaded to the configured **PDF folder** (Settings; default
  `~/Downloads/UR_Extracts`).
- A filing with no detectable tables emits `batch_error("No tables found")` and is skipped.
- The company name shown in the rail is derived from the first downloaded document's
  `company` (replacing the "(Searching…)" placeholder).
