# Appendix — Screen Relationships

How the analyst moves between screens and how data couples them.

## Navigation map
```
                         ┌─────────────────────────────┐
                         │  Left rail (always visible)  │
                         │  New Searches  +  Library    │
                         └───────────┬─────────────────┘
            select empty / +         │      select company w/ tables / open Library
                  ▼                  │                 ▼
        ┌───────────────┐            │        ┌────────────────────────────┐
        │ 1. Search &   │  batch     │        │ 2. OVERVIEW consolidated   │
        │    Batch      ├────────────┴───────▶│    grid (Bilanz/GuV/CF)    │
        └───────────────┘ complete            └───┬───────────┬────────────┘
                                                  │           │
                       click value cell           │           │ year header /
                       ▼                           │           │ right-click "sources"
              ┌─────────────────┐                  │           ▼
              │ 4. Right rail   │◀── "⚠ items" ────┤   ┌──────────────────┐
              │  Audit/Review   │   (status chip)  │   │ 4. Right rail    │
              └─────────────────┘                  │   │  Sources Picker  │
                                                   │   └────────┬─────────┘
                  outer tab "All Tables" /         │            │ Preview
                  "▸ N tables" chip                ▼            ▼
                                          ┌────────────────┐  ┌─────────────────┐
                                          │ 3. All Tables  │─▶│ 4. Right rail   │
                                          │   workbench    │  │   Preview       │
                                          └────────────────┘  └─────────────────┘

   Top bar (8. Status track):  Export ▶ 7. Export dialog · ⚙ ▶ 6. Settings · Log drawer
```

## Inbound / outbound per screen
| Screen | Reached from | Leads to |
|--------|--------------|----------|
| 1 Search & Batch | launch, left-rail **+**, selecting an empty company | OVERVIEW (after batch) |
| 2 OVERVIEW grid | Search (batch complete), company select, All Tables corrections | Right rail (Audit/Picker), Export dialog, All Tables |
| 3 All Tables | OVERVIEW outer tab, "▸ N tables" chip | Right rail Preview; corrections rebuild OVERVIEW |
| 4 Right rail | OVERVIEW (Audit/Picker), All Tables (Preview), "⚠ items" chip (Review) | Preview from Picker; Remap/Resolve refresh OVERVIEW |
| 5 Company rail | always visible | Search or OVERVIEW |
| 6 Settings | gear (any screen) | back to active screen (may redraw grid) |
| 7 Export dialog | Export button | `.xlsx` on disk |
| 8 Status track | always visible | Export dialog, Settings, Review rail, All Tables |

## Data coupling (cross-screen refresh)
| Action on screen | Persists to | Triggers |
|------------------|-------------|----------|
| Batch complete (1) | Library snapshot | OVERVIEW rebuild, review recompute, Export enabled |
| Include/exclude or reclassify a table (3 / Picker 4) | `table_overrides.csv` (+ feedback bundle) | `recompute_overview` → OVERVIEW redraw + Library auto-save |
| Bulk re-segment (3) | `table_overrides.csv` (per table) | one `recompute_overview` |
| Merge / unmerge rows (2) | `row_merges.csv` | synchronous rebuild + redraw + Library auto-save |
| Remap (Audit 4) / Resolve (Review 4) | `client_aliases.csv` | grid refresh, review chip recount |
| Settings currency / std_id (6) | user prefs JSON | OVERVIEW redraw |
| Any correction | Library snapshot (debounced) | left-rail counts update |

## Shared regions (not separate screens)
- **Outer tabs** (OVERVIEW / All Tables) and **inner tabs** (Bilanz / GuV / Cashflow)
  switch the center canvas and active statement; the inner-tab accent is carried by the
  outer tab's indigo stripe.
- **Debug log drawer** — dark console under the grid, toggled by the **Log** button.
- **Modals/drawers** (Export dialog, Settings panel, the four right-rail modes) are
  documented with their triggering screen, per PRD convention.
