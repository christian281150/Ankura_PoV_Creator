# Unternehmensregister Financial Extractor - to be updated


A portable Windows desktop tool that searches the German **Unternehmensregister**
(unternehmensregister.de), downloads annual-report PDFs, and extracts financial
tables (Bilanz, GuV, Kapitalflussrechnung) into a structured Excel workbook.
Multi-year filings are automatically consolidated into canonical summary tables
using the HGB standardisation map so line items align across years and entities
regardless of label variation.

---

## Features

| Feature | Detail |
|---|---|
| Company search | Full-text search across all German registered companies |
| Multi-select | Select multiple filings (years / companies) in one go |
| Parallel processing | Each filing gets its own browser instance — downloads run simultaneously |
| CAPTCHA handling | Automated click attempt; falls back to a one-click GUI dialog |
| Table extraction | pdfplumber-based extraction with multi-page stitching and heading detection |
| Type detection | Auto-classifies tables as Bilanz / GuV / Kapitalfluss / Other |
| HGB mapping | Each extracted row is resolved to a canonical `std_id` (PL-010 … CF-R-020) |
| Multi-year summary | Overview tables consolidate all years side-by-side using `std_id` as the merge key |
| Excel export | One workbook, one sheet per table; bare floats for native Excel recognition |
| Number formatting | Configurable decimal + thousands separator (German `,` / English `.`) |
| PDF folder | Configurable download directory — auto-creates `Company_Name/` subfolders |
| Portable build | Single folder with `.exe` — no installation required |

---

## Requirements

### Portable build (end-user)
- Windows 10 or 11 (x64)
- Microsoft Edge installed (default on every Windows 10/11 machine)
- Nothing else — just unzip and run

### Development
- Python 3.10+
- Microsoft Edge

```bat
pip install -r requirements.txt
```

---

## Quick-start (portable)

1. Download and unzip `UR_Financial_Extractor_v1.0.zip`
2. Open the extracted folder
3. Double-click **`UR_Financial_Extractor.exe`**
4. Type a company name and press **Search**
5. Tick the filings you want → **Process Selected**
6. Complete the CAPTCHA when the dialog appears
7. Check the **OVERVIEW** section for consolidated multi-year tables
8. **Export All** or pick individual tables with **Export Selected**

---

## Development setup

```bat
git clone <repo>
cd Bundesanzeiger_Financial_Extracts
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python ur_gui.py        # launch GUI
python ur_extractor.py  # run CLI / debug extraction
```

---

## Usage guide

### Searching
- Partial or full company name — substring matching works well
- Results are filtered to *Veröffentlichungen → Rechnungslegung* automatically
- Results are grouped by company with collapsible company headers (▾/▸)
- **Select all** checkbox selects every returned filing at once

### Processing
- Filings run in parallel (one hidden browser window each)
- A CAPTCHA dialog appears once per document — click the checkbox in the browser, then OK
- Status bar and progress bar show per-document progress

### Table list

Tables are grouped two ways depending on how many documents were processed:

**Single document** — flat type sections at the top level:

| Group | Colour |
|---|---|
| OVERVIEW (multi-year summaries) | Amber |
| Bilanz | Blue |
| GuV / Ergebnis | Green |
| Kapitalfluss | Purple |
| Sonstige | Grey |

**Multiple documents** — year-first hierarchy: one collapsible card per fiscal year,
with type sub-sections inside each year.

- Click a pill / header to expand or collapse that section
- **Select / Deselect** button per type group
- Sorted newest → oldest within each group
- Click any row to preview in the right panel
- Multi-year summary rows show the range of years (e.g. `2022 · 2023 · 2024`)

### OVERVIEW — multi-year summary tables

After processing two or more filings, an **OVERVIEW** section appears at the top
of the tables list. Each summary table merges the individual-year tables into a
single view with one column per fiscal year.

Row alignment uses the HGB canonical `std_id` as the join key, so rows match
even when a company changes its label wording between years (e.g.
`Jahresüberschuss` one year, `Jahresfehlbetrag` another).

### Export
- **Export Selected** — only the ticked tables
- **Export All** — everything in this session, including OVERVIEW tables
- Each table → one Excel sheet (named: `FY_ShortHeading`)
- Numbers written as bare floats — Excel applies its own formatting

### Settings (⚙ top-right)

| Setting | Default | Notes |
|---|---|---|
| Decimal separator | `,` (German) | Change to `.` for English-language PDFs |
| Thousands separator | `.` (German) | Or `,` / *none* |
| PDF download folder | `~/Downloads/UR_Extracts/` | PDFs saved to `<folder>/<Company>/` |

Settings are persisted to `~/Downloads/UR_Extracts/prefs.json` between sessions.

---

## Building the portable executable

### Prerequisites
```bat
pip install pyinstaller
```

