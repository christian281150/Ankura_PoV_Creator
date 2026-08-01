# WORKING_PLAN.md — Unternehmensregister Financial Extractor UI Redesign v2
*Phase 0 deliverable — reconnaissance & plan, no code changes*

---

## 1. Mental-model confirmation (7 bullets)

1. **The OVERVIEW (multi-year aligned statements) is the primary canvas tab**, scoped to the active company. After extraction it is the default view. The center canvas has two tabs; OVERVIEW is always shown first.
2. **The "All Tables" tab** is the secondary canvas tab, one click away. It shows every extracted table for the active company — with a classification badge (Bilanz / GuV / CF / Other) and an OVERVIEW status badge (✓ included / ⊘ excluded). Right-click on any row opens a context menu for reclassification.
3. **Per-year individual tables are visible in the All Tables tab AND drillable from OVERVIEW cells.** Three paths to source data: OVERVIEW grid (95% of uses), All Tables tab (~20%), cell drill-down to right rail (~5%).
4. **Selection is implicit.** Auto-classified tables feed OVERVIEW automatically. Exceptions (ambiguous HGB labels, tables classified as "Other" or low-confidence) are flagged — never silently dropped.
5. **Two correction loops, both persisted:**
   - *Line-item loop:* ambiguous/unmatched label → user picks `std_id` → written to `aliases/client_aliases.csv`
   - *Table loop:* wrong auto-class → user right-clicks and reclassifies → written to `data/table_overrides.csv`; applied automatically on next extraction of the same filing
6. **Sessions are multi-company.** Each company has its own OVERVIEW. No cross-company consolidation. Switching companies in the left rail re-renders the canvas for that company without losing other companies' data.
7. **Three zones: left rail (company list + filings) · center canvas (OVERVIEW or All Tables) · right rail (cell audit drill-down or review queue).** Left rail and status track are continuous across all phases; center canvas morphs.

---

## 2. Current `ur_gui.py` structure map

The current file is **2 109 lines** (just written in this session — a partial v1 implementation).

| Lines | Section | Status vs v2 |
|---|---|---|
| 1–35 | Module docstring — event/command contracts | Needs updating (new events: `recompute_overview`, `overview_ready`, `table_reclassified`) |
| 37–83 | Imports + prefs load/save | ✓ kept |
| 84–189 | `_SessionLogger`, `_LogCapture`, stdout redirect | ✓ kept verbatim |
| 190–200 | `ur_extractor` imports | Minor addition (`load_table_overrides`, `save_table_override`) |
| 201–275 | HGB import guard, design tokens, typography constants | ✓ kept |
| 276–519 | `ExtractorWorker` — asyncio thread, browser, batch pipeline | Needs: `recompute_overview` command handler; `apply_table_overrides()` called before emitting `batch_complete` |
| 520–574 | `URExtractorApp.__init__` — state, prefs, worker, poll | **Major refactor**: replace flat `_all_tables`/`_doc_sections` with `_session` dict |
| 575–866 | `_build_ui`, layout zones, status track, left rail, center canvas, right rail, log drawer, settings | Left rail: refactor from "filing list" to "company list + filings per company". Center canvas: add "All Tables" tab UI stub. Status track: add second review badge (tables). |
| 867–918 | `_style_treeview` | ✓ kept |
| 919–1027 | Financial grid: `_get_overview_table`, `_draw_financial_grid`, `_row_display_type`, `_format_value` | ✓ kept; needs company scoping |
| 1028–1072 | `_on_tree_click` | ✓ kept |
| 1073–1237 | Right rail: `_open_right_rail`, audit content, review content | Extend review content to include table-level items |
| 1305–1420 | Needs Review logic — compute, update badge, resolve, skip, remap | Extend to include table review list; second badge slot |
| 1421–1459 | Canvas state machine, tab buttons | Add "All Tables" tab and its content rendering |
| 1460–1562 | `_poll`, `_handle`, `_set_status`, `_set_breadcrumb`, CAPTCHA | Add `overview_ready` event handler |
| 1563–1701 | Search flow, results rendering | ✓ kept; company now added to session not replaced |
| 1703–1820 | Processing flow, doc sections, left rail rebuild | **Refactor**: `_add_doc_section` adds to active company in session; left rail shows companies |
| 1821–1984 | Settings panel | Add: auto-apply table overrides toggle |
| 1984–2095 | Settings helpers, theme, log, session reset | `_on_new_search` clears full session; `_on_add_company` returns to search without clearing |
| 2099–2119 | `main()` | ✓ kept |

---

## 3. Current `ur_extractor.py` data model

