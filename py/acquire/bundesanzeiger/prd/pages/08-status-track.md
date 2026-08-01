# Status Track & Breadcrumb

> **Region:** top bar (full width, ~44 px) + progress bar below · **Module:** Settings & status
> **Generated:** 2026-06-28

## Overview
The persistent top bar. Left side shows a **breadcrumb** of where the analyst is; right
side holds global actions and at-a-glance health chips. A thin progress bar sits directly
beneath it and animates during batch processing.

## Layout
```
┌────────────────────────────────────────────────────────────────────────────┐
│ Active: CTEC I GmbH ▸ 3 filings ▸ Bilanz        ● [Export] Log ⚙ ⚠N items ▸N tables │
└────────────────────────────────────────────────────────────────────────────┘
│██████████░░░░░░░░░░  progress (during batch)                                 │
```

## Elements

### Left — breadcrumb
| Element | Content |
|---------|---------|
| Breadcrumb | "Active: ⟨Company⟩ ▸ ⟨N filings⟩ ▸ ⟨Tab⟩" — updated on company select, tab switch, and batch completion. Shows "Search for a company" / "Starting…" when idle. |

### Right — actions & chips
| Element | Type | Behavior |
|---------|------|----------|
| Bundle dot ● | Status dot | Colour reflects the last feedback-bundle writes; hover shows a tooltip of the last 3 results (✓/✗ + path) |
| **Export** | Button | Opens the [Export dialog](./07-export-dialog.md); enabled after extraction |
| **Log** | Toggle | Shows/hides the debug log drawer (dark console under the grid) |
| ⚙ Settings | Button | Opens the [Settings panel](./06-settings.md) |
| **⚠ N items** | Chip (amber) | Count of line items needing review; click → opens **Needs Review** rail. Hidden when 0 |
| **▸ N tables** | Chip (amber) | Count of tables needing attention; click → **All Tables**. Hidden when 0 |

### Progress bar
Hidden/zeroed when idle. During `process_batch` it animates from `batch_progress` events
("(i/n) Starting FY…", per-step %); on `batch_complete` it resets and the status shows
"✓ N tables extracted".

## Interactions
- The chips appear/disappear based on counts (`_update_review_chips`); both are entry
  points into review workflows.
- The breadcrumb is recomputed by `_update_breadcrumb()` at every navigation event.
- A **captcha pending** indicator surfaces here while the worker awaits a register CAPTCHA.

## API / Backend dependencies
Reflects worker events: `status`, `batch_progress`, `batch_complete`, `need_confirm`,
`bundle_written`, `error`. No direct commands of its own (Export routes through the dialog).

## Page relationships
- **From / To:** always visible; routes to Export dialog, Settings, Needs Review, All Tables.
- **Data coupling:** chip counts derive from the active company's review state; progress
  reflects the worker's batch.

## Business rules
- Review chips are hidden at zero (no empty-state noise).
- The bundle dot turns amber if any of the last feedback-bundle writes failed.
