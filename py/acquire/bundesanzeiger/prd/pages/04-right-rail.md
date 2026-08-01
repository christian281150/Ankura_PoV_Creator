# Right Rail — Audit · Preview · Sources Picker · Needs Review

> **Region:** right column (320 px; ~600 px in Preview) · **Modes:** 4
> **Module:** Consolidation / Table workbench · **Generated:** 2026-06-28

## Overview
A single right-hand panel reused for four purposes. It is opened with
`_open_right_rail(mode, data)` and fully **replaces** its previous content on each open
(a fixed border line is preserved). Mouse-wheel scrolling is routed to every child so the
panel scrolls regardless of cursor position. Closing it (✕) restores the normal layout.

The four modes:

| Mode | Opened from | Purpose |
|------|-------------|---------|
| **Audit** | Click a value cell in OVERVIEW | Trace one figure to its source + HGB mapping |
| **Preview** | Click a table row in All Tables (or a Picker "Preview") | Read a raw extracted table in full |
| **Sources Picker** | Year header / right-click in OVERVIEW | Choose which tables feed a statement's consolidation |
| **Needs Review** | "⚠ N items" status chip | Resolve unmapped/ambiguous labels |

---

## Audit
> Anchor: `audit`

**Trigger:** click a year **value cell** in the OVERVIEW grid.

**Content (cards, top→bottom):**
- **RAW LABEL** — the source German label of the clicked row.
- **VALUE** — the clicked cell's value.
- **HGB MAPPING** — `hgb_map.lookup(label)` result:
  - *single match* → the canonical `std_id` (e.g. `BS-A.B.II.1`), canonical English name,
    and a confidence dot (high for exact/normalized).
  - *ambiguous (>1 candidate)* → lists candidates, each with a **Remap** button.
  - *no match* → "No HGB match found".
- **SOURCE** — the originating filing: company, fiscal year · doc type, date filed, page
  range, and an **Open PDF** button.

**Interactions:**
- **Remap** (ambiguous case) → writes a client alias mapping the raw label to the chosen
  `std_id` (`_remap_label` → `client_aliases.csv`) and refreshes the grid.

The source filing/table is resolved by matching the clicked year to the company's
`doc_sections` and the active statement type (override-aware).

---

## Preview
> Anchor: `preview`

**Trigger:** click a table row in **All Tables**, or **Preview** on a Picker card.

**Behavior / layout:** Preview gets a **roomy** panel — the **left company rail collapses**
and the right rail widens to ~600 px ("shift-left" layout); closing restores the
3-column layout. The table is rendered as a read-only `ttk.Treeview` (description column
stretches), preceded by a type badge and the filing label. Header row supplies column
titles; all data rows shown (clamped 4–30 visible, internal scroll if longer).

---

## Sources Picker
> Anchor: `sources-picker`

**Trigger:** click a **year column header** in OVERVIEW, or right-click → **"Edit
consolidation sources…"**. Scoped to the **active inner tab** (statement type).

**Content:** a hint ("Tick the tables that should feed this consolidated view. Changes are
saved and re-applied on the next extraction.") then one card per candidate table —
candidates are `all_tables` whose **effective type** equals the active statement:

| Element | Content |
|---------|---------|
| Include switch | On = this table feeds the consolidation |
| Heading | Short heading |
| Meta | doc label · year(s) · page range · row count |
| Preview | Opens this table in Preview mode |

**Interactions:**
- Toggling a switch sets `_include_in_overview`, **persists** the override
  (`save_table_override` with the table's current type), rebuilds the consolidation
  synchronously, and redraws the grid — and auto-saves the company to the Library.
- Empty state: "No tables of this type were found."

---

## Needs Review
> Anchor: `needs-review`

**Trigger:** the **"⚠ N items"** chip in the status track.

**Purpose:** lists labels the canonical mapping could not resolve (match type `none`) or
that were **ambiguous** (>1 candidate). Per item the analyst can:
- **Resolve** to a candidate `std_id`, or
- type a `std_id` manually,

which writes a **client alias** (`client_aliases.csv`, "resolved_via_review_ui") and
recomputes the review list. This is the mechanism that drives the unmapped queue toward
zero over time. The review list is computed by `_compute_review_list()` over the
company's tables using `hgb_map.lookup`.

---

## Header (all modes)
A title (mode-specific, e.g. "Audit", "Sources — Bilanz", "Needs Review (N)") and a ✕
close button. Closing calls `_close_right_rail()` which collapses column 2 and restores
the left rail.

## API / Backend dependencies
- **Audit / Review** read `hgb_map.lookup` / `by_id` (local, in-process; no network).
- **Picker** writes overrides and triggers `recompute_overview` (or a synchronous rebuild).
- **Open PDF** opens the local downloaded file.

## Page relationships
- **From:** OVERVIEW (Audit, Picker), All Tables (Preview), status chip (Review).
- **To:** Preview can be opened from the Picker; Remap/Resolve refresh the OVERVIEW grid.
- **Data coupling:** writes `client_aliases.csv` (Audit/Review) and `table_overrides.csv`
  (Picker); both feed back into the consolidation.