### Extracted table record (`tables: list[dict]`)
```
{
    "index":       int,            # 1-based within the PDF
    "heading":     str,            # largest-font text above table (or inferred)
    "rows":        list[list],     # list of rows; each row is list of cell strings
    "page_start":  int,
    "page_end":    int,
    "doc_label":   str,            # set by worker: the FY string ("FY2024")
    "_company":    str,            # set by worker: company name string
    "pdf_path":    str,            # set by worker after download_pdf()
    "multi_year":  bool,           # set by build_multi_year_tables()
    "years":       list[int],      # set on multi-year tables
    "type":        int,            # 0=Bilanz, 1=GuV, 2=CF, 99=Other — set by _classify_table()
}
```
`type` is set by `_classify_table()` at line 1710 of ur_extractor.py. **This is the field the table-level override writes to in-session.**

### `build_multi_year_tables(tables)` — line 2337
- Input: all per-year per-company table records
- Groups by `_classify_table(t)`, then aligns rows by HGB `std_id` / CF pattern key
- Output: new table records with `multi_year=True`, `years=[...]`, rows aligned across years
- Called once after `batch_complete` in the current GUI; must become callable on-demand (recompute trigger)

### `_classify_table(t)` — line 1710
- Heuristic classifier; returns 0/1/2/99
- **No side effects** — can be called on any table record at any time
- Cannot be modified (hard constraint), but the GUI can override its result by writing `t["type"] = override_type` before calling `build_multi_year_tables`

### Where auto-classification happens
1. `extract_tables_from_pdf()` (line 1079) calls `_classify_table()` internally to set `t["type"]`
2. `_pin_key_tables()` (line 1799) reorders tables, no classification change
3. `build_multi_year_tables()` reads `t["type"]` to group; does not re-classify

### Auto-classify + override application sequence (proposed)
```
extract_tables_from_pdf()         → t["type"] = auto_class (0/1/2/99)
↓
apply_table_overrides(tables, co) → t["type"] = override if match found
↓
build_multi_year_tables(tables)   → OVERVIEW computed on overridden types
```

---

## 4. Phase plan (v2 sequenced)

### Phase 0 — Reconnaissance & plan (this document)
Already done. Deliverable: this WORKING_PLAN.md.
**Stop here. Wait for human approval.**

---

### Phase 1 — Multi-company session data model + layout refactor

**What changes:**

**`ur_extractor.py` additions (carve-out):**
- `load_table_overrides(path) -> dict` — reads `data/table_overrides.csv`, returns lookup dict keyed by `(company_normalized, filing_id, heading_normalized)`
- `save_table_override(path, record: dict)` — appends one row to `data/table_overrides.csv`
- `apply_table_overrides(tables, company_id, overrides_dict)` — mutates `t["type"]` for matching tables; logs applied overrides via `print()`
- These are pure data helpers (~40 lines total); no engine logic touched

**`ur_gui.py` refactor:**

Replace flat session state:
```python
# OLD (v1)
self._all_tables: list = []
self._overview_tables: list = []
self._doc_sections: list = []    # [{doc, tables}]
self._review_list: list = []
```

With structured multi-company session:
```python
# NEW (v2)
self._session = {
    "companies": [],              # list of company dicts (see data model above)
    "active_company_id": None,    # str or None
}
self._table_overrides: dict = {}  # loaded at startup from data/table_overrides.csv
```

Company dict structure:
```python
{
    "id": str,                    # normalized (lowercase + underscores)
    "display_name": str,          # full company name
    "short_name": str,            # first word/token, for sheet prefixes
    "filings": list[dict],        # [{doc, tables}]
    "overview_tables": list,      # computed by build_multi_year_tables
    "review_line_items": list,    # computed after each extraction
    "review_tables": list,        # computed after each extraction (type==99 + overrides)
}
```

**Left rail** refactored: company list (each expandable to filings) + bottom button split into "Add company" and "New session".

**Search/processing flow** updated: `_add_doc_section()` now finds or creates a company entry in `self._session["companies"]`; the company is identified by normalizing `doc["company"]`.

**Acceptance criteria:**
- App launches; search works; processing works; tables appear; export works — identical user outcomes
- Multiple searches add multiple companies without losing previously processed data
- Left rail shows company names (expandable to filings)
- Layout zones preserved; threading model unchanged
- Table overrides CSV is loaded at startup and applied during `batch_complete`

---

### Phase 2 — Canvas tabs: OVERVIEW + All Tables

**New canvas structure:**

```
Center canvas
├── Tab bar: [OVERVIEW]  [All Tables]              (top of canvas)
├── OVERVIEW frame (existing grid, now scoped to active company)
│   └── Sub-tabs: Bilanz | GuV | Cashflow
└── All Tables frame (new)
    └── ttk Treeview: heading | year | pages | rows | type badge | OVERVIEW status
        └── Right-click context menu (stub → full in Phase 3)
```

