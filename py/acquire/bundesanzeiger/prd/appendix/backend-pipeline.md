# Appendix — Backend Pipeline (Worker Protocol + Extraction)

This desktop app has no app-owned HTTP API. Its "backend" is the **worker thread**
(`_Worker` in `ur_gui.py`) running an asyncio loop + Playwright browser, plus the pure
functions in `ur_extractor.py`. The GUI and worker talk over two queues.

## Command / event protocol (the app's "API")

### GUI → Worker — commands (`self._worker.send(cmd, payload)`)
| Command | Payload | Handler does |
|---------|---------|--------------|
| `search` | company name | `run_search()` against the register |
| `process_batch` | (selected filings, pdf_dir) | download + extract each filing |
| `recompute_overview` | (company_id, all_tables, bundle_info, row_merges) | `build_multi_year_tables()` (+ optional feedback bundle) |
| `export_v2` | (overview_tables, all_tables, result, out_path, dec, tho, pdf_dir, review_meta) | `export_to_excel_v2()` |
| `navigate_home` | — | browser back to base URL |
| `quit` | — | shut down loop + browser |

### Worker → GUI — events (`self._emit(event, data)`), drained by `_poll` every 100 ms
| Event | Data | GUI reaction |
|-------|------|--------------|
| `ready` | — | App ready / returned home |
| `status` | text | Status track message |
| `search_results` | list \| None | Populate Search results (or "no results") |
| `need_confirm` | — | Prompt/confirm step |
| `batch_progress` | (fraction, label) | Animate progress bar + status |
| `batch_doc_done` | (doc, tables) | Append tables to active company; re-apply overrides |
| `batch_error` | (i, label, msg) | Per-filing error |
| `batch_complete` | — | Rebuild overview, recompute review, switch to OVERVIEW, enable Export, auto-save Library |
| `overview_ready` | (company_id, overview_tables) | Store + redraw grid; auto-save |
| `bundle_written` | (ok, path) | Update bundle dot + tooltip history |
| `exported` | (count, path) | "Exported N sheet(s)" + re-enable Export |
| `error` | message | Surface error |

## Acquisition pipeline (`ur_extractor.py`)

```
run_search(page, name)        → navigate register, fill form, solve CAPTCHA, read hit list
   → [ {company, doc_type, fy, date_filed, url}, … ]
select_document / open_document(page, result, confirm) → open the chosen filing
download_pdf(page, result, captcha_cb) → download PDF (second CAPTCHA possible) → pdf_path
extract_tables_from_pdf(pdf_path) → [ table dicts ]
```

### Table extraction (`extract_tables_from_pdf`)
Uses `pdfplumber` to find tables per page, then:
1. Extract cell grids (`rows`).
2. `_extract_heading()` — read the section title from layout above each table.
3. `_classify_stmt_name()` / `_classify_table()` — assign a statement type (0/1/2/99).
4. `_pin_key_tables()` — pin Bilanz→index 1, GuV→2, KFR→3.
5. `_heuristic_word_extraction()` — fallback for tables pdfplumber misses.

**Extracted table dict** (the unit everything else operates on):
| Key | Type | Meaning |
|-----|------|---------|
| `index` | int | 1-based position after pinning |
| `heading` | str | Section title from PDF layout |
| `rows` | list[list] | Cell values (strings / None); row 0 may be a title or the date header |
| `type` | int | 0/1/2/99 (auto or overridden) |
| `doc_label` | str | Filing label, e.g. "FY2024" |
| `page_start` / `page_end` | int | Source pages |
| `_include_in_overview` | bool | Whether it feeds consolidation (override) |
| `_override_applied` / `_override_old_type` | — | Manual reclassification markers |

## Consolidation (`build_multi_year_tables`) {#consolidation}
Turns a company's per-year tables into one grid per statement type.

**Algorithm (business-visible rules):**
1. Group source tables by **effective type** (override-aware); skip type 99; need ≥2 tables.
2. For each table, find the **date-header row** among the first ~3 rows (section-titled
   balance sheets put a heading on row 0 and dates on row 1) and read year→column. If no
   date header, fall back to the **doc_label** year (e.g. "FY2017"; a digit-bounded regex
   so the year glued to "FY" still matches).
3. **Within-year merge** — multiple tables reporting the same year are unioned (Aktiva +
   Passiva split across two tables join one column); on a genuine duplicate the more
   authoritative source wins (current-year date column > prior-year column > doc_label).
4. Require **≥2 distinct years** or the type is skipped.
5. **Row ordering** — full outer-join of every contributing table; seed order from the
   "best" (main, most-recent) statement, then append rows only seen in other years.
6. **Row identity** — `_canonical_row_key()` (lower, umlaut-fold, sign-synonyms like
   Jahresüberschuss/Jahresfehlbetrag → one key) then apply the analyst's **row-merges**.
   The merged row keeps its position but adopts the kept target's display label.
7. Emit a synthetic table: `{type, years[], rows[[Description, y1, y2,…], …],
   row_source_labels[], multi_year=True}`.

## Export (`export_to_excel_v2`)
Produces a workbook: one sheet per OVERVIEW (multi-year) table, one sheet per raw per-year
table, and a **Mapping Audit** sheet (`raw_label, std_id, canonical_en, match_type,
fiscal_year, company`) built via `_derive_audit_rows()` + `hgb_map.lookup`. Number
separators come from Settings. `export_to_csv` / `export_to_excel` are legacy exporters.

## Feedback bundles (`write_feedback_bundle`)
When the analyst reclassifies a table, a bundle (manifest + table JSON/CSV + source PDF
excerpt) is written under `~/Downloads/UR_Extracts/feedback/resegmentations/` — a
training/audit trail of human corrections. Success/failure drives the status-track bundle dot.