### One-command build
```bat
build.bat
```

Output: `dist\UR_Financial_Extractor\`

### Create distributable ZIP
```bat
powershell Compress-Archive dist\UR_Financial_Extractor UR_Financial_Extractor_v1.0.zip
```

### What is bundled
- All Python packages (`pdfplumber`, `openpyxl`, `customtkinter`, `playwright` driver, …)
- The Playwright Node.js bridge (controls Edge via CDP)
- HGB mapping library (`lib/hgb_map.py` with embedded canonical chart)
- **NOT bundled**: Microsoft Edge itself (system-provided)

---

## Project structure

```
Bundesanzeiger_Financial_Extracts/
├── ur_extractor.py         # Backend: browser automation, PDF extraction, Excel export
├── ur_gui.py               # GUI frontend (CustomTkinter)
├── config.py               # Settings loader (reads config.cfg, falls back to defaults)
├── config.cfg              # Optional: override colours, fonts, timeouts, separators
├── requirements.txt        # Python dependencies
├── build.bat               # One-click PyInstaller build
├── UR_Extractor.spec       # PyInstaller spec for reproducible builds
│
├── lib/
│   └── hgb_map.py          # HGB canonical mapping utility (self-contained, zero deps)
│
├── data/
│   ├── hgb_mapping.json    # Source mapping data (generated from Excel workbook)
│   ├── hgb_pl_map.csv      # P&L canonical rows
│   ├── hgb_bs_map.csv      # Balance sheet canonical rows
│   └── hgb_cf_map.csv      # Cash flow canonical rows
│
├── aliases/
│   └── client_aliases.csv  # Client-specific label overrides (client_label,std_id,client,note)
│
├── reviews/
│   └── unmapped_queue.csv  # Labels that could not be resolved — manual review queue
│
└── README.md
```

---

## Architecture notes

### Backend (`ur_extractor.py`)
- Playwright async API with **Microsoft Edge** (`channel="msedge"`) — no Chromium download
- Fixed viewport `1280×900` for reproducible coordinates
- CAPTCHA: three DOM selectors → `label[for=fox-captcha-checkbox]` → span offset → widget offset
- PDF extraction: `pdfplumber.find_tables()` for bbox, heading via largest-font char above table
- Multi-page stitching: same col count + prev ends near bottom + curr starts near top
- Statement splitting: "Summe Passiva" marks end of Bilanz; GuV follows on next row
- Number parsing: group-of-3 check prevents Anhang refs ("4.8") being treated as numbers
- HGB mapping: `_hgb_key(desc, stmt)` resolves each row to a `std_id` for PL/Bilanz;
  CF uses pattern-based `_canonical_key()` (CF DRS 21 labels vary too widely for lookup)
- Multi-year consolidation: `build_multi_year_tables()` merges per-year tables by `std_id`
  key; cashflow section totals are normalised via regex synonyms (6 canonical CF keys)

### GUI (`ur_gui.py`)
- `ExtractorWorker` runs the asyncio loop in a **background thread**
- GUI ↔ worker: `queue.Queue` polled every 100 ms via `after()`
- Parallel batch: `asyncio.gather()` + per-document browsers + CAPTCHA `asyncio.Lock`
- Clean shutdown: `threading.Event` waits for Playwright driver to exit → no EPIPE crash
- Settings panel opens on startup; preferences persisted to `prefs.json`
- Per-session log files written to `~/Downloads/UR_Extracts/logs/`

### HGB mapping (`lib/hgb_map.py`)
- Zero external dependencies; data embedded as Python literals
- `SYNONYM_INDEX`: normalised German label → `[std_id, …]`; built at import time
- `lookup(label)` returns `{query, normalized, match_type, candidates}`;
  never silently picks an ambiguous result
- Ambiguous or unmatched labels are written to `reviews/unmapped_queue.csv`;
  resolved items are added to `aliases/client_aliases.csv`
- CF records use `drs21_de` field for German labels; encoding artefacts in embedded
  data mean CF rows bypass HGB lookup and use regex synonym patterns instead

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not launch browser" | Ensure Microsoft Edge is installed and up to date |
| No search results | Try a shorter or differently spelled company name |
| CAPTCHA not auto-clicking | Click the checkbox manually in the browser, then press OK in the dialog |
| No tables found | PDF may be image-only (scanned); pdfplumber needs a text-layer PDF |
| Numbers show as text in Excel | Check Settings → correct decimal separator for the source document |
| OVERVIEW table missing rows | Label not yet in HGB map or client aliases — check `reviews/unmapped_queue.csv` |
| EPIPE error on close | Fixed in current version via `wait_done()` — update if still occurring |

---

## License

Internal research tool — not for redistribution or commercial use.
Data sourced from unternehmensregister.de — usage subject to their terms of service.
