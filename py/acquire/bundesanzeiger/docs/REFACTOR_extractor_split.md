# Refactor plan — split `ur_extractor.py` into an `extractor/` package

> Status: **proposed** (follow-up; not yet executed). Owner decision: do this as
> its own reviewed change, separate from the hygiene pass.

## Why
`ur_extractor.py` is ~3,580 lines of **37 top-level public functions** plus
helpers spanning five unrelated concerns (browser scraping, PDF parsing,
classification, consolidation, export, persistence). It's the highest-ROI,
lowest-risk module to break up because it's a flat collection of functions, not
one giant class (unlike `ur_gui.py`, which we deliberately leave intact).

## Hard constraint — keep the public import surface stable
`ur_gui.py` imports a fixed set of 37 symbols from `ur_extractor` (incl. some
private ones: `_classify_table`, `_minimize_all_browsers`, `_get_browser_hwnds`,
`_hide_hwnds`, `_minimize_hwnds`, `_normalize_for_override_key`,
`_OVERRIDES_PATH`). `dev/dev_test.py` also imports internals
(`_parse_num_cell`, `_acct_indent`, `_acct_bold`, `_has_financial_content`).
`build.bat` / `UR_Extractor.spec` reference the module by name.

**Therefore the migration must not change any caller.** We achieve that with a
**re-export shim**: `ur_extractor.py` becomes a thin module that re-exports the
package's API, so every existing `import ur_extractor` / `from ur_extractor
import (...)` keeps working untouched. The internal refactor is invisible to the
rest of the app and the build.

## Target layout
```
extractor/
├── __init__.py        # re-exports the full public API (browser, pdf, classify,
│                      #   consolidate, exporters, stores, util)
├── util.py            # State, console, sanitize_filename, _parse_num_cell,
│                      #   _acct_indent, _acct_bold, _has_financial_content
├── browser.py         # launch_browser, run_search, select_document,
│                      #   open_document, download_pdf, window mgmt
│                      #   (_minimize_all_browsers, _get/_hide/_minimize_hwnds);
│                      #   re-exports BASE_URL + *_TIMEOUT from config
├── pdf_extract.py     # extract_tables_from_pdf, _extract_heading,
│                      #   _heuristic_word_extraction, _pin_key_tables
├── classify.py        # _classify_table, _classify_stmt_name, effective_table_type
├── consolidate.py     # build_multi_year_tables, _canonical_row_key, _ROW_SYNONYMS
├── exporters.py       # export_to_csv, export_to_excel, export_to_excel_v2,
│                      #   _derive_audit_rows
└── stores.py          # persistence: table overrides + row-merges + library +
                       #   alias/queue paths (load/save/apply/make_* / library_*)
```
`ur_extractor.py` (kept at root) shrinks to:
```python
"""Back-compat facade. Real code lives in the `extractor` package."""
from extractor import *                      # noqa: F401,F403
from extractor import (                      # explicit re-export of the names
    _classify_table, _minimize_all_browsers, _get_browser_hwnds, _hide_hwnds,
    _minimize_hwnds, _normalize_for_override_key, _OVERRIDES_PATH,
    _parse_num_cell, _acct_indent, _acct_bold, _has_financial_content,
)
if __name__ == "__main__":
    from extractor.__main__ import main; main()
```

## Dependency direction (no cycles)
```
util  ← (everyone)
config ← browser
util ← pdf_extract ← classify ← consolidate
util ← exporters   (uses hgb_map for the audit sheet)
util ← stores
```
`classify` is imported by `consolidate`, `pdf_extract`, and the GUI; keep it
dependency-light (only `re`/`util`). `stores` depends on nothing but stdlib +
`util`. No module imports `browser` except the GUI worker, so Playwright stays
isolated (faster non-GUI imports for tests).

## Step-by-step (each step independently verifiable)
1. Create `extractor/` with empty modules + `__init__` re-exporting the current
   `ur_extractor` names (temporarily `from ur_extractor import *`).
2. Move **`util`** first (no deps), then **`stores`**, **`classify`**,
   **`consolidate`**, **`pdf_extract`**, **`exporters`**, **`browser`** — one
   module per commit; fix intra-package imports as you go.
3. Flip `__init__` to import from the new modules; convert `ur_extractor.py` to
   the shim above; add `extractor/__main__.py` for the CLI entry.
4. Move the module-level path constants (`_OVERRIDES_PATH`, `_ROW_MERGES_PATH`,
   `library_dir`, alias/queue paths) with `stores`; keep them resolving to the
   same `data/`, `aliases/`, `reviews/`, `library/` locations (the
   `Path(__file__).parent` base changes from root to `extractor/`, so anchor
   paths on the **project root**, not the module file).
5. Regenerate `lib/hgb_map.py` import in `exporters`/audit if needed (it imports
   `lib.hgb_map`, unaffected).

## Verification gates
- `python -c "import ur_extractor, ur_gui, extractor"` — clean.
- `python -c "from ur_extractor import (<the 37 symbols>)"` — clean (proves the
  shim preserves the surface).
- `python dev/dev_test.py` unit cases pass (they import internals).
- `build.bat` produces the exe; smoke-launch it.
- Diff is **moves + a shim**, no logic edits — review by file-moved, not line.

## Risks / watch-outs
- **Path anchoring** (step 4) is the only real trap: several stores derive paths
  from `Path(__file__).parent / "data"`. After the move that would point at
  `extractor/data`. Anchor on the project root (e.g. a `util.PROJECT_ROOT`) so
  `data/`, `aliases/`, `reviews/`, `library/` keep resolving as today (and the
  frozen-exe `library_dir()` next-to-exe logic is unchanged).
- **Frozen build:** ensure `UR_Extractor.spec` picks up the new `extractor`
  package (PyInstaller follows imports, so the shim import is enough; verify).
- Keep the shim until a later, separate change migrates `ur_gui.py` to import
  from `extractor` directly and deletes the facade.

## Effort
~half a day, mechanical and fully testable behind the shim. `ur_gui.py` is out
of scope (single large Tk class — defer; if ever split, do it via area mixins,
not file surgery).
