# Appendix — Persistence Schemas & HGB Mapping

All persistence is **local files** (no database, no server). Two ideas drive the design:
corrections must **survive restart** and be **re-applied automatically**, and the canonical
mapping must **never guess**.

## Persistence stores

### Table overrides — `data/table_overrides.csv`
Remembers per-table corrections (re-classification, include/exclude).

| Column | Meaning |
|--------|---------|
| `company_normalized` | Company key (lowercased, punctuation-stripped) |
| `filing_id` | `override_filing_id(t)` = normalized `doc_type_doc_label` |
| `table_heading_normalized` | Normalized table heading |
| `override_type` | Bilanz / GuV / Cashflow / Other |
| `override_include_in_overview` | "true"/"false" |
| `timestamp` | ISO time |
| `note` | Provenance, e.g. "bulk reclassified from 99 via GUI" |

- Written by `save_table_override()` (via `make_override_record`); re-applied by
  `apply_table_overrides()` on every `batch_doc_done` and overview rebuild.
- **Key consistency:** save and apply derive `filing_id` through the same
  `override_filing_id()` so corrections re-match on re-extraction.

### Row merges — `data/row_merges.csv`
Remembers "these two differently-named rows are the same line".

| Column | Meaning |
|--------|---------|
| `company_normalized` | Company key |
| `member_key` | Canonical key of the merged-away label |
| `target_key` | Canonical key of the kept label |
| `display_label` | Label to show for the merged group |
| `timestamp`, `note` | Provenance |

- `save_row_merge` / `load_row_merges` (returns `{member_key: target_key}`, with transitive
  chains collapsed) / `clear_row_merges` (matches member **or** target, so unmerging the
  kept row dissolves the whole group).
- Applied inside `build_multi_year_tables(tables, row_merges=…)`.

### Client aliases — `aliases/client_aliases.csv`
Authoritative, version-controlled label→canonical resolutions added from the **Audit
Remap** and **Needs Review** flows (`[raw_label, std_id, company, note]`). Drives the
unmapped queue toward zero across packs.

### Unmapped queue — `reviews/unmapped_queue.csv`
Labels with no/ambiguous canonical match queued for human resolution (the "fail loud"
output of the mapping rule).

### User preferences (JSON)
Loaded at startup into `_USER_PREFS`: `theme`, `pdf_dir`, `log_dir`, `log_together`,
`log_delete_on_close`, `decimal_sep`, `currency_unit`, `show_std_id`.

### Library {#library}
Per-company snapshots so a worked-up company survives restart.
- **Location:** `library/` next to the executable when frozen, else the source dir.
- **One JSON per company:** `{schema, saved_at, name, company:{…full session dict…}}`.
- **Filename:** `‹normalized-name›__‹sha1(full name)[:8]›.json` — distinct companies that
  normalise to the same key cannot overwrite each other; the same name updates in place.
- **Index:** `library/index.json` = `{filename: {name, saved_at, n_filings, n_tables}}` so
  the rail lists entries without parsing every (multi-MB) snapshot. Backfilled for legacy
  files; pruned on delete.
- **Write path:** `prepare_library_save()` (snapshot/serialise on the GUI thread for a
  consistent read) → `write_library_file()` (atomic write + index update, runnable
  off-thread). Auto-save is **debounced ~1.5 s** and written on a daemon thread; flushed
  synchronously on close.

## HGB mapping subsystem (`lib/hgb_map.py` + `lib/hgb_data/`) {#hgb-mapping}

The canonical chart of accounts the app standardises every label to.

### Public API (stable; what the app consumes)
| Function | Returns |
|----------|---------|
| `lookup(label)` | `{query, normalized, match_type, candidates:[record,…]}` |
| `by_id(hgb_code)` | full record or None |
| `resolve(label)` | single `std_id` only when unambiguous, else None |
| `records(statement=None)` | all / filtered records |
| `normalize(text)` | the matching key: lower, ä→ae ö→oe ü→ue ß→ss, keep alphanumerics |
| `SYNONYM_INDEX` | `{normalized_key: [hgb_code,…]}` |
| `DRIFT_LOG` | GKV↔UKV bridge rows (reference) |

A **record** = `std_id` (=hgb_code), `canonical_en`, `canonical_de`, `hgb_ref`, `row_type`
(line/memo/subtotal), `statement`, `level`, `pnl_format`, `is_subtotal`,
`ukv_allocation_required`.

### Rules baked into lookup
- **Exact normalized match only.** No substring/fuzzy fallback. A unique hit →
  `normalized`; a key mapping to >1 code → `ambiguous`; otherwise → `none`. Unknown or
  ambiguous labels go to **Needs Review** — the product never silently buckets a figure.
- The data is **embedded** in `hgb_map.py` (generated from `lib/hgb_data/`), so the
  packaged exe needs no external mapping file.

### Source data (`lib/hgb_data/`, v1.1) — for regeneration
| File | Contents |
|------|----------|
| `hgb_mapping.json` | Consolidated taxonomy + synonyms + bridge + detection + subtotals (the embed source) |
| `hgb_taxonomy.csv` | 95 canonical positions (BS / PL_GKV / PL_UKV / STAT) with `pnl_format`, `is_subtotal`, `ukv_allocation_required` |
| `label_synonyms.csv` | 210 German/English label → hgb_code synonyms (normalized keys) |
| `account_ranges.csv` | SKR03 / SKR04 / IKR account-number ranges → hgb_code (reference) |
| `pnl_format_bridge.csv` | GKV ↔ UKV position equivalences + allocation flags |
| `pnl_format_detection.csv` | Heuristics to detect GKV vs UKV from labels |
| `pnl_subtotals.csv` | Calculated subtotal definitions (Bruttoergebnis, EBIT, Finanzergebnis) |
| `hgb_lookup_reference.py` | Reference helper (account lookup, format detection, bridge) — not used by the GUI |

> **GKV ≠ UKV.** Nature-of-expense (Material/Personal) and function-of-expense
> (Herstellungs-/Vertriebs-/Verwaltungskosten) P&L formats do not map 1:1; bridging
> several GKV lines into UKV needs cost-centre data the published statement lacks. The
> mapping flags allocation-required positions rather than fabricating a split.

## Coverage note (observed)
Some real labels are intentionally **not** auto-mapped (e.g. "Rückstellungen für
Pensionsverpflichtungen", "Zahlungsmittel und Zahlungsmitteläquivalente") — they return
`none` and surface in Needs Review. The remedy is curated: add a synonym
(`lib/hgb_data/label_synonyms.csv`, then regenerate) or a `client_aliases.csv` entry — not
fuzzy matching.
