# Export Options Dialog

> **Region:** modal dialog · **Module:** Output · **Generated:** 2026-06-28

## Overview
A small modal opened by the **Export** button (status track). It lets the analyst choose
*what* goes into the Excel workbook — scope and which statements — before picking a save
location. Replaces a one-click "export everything" with controllable output.

## When a user is here
After working up a company, to produce the deliverable Excel model. Export is enabled only
once a company has consolidated or raw tables.

## Layout
```
┌──────────────────────────────────────┐
│  Export to Excel                      │
│  WHAT TO EXPORT                       │
│  [ Everything            ▾ ]          │  scope dropdown
│  STATEMENTS                           │
│  [x] Bilanz [x] GuV [x] Cashflow [x] Other │  toggles
│                       [ Cancel ] [ Export ] │
└──────────────────────────────────────┘
```

## Fields
| Field | Type | Options | Default | Notes |
|-------|------|---------|---------|-------|
| Scope | Dropdown | **Consolidation only** · **Raw tables only** · **Everything** | Everything | Chooses which sheets are produced |
| Statements | Checkboxes | Bilanz · GuV · Cashflow · **Other** | all on | Filters which statement types are included |

- **Other** (type 99) only affects raw tables (notes/Anhang); there is no consolidated
  "Other" view. It defaults **on** so "Everything"/"Raw" export the full set.

## Interactions

### Export
- **Trigger:** **Export** button.
- **Validation:** if **no** statement is ticked → an info message ("Select at least one
  statement to export.") and the dialog stays open (no silent no-op).
- **Behavior:** filters the company's `overview_tables` and raw `all_tables` by the chosen
  scope + statement set, then opens a **Save As** file dialog (default filename tagged by
  scope, e.g. `Company_…_consolidation.xlsx`). On confirm, sends `export_v2` to the worker.
- **Nothing matches:** "Nothing to export for the chosen options."

### Scope → output mapping
| Scope | Overview sheets | Raw per-table sheets |
|-------|-----------------|----------------------|
| Consolidation only | yes (filtered) | none |
| Raw tables only | none | yes (filtered) |
| Everything | yes (filtered) | yes (filtered) |

### Cancel
Closes without exporting.

## API / Backend dependencies
| Worker command | Payload | Backend | Emits |
|----------------|---------|---------|-------|
| `export_v2` | overview tables, raw tables, result meta, out path, decimal/thousand sep, pdf dir, review meta | `export_to_excel_v2()` | `status`, `exported(count, path)` |

The workbook contains: one sheet per OVERVIEW (multi-year) table, one sheet per raw
per-year table, and a **Mapping Audit** sheet (raw label → std_id → canonical → match type
→ year → company). On completion the GUI shows "Exported N sheet(s) to: …".

## Page relationships
- **From:** Export button (status track), enabled after extraction.
- **To:** returns to the active screen; produces an `.xlsx` file on disk.
- **Data coupling:** reads the active company's `overview_tables` + `all_tables` and the
  Needs-Review list (for the audit sheet).

## Business rules
- Number format (German/English separators) comes from Settings.
- Currency unit is **not** applied to the exported numbers (it is a display-only header
  suffix in the GUI).