**All Tables Treeview columns:**
- `heading` (left-aligned, 280px)
- `year` (right-aligned, 60px)
- `pages` (center, 70px, "p. 3–5")
- `rows` (right-aligned, 50px)
- `type` (center, 90px — colored badge text: Bilanz/GuV/CF/Other)
- `status` (center, 90px — "✓ OVERVIEW" or "⊘ excluded")

Type badge colors inherited from `TYPE_COLORS` in config: Bilanz=#3b82f6, GuV=#10b981, CF=#8b5cf6, Other=#6b7280.

**Company switching:** clicking a company in the left rail calls `_switch_active_company(company_id)`, which re-renders both OVERVIEW and All Tables for that company.

**Export updated:** `_on_export_excel()` iterates all companies, prefixes sheets by `company["short_name"]`.

**Acceptance criteria:**
- Both tabs visible and switchable
- All Tables shows correct type + OVERVIEW status for every extracted table
- Company switching in left rail instantly re-renders both tabs
- Export produces company-prefixed sheets for all companies in session
- Old flat table list is gone

---

### Phase 3 — Table resegmentation (right-click → reclassify)

**Right-click context menu on All Tables rows:**
```
Reclassify as ▶  Bilanz
                 GuV
                 Cashflow
                 Other
─────────────────────────
Include in OVERVIEW: [✓ Yes] / [✗ No]
─────────────────────────
Preview in right rail
Open source PDF
```

**Reclassification flow (threading model):**
1. GUI thread: user picks type → mutates `t["type"]` in the company's tables list (immediate visual update in All Tables)
2. GUI thread: sends `recompute_overview` command to worker with `(company_id, tables_list)`
3. Worker thread: calls `apply_table_overrides()` then `build_multi_year_tables(tables)` → emits `overview_ready` event with `(company_id, new_overview_tables)`
4. GUI thread: on `overview_ready` — updates `company["overview_tables"]`, refreshes OVERVIEW grid if this company is active
5. GUI thread: calls `save_table_override()` to persist the override to `data/table_overrides.csv`

**New worker commands:**
```
recompute_overview   (company_id: str, tables: list[dict])
```

**New worker events:**
```
overview_ready       (company_id: str, overview_tables: list[dict])
```

**Acceptance criteria:**
- Right-click menu appears on All Tables rows
- Reclassification updates All Tables badge immediately
- OVERVIEW refreshes (via queue round-trip) within ~300ms
- Override written to `data/table_overrides.csv`
- Override applied automatically on next extraction of same filing

---

### Phase 4 — Audit drill-down (already partially implemented; extension)

The current right rail audit content is already implemented. Extensions for v2:
- Add **table preview mode** when user clicks "Preview in right rail" from All Tables context menu
- Table preview: shows the raw extracted table (mini Treeview), heading, page reference, type badge, "Reclassify as…" inline buttons

**Acceptance criteria (additions):**
- "Preview in right rail" from All Tables opens a table preview in the right rail
- Inline reclassify buttons in the preview work the same as the context menu
- Existing cell-click audit from OVERVIEW still works unchanged

---

### Phase 5 — Review queue (two badges, both queues)

Current state: one review badge (line items only). v2 adds the second badge for tables.

**Status track:** two badge slots:
```
[⚠ 4 line items]  [⚠ 2 tables]
```

**Right rail Review mode** extended to two collapsible sections:
- **Line items** — ambiguous/unmatched HGB labels (existing logic)
- **Tables** — tables where `t["type"] == 99` (Other) OR where `t["_override_applied"] == False` and classification confidence < threshold (heuristic: tables whose heading does not contain any classifier keyword → suggest manual review)

Table review item shows: heading, page range, row count, current type badge, one-click reclassify buttons.

**Resolution flow:** same queue round-trip as Phase 3 (recompute_overview on worker).

**Acceptance criteria:**
- Both badges show correct counts
- Clicking either badge opens review rail in the correct mode
- Table resolutions persist to `data/table_overrides.csv`
- Both badges go green (or disappear) when all items resolved

---

### Phase 6 — Visual polish (already partially done)

Current state: light theme, inline CAPTCHA, gear-only settings, breadcrumb — already implemented in the current ur_gui.py.

Remaining items:
- Per-filing progress cards during extraction (empty state mid-extraction)
- Strong empty state: "Search for a German company to begin"
- Settings: add "Auto-apply table overrides from CSV" toggle
- Status track: add per-document progress indicator during batch

**Acceptance criteria:**
- Empty states informative at all times
- Settings auto-apply toggle works
- CAPTCHA inline (already done ✓)

---

## 5. `data/table_overrides.csv` schema + recompute trigger design

### CSV schema (proposed — flag for human review)

```csv
company_normalized,filing_id,table_heading_normalized,override_type,override_include_in_overview,timestamp,note
```

