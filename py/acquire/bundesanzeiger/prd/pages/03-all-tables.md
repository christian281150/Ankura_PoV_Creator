# All Tables — Workbench

> **Canvas state:** `all_tables` · **Outer tab:** All Tables · **Module:** Table workbench
> **Generated:** 2026-06-28

## Overview
A complete, inspectable list of **every table extracted** for the active company,
grouped into collapsible **statement-type → fiscal-year** segments. This is where the
analyst verifies extraction, re-classifies mis-typed tables, includes/excludes tables
from the consolidation, and previews raw table content. Because the consolidation groups
tables by their *effective type*, the segmentation here **is** the consolidation input.

## When a user is here
- To check why a number is missing/odd in OVERVIEW (find the source table).
- To fix classification (e.g. a balance sheet table extracted under "Sonstige").
- To bulk-move several tables into a statement type at once.

## Layout
```
 OVERVIEW | All Tables
┌──────────────────────────────────────────────────────────┐
│ [ N selected   Set type ▾   Clear ]   (bulk bar, shown    │  bulk action bar
│                                        when ≥1 ticked)     │  (hidden otherwise)
├──────────────────────────────────────────────────────────┤
│ ▾ Bilanz (9)                                              │  type section header
│    ▾ FY2024 (2)                                           │  year sub-header
│       ☐  Konzernbilanz        12r  [Bilanz]  ✓            │  table row
│       ☐  31.12.2024 31.12.2023 …                          │
│    ▸ FY2023 (1)                                           │  (collapsed)
│ ▾ GuV (1) …                                               │
│ ▾ Sonstige (… ) …                                         │
└──────────────────────────────────────────────────────────┘
```

## Fields

### Segment headers
| Element | Content | Behavior |
|---------|---------|----------|
| Type header | "Bilanz / GuV / Cashflow / Sonstige (count)" with chevron | Click to collapse/expand the whole type |
| Year sub-header | "FY#### (count)" with chevron | Click to collapse/expand that year within the type |

Grouping uses `effective_table_type(t)` — the **manual override wins** over the automatic
classifier, so re-typing a table immediately moves it to the right segment.

### Table row (per extracted table)
| Element | Content | Notes |
|---------|---------|-------|
| Selection checkbox | ☐ / ☑ | Ctrl-click the row also toggles; selected rows highlighted |
| Heading | Short heading of the table | From `heading` / first rows |
| Row count | "Nr" (data rows) | `len(rows) - 1` |
| Type badge | Bilanz / GuV / Cashflow / **Sonstige (amber)** | Effective type; amber = workflow-attention "Other" |
| In-overview badge | ✓ included · — excluded · ✓* overridden | Whether this table feeds the consolidation |

## Interactions

### Collapse / expand
Clicking a type or year header toggles its `_at_collapsed[key]` state and re-renders the list.

### Preview a table
- **Trigger:** plain left-click on a table row.
- **Behavior:** opens the right rail in **Preview** mode (roomy, left rail collapses).
  See [04-right-rail.md](./04-right-rail.md#preview).

### Right-click a single table
| Item | Behavior |
|------|----------|
| Preview | Open preview |
| Set type ▸ (Bilanz / GuV / Cashflow / Other) | Re-classify just this table (persists override, recomputes overview) |
| Include / Exclude from overview | Toggle whether it feeds consolidation (persists, recomputes) |
| Add note… | Disabled (Phase 5) |
| Open PDF | Open the source PDF (if path known) |

### Bulk re-segmentation
- **Select:** tick checkboxes (or Ctrl-click rows). A **bulk action bar** appears at the
  top: "**N selected**", **Set type ▾**, **Clear**.
- **Set type ▾:** choose Bilanz / GuV / Cashflow / Other → applies to *all* selected
  tables at once, persists each override, runs **one** overview recompute, and re-renders
  so the tables jump into their new segment together.
- Selection is per-company (cleared on company switch) and self-prunes if tables change.

### Effect on the consolidation
- Re-typing tables to **Bilanz** pulls them into the Bilanz OVERVIEW for their years.
- Excluding a table removes it from its statement's OVERVIEW.
- Both are remembered in `data/table_overrides.csv` and re-applied on re-extraction.

## API / Backend dependencies
| Worker command | Trigger | Emits |
|----------------|---------|-------|
| `recompute_overview` | Single or bulk re-classify, include/exclude toggle | `overview_ready` (+ `bundle_written` on single reclassify) |

Each correction also writes a record via `save_table_override()` and (for reclassify) a
**feedback bundle** via `write_feedback_bundle()`.

## Page relationships
- **From:** OVERVIEW outer tab, the "▸ N tables" status chip.
- **To:** Right rail Preview; corrections flow back into OVERVIEW.
- **Data coupling:** reads `all_tables`; writes `table_overrides.csv`; triggers overview
  rebuild + Library auto-save.

## Business rules
- Tables classified as **Sonstige (99)** never feed any consolidation; re-type them to
  include them.
- The type badge and segment always reflect *effective* type (override-aware).
- A bulk reclassify is a single recompute (not one per table) for responsiveness.
