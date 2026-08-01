# UI/UX Design Brief — Unternehmensregister Financial Extractor

**For:** UI/UX design review and redesign proposals
**Prepared by:** Development team
**Purpose:** Provide a complete picture of the current application so a UI/UX expert
can propose improvements that can be implemented in the existing codebase.

---

## 1. What This Application Does

### Use case
Analysts at a consulting firm need financial data from German companies. This data is
publicly available on the **Unternehmensregister** (unternehmensregister.de) — the
official German company registry — but only in PDF form. Extracting it manually is
slow and error-prone for portfolios of 10–100+ companies.

This tool automates:
1. Searching for companies by name
2. Downloading the annual-report PDFs
3. Extracting the financial tables (balance sheet, P&L, cash flow)
4. Aligning multi-year data into a single view using a canonical accounting map
5. Exporting to Excel for further analysis

### Who uses it
Internal analysts with financial/accounting backgrounds. They understand German HGB
accounting terminology. They are not developers. They run the tool on Windows laptops
directly from the downloaded folder — no installation.

### What "success" looks like for a user
Open the app → type a company name → tick the years they want → click one button →
get an Excel file with clean, aligned financial tables. The fewer steps and the less
thinking required, the better.

---

## 2. Current User Workflow

```
1. Launch app
   └─ Settings panel appears on first run (decimal/thousands separator, download folder)

2. Type company name in search box → press Search or Enter
   └─ Results appear grouped by company (accordion)
   └─ Each result card shows: fiscal year (large), company name, doc type, filing date

3. Tick the filings to process (checkbox on each card, or "Select all")
   └─ Button updates live: "Process Selected (3)"

4. Click "Process Selected"
   └─ Progress bar fills; status bar updates per document
   └─ CAPTCHA dialog appears once per document when automated click fails
      └─ User clicks checkbox in the browser window that opened, then "OK" in the dialog

5. Tables appear in the sidebar list as each document completes
   └─ OVERVIEW section at top: multi-year summary tables (all years side-by-side)
   └─ Per-document sections below: individual-year tables grouped by type

6. Click any table row to preview it in the right panel
   └─ Treeview shows the full table with column headers

7. Tick tables to include, then "Export Selected" or "Export All"
   └─ File-save dialog → Excel workbook written
   └─ Success message with file path

8. "New Search" button resets to step 2
```

---

## 3. Current UI Layout

