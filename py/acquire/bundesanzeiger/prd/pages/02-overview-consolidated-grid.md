# OVERVIEW — Consolidated Multi-Year Grid

> **Canvas state:** `overview` · **Outer tab:** OVERVIEW · **Inner tabs:** Bilanz / GuV / Cashflow
> **Module:** Consolidation · **Generated:** 2026-06-28

## Overview
The core deliverable screen. It shows one statement (Balance sheet, P&L, or Cash flow)
as a **year-over-year grid**: rows are canonical line items, columns are fiscal years.
It is synthesised from all the company's extracted tables of that statement type, joined
by canonical row identity. The analyst reviews figures, drills into any cell's source,
adjusts which tables feed the view, and merges differently-named rows.

## When a user is here
After a batch completes, or when selecting an already-processed company. It is the
default working surface for analysis and export.

## Layout
```
 OVERVIEW | All Tables                         (outer tabs)
 Bilanz   GuV   Cashflow                        (inner tabs = statement type)
┌───────────────────────────────────────────────────────────────┐
│ Source Label(s) | Canonical | std_id | 2024 | 2023 | 2022 |…   │  ttk.Treeview
│ Geschäfts- oder…| Goodwill  | …      | 1.92 | 1.92 | 1.93 |     │  (financial grid)
│ …                                                              │
└───────────────────────────────────────────────────────────────┘
 (debug log drawer, collapsed)
```
Rendered with a `ttk.Treeview` styled via design tokens. The right rail (Audit / Picker)
opens alongside on demand.

## Columns
| Column | Content | Notes |
|--------|---------|-------|
| **Source Label(s)** | The raw German label(s) as they appeared across years, distinct values joined by " / "; line items indented | Primary description column |
| **Canonical** | HGB canonical name (`name_de`) via `hgb_map.lookup` when the label resolves to exactly one position | Blank for unmapped / section headers |
| **std_id** | The canonical HGB code (e.g. `BS-A.B.II.1`) | Hidden by default; toggle in Settings ("Show std_id column") |
| **Year columns** | One per fiscal year, most-recent first, with the currency unit in the header (e.g. "2024 (TEUR)") | Negative values rendered in parentheses |

Row visual types (drive shading/weight): **section header** (memo / ALL-CAPS),
**subtotal** (bold, tinted), **line item** (indented, alternating tint). The type is
derived from the canonical record's `row_type` (`subtotal` / `memo` / `line`) and a
fallback heuristic.

## Interactions

### Page load / tab switch
Selecting OVERVIEW or an inner tab calls `_draw_financial_grid(stmt_type)`:
- Reads the consolidated table for that statement type from `active_company.overview_tables`.
- Builds columns (3 meta columns + N year columns) and rows; clicking a year header opens
  the **source picker** for that statement.
- If none exists: "No data available for this statement type".

### Drill into a cell → Audit
- **Trigger:** click a **year cell** (not a meta column; suppressed during multi-select).
- **Behavior:** opens the right rail in **Audit** mode for that (row label, year, value),
  resolving the source filing/table and the HGB mapping. See
  [04-right-rail.md](./04-right-rail.md#audit).

### Edit which tables feed the consolidation → Source Picker
- **Trigger:** click a **year column header**, or right-click → **"Edit consolidation sources…"**.
- **Behavior:** opens the right rail **Picker** listing every table of this statement type
  with include/exclude switches. Toggling persists and rebuilds the grid live. See
  [04-right-rail.md](./04-right-rail.md#sources-picker).

### Merge two differently-named rows
- **Trigger:** Ctrl/Shift-click ≥2 rows → right-click → **"Merge N rows — keep name…"** →
  choose which row's label to keep.
- **Behavior:** the chosen rows collapse onto one consolidated line (e.g. "Erlöse" +
  "Umsatzerlöse"); persisted per company in `row_merges.csv` and re-applied automatically.
  **"Unmerge selected row(s)"** dissolves a merge group.
- **Keep-name rule:** the merged row keeps its *position* from first appearance but takes
  its *displayed label* from the chosen (kept/target) row.

### Context menu (right-click anywhere on the grid)
| Item | Behavior |
|------|----------|
| Edit consolidation sources… | Opens the Picker for the active statement |
| Merge N rows — keep name… ▸ | Sub-menu of the selected rows; pick the label to keep |
| Unmerge selected row(s) | Removes merges the selected rows participate in |
| Add note… | Disabled (Phase 5 placeholder) |

### Export
The top **Export** button opens the [Export dialog](./07-export-dialog.md); the current
company's `overview_tables` (and raw tables) are the source.

## How the grid is built (business logic)
Consolidation is `build_multi_year_tables()` (see
[../appendix/backend-pipeline.md](../appendix/backend-pipeline.md#consolidation)). Key
rules the analyst sees the effect of:
- **One grid per statement type** when ≥2 source tables and ≥2 distinct years exist.
- **Full outer-join of rows** across all contributing tables — a line one filing reports
  and another omits is kept (blank where absent), never dropped.
- **Within-year join** — if a balance sheet is split across two tables (Aktiva on one,
  Passiva on another), both feed the same year column instead of overwriting.
- **Only included tables feed it** — exclude a table in the Picker/All Tables and it
  drops out; re-classify a table to this statement type and it joins in.
- **Row identity** uses a canonical key with built-in synonyms (e.g. Jahresüberschuss /
  Jahresfehlbetrag → one line) plus the analyst's saved row-merges.

## API / Backend dependencies
| Worker command | Trigger | Emits |
|----------------|---------|-------|
| `recompute_overview` | Any correction that recomputes async (reclassify, include/exclude, bulk) | `overview_ready`, `bundle_written` |

Synchronous rebuilds (row-merge, picker toggle) call `build_multi_year_tables()` directly
on the GUI thread and redraw.

## Page relationships
- **From:** Search (after batch), left-rail company select, All Tables (re-segmentation
  feeds it).
- **To:** Right rail (Audit / Picker), Export dialog, All Tables.
- **Data coupling:** reads `overview_tables`; corrections write override/row-merge stores
  and trigger a rebuild + Library auto-save.

## Business rules
- Currency unit is a **display-only** suffix in headers (Settings); it does not convert values.
- Negative numbers are shown in parentheses.
- The `std_id` column is hidden unless enabled in Settings.
