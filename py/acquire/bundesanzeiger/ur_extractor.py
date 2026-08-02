"""
ur_extractor.py — back-compat facade for the ``extractor`` package.
==========================================================================

The backend was split into a package (``extractor/``) for readability:

    extractor/_core        shared imports, console, HGB handle, State, helpers
    extractor/browser      register session, search, document download, CLI
    extractor/extract      PDF table extraction + statement classification
    extractor/consolidate  multi-year consolidation (build_multi_year_tables)
    extractor/exporters    CSV / Excel exporters + mapping-audit sheet
    extractor/stores       overrides, row-merges, feedback bundles, library
    extractor/cli          interactive command-line entry point

This module is kept so existing callers (``from ur_extractor import …`` in
ur_gui.py and the dev tests) and the packaged build keep working unchanged.
New code should import from ``extractor`` directly.
"""

# Re-export the package's full legacy surface. `extractor.__all__` lists every
# name callers historically imported from ur_extractor — public functions plus
# the internals used by name in ur_gui.py / dev/dev_test.py (e.g. _classify_table,
# _parse_num_cell, _OVERRIDES_PATH) — and deliberately omits the submodule
# objects, so this star-import stays clean.
from extractor import *                                    # noqa: F401,F403

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())                                    # noqa: F405