### Overall structure
Two-panel layout, fixed split: **left sidebar (400 px fixed)** + **right preview pane (fills remaining width)**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  TOP BAR (full width, ~52px)                                            │
│  [● status dot] [status text ...........]  [Log ▪] [⚙ Settings]        │
│  [████████████████ progress bar (hidden when idle) ███████████████████] │
├────────────────────────────┬────────────────────────────────────────────┤
│  SIDEBAR (400px fixed)     │  PREVIEW PANE (fills remaining width)      │
│                            │                                            │
│  SEARCH                    │  [Table heading / "Table Preview"]         │
│  [search input    ][Search]│                                            │
│                            │  ┌──────────────────────────────────────┐  │
│  SEARCH RESULTS            │  │  TREEVIEW TABLE                      │  │
│  [□ Select all] [0 sel'd]  │  │  Col 1  │  Col 2  │  Col 3          │  │
│  ┌─────────────────────┐   │  │─────────┼─────────┼─────────         │  │
│  │▾ Company Name (3)   │   │  │ row 1   │  1,234  │  5,678          │  │
│  │ ┌─────────────────┐ │   │  │ row 2   │  2,345  │  6,789          │  │
│  │ │□ 2024  Name  Typ│ │   │  │  ...                                │  │
│  │ │□ 2023  Name  Typ│ │   │  └──────────────────────────────────────┘  │
│  │ │□ 2022  Name  Typ│ │   │                                            │
│  │ └─────────────────┘ │   │  [debug log drawer — hidden by default]    │
│  └─────────────────────┘   │                                            │
│                            │                                            │
│  [Process Selected (0)   ] │                                            │
│  ─────────────────────────  │                                            │
│  EXTRACTED TABLES          │                                            │
│  ┌─────────────────────┐   │                                            │
│  │▾ OVERVIEW       (2) │   │                                            │
│  │ □ ALL-GuV 22·23·24  │   │                                            │
│  │ □ ALL-Bilanz 22·24  │   │                                            │
│  │▾ Bilanz         (3) │   │                                            │
│  │ □ Bilanz  2024  p.4 │   │                                            │
│  │ □ Bilanz  2023  p.3 │   │                                            │
│  │▾ GuV / Ergebnis (3) │   │                                            │
│  │ □ GuV     2024  p.6 │   │                                            │
│  │ ...                 │   │                                            │
│  └─────────────────────┘   │                                            │
│                            │                                            │
│  [Export Selected][Exp All]│                                            │
│  [New Search              ]│                                            │
└────────────────────────────┴────────────────────────────────────────────┘
```

---

## 4. Component-by-Component Description

### 4.1 Top bar
- **Status indicator**: small coloured dot (green=ready, amber=working, red=error) + text label
- **Progress bar**: full-width, thin (~6px), sits below the top bar row; hidden when idle
- **Log button**: toggles the debug log drawer in the preview pane (for developers)
- **Settings button (⚙)**: opens a modal settings panel

### 4.2 Settings modal
Opens at startup if no preferences have been saved yet; otherwise on ⚙ click.

| Field | Control | Default |
|---|---|---|
| Decimal separator | Radio: `,` / `.` | `,` (German) |
| Thousands separator | Radio: `.` / `,` / none | `.` (German) |
| PDF download folder | Text entry + Browse button | `~/Downloads/UR_Extracts/` |
| Log folder | Text entry + Browse button | `~/Downloads/UR_Extracts/logs/` |

Saved to `~/Downloads/UR_Extracts/prefs.json` on confirm.

### 4.3 Search section (sidebar top)
- Single-line text entry — triggers search on Enter or Search button click
- Search button is disabled until the browser worker is ready (~1–2 s after launch)
- Results replace any previous results immediately

### 4.4 Search results (sidebar, scrollable)
- Grouped by company name with an accordion header per company
  - Header: ▾/▸ toggle icon, company name, filing count
  - Click anywhere on the header to collapse/expand
- Each filing is a card: checkbox | large FY year | company name | doc type + date filed
- Clicking anywhere on a card (outside the checkbox) toggles the checkbox
- "Select all" checkbox at top selects/deselects all visible filings
- Counter label "N selected" updates live
- "Process Selected (N)" button enables when N > 0; shows count inline

### 4.5 Extracted tables (sidebar bottom, scrollable)
This section expands to fill whatever vertical space remains after the search results.

**Layout depends on how many documents were processed:**

*Single document:*
- OVERVIEW (if multiple years were loaded previously) → Bilanz → GuV → Kapitalfluss → Sonstige
- Each type section has a collapsible pill header

*Multiple documents:*
- OVERVIEW at top (always)
- One collapsible card per fiscal year (newest first): shows FY, company name, N/M selected
- Inside each year: same type sub-sections

**Type section pill headers:**
- Coloured pill with ▾/▸ toggle + type name
- Badge showing total count
- "N/M sel" count
- Select/Deselect toggle button (flips between Select all / Deselect all)

**Table rows:**
- Thin coloured left border (type colour)
- Checkbox
- Label (truncated to ~46 chars)
- FY badge (indigo pill, e.g. "2024")
- Page info + row count ("p.4 12r") or years for multi-year ("3 yrs")
- Click anywhere on row → previews in right panel; click checkbox → selects for export

### 4.6 Action buttons (sidebar bottom, always visible)
- **Export Selected** (green) — exports only ticked tables
- **Export All** (green) — exports every table in the session
- **New Search** (ghost/outline) — clears everything, re-enables search

### 4.7 Preview pane (right panel)
- Title label at top: shows the selected table's heading
- Treeview table fills the pane: column headers from PDF row 1; all rows displayed
- Light theme (white background, dark text) for readability
- Vertical + horizontal scrollbars
- Row height 24 px; header row dark background with light text

**Subtotal styling:** The Treeview applies a grey background tag to rows identified
as subtotals (empty description cell + numeric values). The last subtotal row gets
an "Endsumme" tag (bold, slightly different shade).

### 4.8 Debug log drawer (preview pane, hidden by default)
- 8-line console at the bottom of the preview pane; toggled by the "Log" button
- Green = success events, red = errors, grey = info
- "Clear" button in the drawer header
- Keeps last 1 000 lines

### 4.9 CAPTCHA dialog
Modal dialog that appears when the automated CAPTCHA click fails.
- Title: "Human Verification"
- Instruction: "Click 'Ich bin ein Mensch' in the browser, then click OK here."
- Single "OK — CAPTCHA completed" button (indigo)

---

## 5. Visual Design

| Token | Value | Used for |
|---|---|---|
| Background | `#0d0d14` | App background |
| Panel | `#13131f` | Sidebar, top bar |
| Card | `#1c1c2e` | Filing cards, table rows |
| Card2 | `#22223a` | Company / year header rows |
| Border | `#2d2d48` | Dividers, card borders |
| Accent | `#6366f1` | Primary buttons, FY badge background, checkboxes |
| Accent light | `#818cf8` | Hover states, FY text |
| Accent dim | `#2d2d6e` | FY badge background |
| Text primary | `#f1f5f9` | Main labels |
| Text secondary | `#94a3b8` | Secondary labels, icons |
| Text muted | `#475569` | Counters, page info |
| Green | `#22c55e` | Success status, export buttons |
| Amber | `#f59e0b` | Working status, OVERVIEW pill |
| Red | `#ef4444` | Error status |
| Preview background | `#f8fafc` | Right-panel Treeview (light) |
| Bilanz (type) | `#3b82f6` | Blue |
| GuV (type) | `#10b981` | Green |
| Kapitalfluss (type) | `#8b5cf6` | Purple |
| Sonstige (type) | `#6b7280` | Grey |

**Fonts:** Segoe UI throughout. Hero labels 14 pt bold; headings 13–11 pt bold;
body 12 pt; small 11 pt; table rows 10 pt. Debug log uses Consolas 10 pt.

**Corner radius:** Pills 24 px; cards 12 px; small buttons 8 px.

**Theme engine:** CustomTkinter (dark mode). The preview Treeview uses the Tkinter
"clam" ttk theme with manual style overrides to match the dark shell with a
light-interior data display.

---

## 6. Technical Constraints for UI Changes

Understanding these constraints helps distinguish changes that are easy from
those that require significant re-engineering.

### What is easy to change
- Colours, fonts, spacing — all defined in `config.py` and `config.cfg`
- Button labels, placeholder text, dialog wording
- Adding new columns to the table row (e.g. a mapped-line-count badge)
- Adding a new setting to the Settings modal
- Reordering sections within the sidebar
- Adding tooltips (CustomTkinter supports them)
- The layout split ratio (sidebar width is a config constant)

### What is harder but feasible
- **Resizable split pane** — requires adding a drag handle and binding resize logic;
  currently the sidebar is a fixed-width grid column
- **Moving the preview to a separate window or tab** — requires refactoring how
  `_preview_table()` updates the Treeview
- **Adding a second preview column** for side-by-side year comparison — requires
  either a second Treeview or exporting to an embedded frame
- **Replacing the Treeview with a custom table widget** — piecemeal; the Treeview
  is deeply integrated but well-isolated in `_preview_table()`
- **Icons / images** — CustomTkinter supports CTkImage; would need assets bundled
  with the PyInstaller build

### What is not feasible without major rework
- **Web/Electron UI** — the tool is a Python desktop app; changing to a web frontend
  would require rewriting the worker communication layer
- **Live editing of table data in-preview** — the Treeview is read-only by design;
  making it editable adds significant state-management complexity
- **Drag-to-reorder tables** — the table list is rendered into a grid and rebuilt
  from scratch on any state change; drag-drop would require a canvas-based list
- **Native OS dark/light mode switching** — CustomTkinter has its own theming;
  it does not follow the OS setting automatically

### Threading model (important for any interactive feature)
All browser operations and PDF parsing run in a background thread (`ExtractorWorker`).
The GUI (Tkinter main thread) and the worker communicate **only** via a `queue.Queue`.
Any UI update triggered by a background event must go through this queue and be
processed in the 100 ms poll loop. This means:
- You **cannot** call Tkinter widget methods from the background thread
- Any new "live update" feature must be emitted as a queue event from the worker
  and handled in `_handle()` on the GUI thread

---

## 7. Current UX Pain Points

These are the known areas that work but feel rough:

### 7.1 The settings modal appears on every first launch
Users who just want to try the app are interrupted before they can do anything.
The defaults are sensible for German documents; the modal could be deferred until
the user explicitly opens Settings.

### 7.2 CAPTCHA flow breaks the parallel experience
When processing 5 documents in parallel, a CAPTCHA dialog appears and blocks
everything until dismissed. The user often does not know which document triggered it
or what to do in the browser window. The dialog text helps but the browser window
is not brought to the front automatically.

### 7.3 The sidebar is a wall of text under heavy load
With 4 years × 4 table types = 16 rows of tables plus the OVERVIEW section,
the sidebar becomes dense. The type-group headers help but are visually similar
to the table rows themselves.

### 7.4 No visual hierarchy between "search" and "results" phases
The search area and the table list share the same sidebar with no strong visual
separation. A user who finishes processing and wants to search for another company
has to scroll back up to find the search field — the "New Search" button at the
bottom helps but is easy to miss.

### 7.5 No progress per table type
The progress bar shows overall batch progress but does not indicate which tables
have been found yet. Users cannot tell whether the Bilanz has been extracted while
Kapitalfluss is still pending.

### 7.6 Export requires knowing which tables to select
First-time users have to understand the OVERVIEW vs individual-table distinction
to know whether they want the consolidated or the per-year export. There is no
"recommended export" shortcut.

### 7.7 Preview pane underused
The right panel takes up most of the screen but shows only one table at a time.
When the sidebar table list is the focus (selecting what to export), the preview
pane is idle.

### 7.8 The debug log is discoverable only by accident
Power users benefit from the log, but there is no visual affordance that it exists
unless they notice the "Log" button in the top bar.

---

## 8. Screens / States to Design For

1. **Launch state** — worker starting up, search disabled, status "Loading…"
2. **Ready to search** — search enabled, no results yet
3. **Searching** — button disabled, status "Searching for 'ACME GmbH'…"
4. **Results shown** — accordion result cards, process button enabled
5. **Processing** — progress bar active, CAPTCHA dialog may appear, tables arriving
6. **Tables available (single doc)** — overview + type sections visible, preview active
7. **Tables available (multi-doc)** — year-first hierarchy + overview
8. **Exporting** — brief loading state, then success/error
9. **Error state** — red status, error message dialog
10. **Settings modal** — overlaid on any of the above

---

## 9. Files the UI/UX Expert Should Know About

| File | Role |
|---|---|
| `ur_gui.py` | Complete GUI code (~1700 lines) — all widget construction and event handling |
| `config.py` | All colour, font, spacing, and layout constants — most visual changes happen here |
| `config.cfg` | Optional plain-text config; overrides `config.py` defaults without touching code |
| `ur_extractor.py` | Backend — contains `build_multi_year_tables()` and the HGB mapping logic |
| `lib/hgb_map.py` | HGB canonical accounting map — not UI, but determines what data appears |

The UI/UX expert only needs to work with `ur_gui.py` and `config.py` for visual
and interaction changes. `ur_extractor.py` is only relevant if new data fields
need to be surfaced in the UI.

---

## 10. Questions for the UI/UX Expert

The following decisions have been left open deliberately, as they depend on design
judgment rather than technical constraints:

1. **Split pane vs tabs** — should the preview pane be a tab alongside the table list,
   or should the two-panel layout be kept with a resizable divider?

2. **OVERVIEW prominence** — the OVERVIEW section is the most analytically useful
   output. Should it be surfaced more prominently (e.g. full-screen step after
   processing, rather than the top item in a list)?

3. **Export flow** — should "Export All" be the default prominent action with
   "Export Selected" as a secondary option, or vice versa? Should there be a
   "Recommended export" that intelligently picks OVERVIEW + raw tables?

4. **CAPTCHA UX** — the automated CAPTCHA attempt works ~80% of the time. For the
   remaining 20%, how can the dialog be clearer about what the user needs to do in
   which window?

5. **Progress granularity** — would per-document progress cards (replacing the single
   progress bar) be more informative, or would they add visual noise?

6. **Search vs results phases** — should these be separate "screens" (wizard flow) or
   remain in the same sidebar as they are now?

7. **Empty states** — what should the preview pane show before any table is selected?
   Currently it shows the heading "Table Preview" with an empty Treeview.