| Column | Type | Description |
|---|---|---|
| `company_normalized` | str | lowercase + underscores, e.g. `ctec_i_gmbh` |
| `filing_id` | str | `{doc_type}_{fy}` e.g. `jahresabschluss_fy2024` |
| `table_heading_normalized` | str | lowercase + underscores, max 80 chars |
| `override_type` | str | `Bilanz`, `GuV`, `Cashflow`, `Other` |
| `override_include_in_overview` | bool | `true` or `false` |
| `timestamp` | str | ISO 8601, e.g. `2026-06-27T17:00:00` |
| `note` | str | `user_override` (default) or free text |

**Match key:** `(company_normalized, filing_id, table_heading_normalized)` — all three must match.

**Normalization function:**
```python
def _normalize_for_key(text: str, max_len: int = 80) -> str:
    import re
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9äöüß\s]", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:max_len]
```

### Recompute trigger mechanism

```
Worker._dispatch("recompute_overview", (company_id, tables))
    ↓ (on worker thread)
    apply_table_overrides(tables, company_id, self._overrides)
    new_overview = build_multi_year_tables(filtered_tables)
    self._emit("overview_ready", (company_id, new_overview))
    ↓ (GUI thread, via _handle)
    company = self._find_company(company_id)
    company["overview_tables"] = new_overview
    if company_id == self._active_company_id:
        self._draw_financial_grid(self._active_stmt)
        self._rebuild_all_tables_view()
```

The recompute is CPU-only (no I/O, no browser), takes <1s for typical PDFs. Worker thread is safe.

### `data/table_overrides.csv` location

```
Bundesanzeiger_Financial_Extracts/data/table_overrides.csv
```

File is created on first write if absent. Loaded at startup by `load_table_overrides()`. A missing file is not an error.

**Human review question:** Should this file live in `data/` (next to the mapping CSVs, shared/committed) or in `~/Downloads/UR_Extracts/` (per-user, like prefs.json)? Recommendation: `data/` — it's a compounding asset like `client_aliases.csv`, not a per-user preference.

---

## 6. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| **Multi-company data model refactor breaks existing session flow** (search, batch, export all assume single company) | High | Introduce `_active_company()` helper that returns the current company dict; all existing code calls this instead of `self._all_tables` directly. Refactor is mechanical, not structural. |
| **Right-click context menus in Treeview require `<Button-3>` binding which behaves differently on Mac/Windows** | Low (Windows-only tool) | Use `self._tree.bind("<Button-3>", handler)` + `tk.Menu.post(event.x_root, event.y_root)`. Test on Windows 11 only; document. |
| **`recompute_overview` queue round-trip adds latency visible to user** (user clicks reclassify, OVERVIEW refresh takes 200–500ms) | Medium | Show a brief spinner or "Updating…" label in the tab bar during recompute. The event is fired-and-forgotten; the UI remains responsive. |
| **`build_multi_year_tables` is sensitive to `t["type"]` — if override mutates the wrong record, OVERVIEW silently loses a table** | High | Apply overrides to a deep-copy of the tables list when sending to worker; do not mutate the canonical `company["filings"]` records. |
| **`data/table_overrides.csv` match key normalization may produce false positives** (two different tables with similar headings) | Medium | Include `filing_id` in the key (not just heading + company). Log every applied override to the session log so analysts can audit. |

---

## 7. Open questions for human review

1. **`data/table_overrides.csv` location:** `data/` (shared, committed) vs. `~/Downloads/UR_Extracts/` (per-user)? Recommendation: `data/`, for the same reason `client_aliases.csv` is in `aliases/`.

2. **"Add company" vs. "New session" buttons:** Brief says split into two distinct actions. Proposed placement: "New session" in the settings panel (rare action, destructive) and "+ Add company" as the bottom button of the left rail (frequent, non-destructive). Confirm?

3. **Multi-company export — one workbook or one per company?** Brief recommends one workbook per session with company-prefixed sheets. Confirm this is preferred over one-workbook-per-company.

4. **Table classification confidence threshold for auto-flagging in review queue:** Current `_classify_table()` returns an integer (0/1/2/99) with no confidence score — it's deterministic, not probabilistic. So "low confidence" must be inferred heuristically (e.g., type==99, or heading contains no known classifier keyword). Proposed: flag for review if `t["type"] == 99`. Is that sufficient, or should we also flag tables whose `heading` is empty/generic?

5. **Phase ordering:** The v2 prompt sequences Phases 1→6. Given that the current `ur_gui.py` already contains layout, OVERVIEW grid, audit rail, and single-company review — should we treat the current file as "Phase 1 partially done" and continue from Phase 2 (All Tables tab) + the multi-company data model refactor, or start Phase 1 from scratch? Recommendation: keep the current file as the base and layer v2 additions on top.

---

*Ready for human review. Awaiting approval to begin Phase 1 coding.*
