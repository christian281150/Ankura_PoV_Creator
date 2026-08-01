# Company Rail & Library

> **Region:** left column (240 px) · **Module:** Company workspace · **Generated:** 2026-06-28

## Overview
The left rail is the workspace switcher. It has two sections: **New Searches**
(companies worked on in the current session) and **Library** (companies saved on disk).
The Library is what lets the analyst close the program and reopen the exact same
worked-up data — extracted tables, corrections, and consolidation — without
re-downloading.

## Layout
```
 Companies                          +     (header + add-company)
 NEW SEARCHES                             (section 1, this session,
   CTEC I GmbH, Plochingen        ●        most-recent first)
   3 filings · 114 tables
 LIBRARY                                  (section 2, saved snapshots,
   ACME AG                                 alphabetical)
   2026-06-28 · 41 tables
   CTEC I GmbH                · open
   2026-06-28 · 114 tables
```

## Fields

### Header
| Element | Behavior |
|---------|----------|
| "Companies" label | Static title |
| **+** | Add a new (empty) company slot and switch to the Search screen |

### NEW SEARCHES rows (this session)
| Element | Content |
|---------|---------|
| Name | Company name (or "(Searching…)" placeholder) |
| Active stripe | Indigo stripe + bold when this is the active company |
| Subtitle | "N filings · N tables" |
| Review dot | Amber ● if the company has unresolved review items |

Sorted **most-recent first** (reverse of insertion).

### LIBRARY rows (saved on disk)
| Element | Content |
|---------|---------|
| Name | Saved company name |
| Subtitle | "saved-date · N tables" (+ "· open" if already loaded this session) |

Sorted **alphabetically**. Read from a lightweight `library/index.json` so the rail does
not parse every (multi-MB) snapshot on each refresh.

## Interactions

### Select a company (New Searches)
- **Trigger:** click a company row.
- **Behavior:** sets it active, clears any All-Tables bulk selection, and either shows
  its **OVERVIEW** (if it has tables; rebuilds the consolidation) or the **Search** screen
  (if empty). Updates breadcrumb and review chips.

### Open a Library entry
- **Trigger:** click a Library row.
- **Behavior:** if that company is already in this session, just selects it; otherwise
  loads the snapshot from disk (`load_library_company`), assigns a fresh id if needed,
  adds it to the session, and selects it (rebuilds OVERVIEW from the restored tables).

### Library row context menu (right-click)
| Item | Behavior |
|------|----------|
| Open | Same as click |
| Delete from library… | Confirms, then deletes the snapshot file and prunes the index (the current session stays) |

### Auto-save (no button)
A company is **auto-saved to the Library** after extraction and after every correction
(exclude/include, reclassify, picker toggle, row-merge). To keep the UI responsive the
save is **debounced (~1.5 s)** and the file write runs **off the UI thread** (the snapshot
is taken on the main thread for a consistent read). A pending save is flushed
synchronously on app close. Unnamed / "(Searching…)" placeholders are skipped.

## Storage
- Library folder: **next to the executable** when packaged (`library/`), else the source
  directory.
- One JSON snapshot per company; filename = normalized name + short hash of the full name
  (so two distinct companies that normalise to the same key cannot overwrite each other;
  the same name updates in place).
- `library/index.json` holds `{name, saved_at, n_filings, n_tables}` per file for fast
  listing. See [../appendix/data-schemas-and-mapping.md](../appendix/data-schemas-and-mapping.md#library).

## Page relationships
- **From:** every screen (always visible, except collapsed during Preview).
- **To:** Search (new/empty company) or OVERVIEW (company with tables).
- **Data coupling:** selecting/loading a company drives the whole center+right area;
  corrections elsewhere update this rail's counts and trigger auto-save.

## Business rules
- The same company name maps to one Library file (idempotent updates).
- Selecting a company is per-session; deleting from Library does not remove the
  in-session copy.
