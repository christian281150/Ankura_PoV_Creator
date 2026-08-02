# Settings Panel

> **Region:** slide-over panel from the right (440 px) · **Module:** Settings
> **Generated:** 2026-06-28

## Overview
A slide-over panel (gear icon in the status track) for app-wide preferences: theme,
currency display, Excel number format, folders, logging, and grid columns. Settings
persist to a user preferences file and apply immediately where relevant.

## Layout
A scrollable panel with a header (⚙ Settings + ✕), grouped sections, and a sticky
**Save & Close** button at the bottom.

## Fields (by section)

### THEME
| Field | Type | Options | Default | Effect |
|-------|------|---------|---------|--------|
| Appearance | Segmented | Light / Dark | Light | Switches the whole palette at runtime (re-styles the grid) |

### CURRENCY DISPLAY
| Field | Type | Options | Default | Effect |
|-------|------|---------|---------|--------|
| Unit in column headers | Dropdown | TEUR · €k · €'000 · €m · none | TEUR | **Display-only** suffix in OVERVIEW year headers; does not convert values |

### NUMBER FORMAT
| Field | Type | Options | Default | Effect |
|-------|------|---------|---------|--------|
| Excel output format | Segmented | German / English | German (comma decimal) | Sets decimal/thousand separators used by the Excel exporter |

### PDF DOWNLOAD FOLDER
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| Folder path | Text + **Browse** | `~/Downloads/UR_Extracts` | Where filing PDFs are downloaded |

### SESSION LOG FOLDER
| Field | Type | Default | Notes |
|-------|------|---------|-------|
| Save PDF & Log files together | Switch | On | When on, logs go under the PDF folder's `logs/` |
| Log folder path | Text + **Browse** | `<pdf>/logs` | Used when the toggle is off |
| Delete log on close | Switch | Off | Removes the session log when the app closes |

### OVERVIEW COLUMNS
| Field | Type | Default | Effect |
|-------|------|---------|--------|
| Show std_id column | Switch | Off | Reveals the canonical-code column in the OVERVIEW grid |

## Interactions

### Open / close
The gear icon opens the panel (slides in from the right, overlaying the right side). ✕ or
**Save & Close** closes it.

### Save & Close
Persists all values via `_save_user_prefs(...)` (theme, folders, decimal sep, currency
unit, log options, `show_std_id`). If the OVERVIEW is showing, the grid is redrawn to
reflect currency / std_id changes immediately.

## API / Backend dependencies
None external. Reads/writes a local user-prefs JSON (loaded at startup into `_USER_PREFS`).

## Page relationships
- **From:** status track gear icon (any screen).
- **To:** returns to whatever screen was active.
- **Data coupling:** currency unit + std_id toggle change the OVERVIEW grid rendering;
  number format changes the Excel export; folder settings change where PDFs/logs are written.

## Business rules
- Theme defaults to **Light**.
- Currency unit is cosmetic only — no figure is recomputed.
- German number format = comma decimal / dot thousands; English = the reverse.
