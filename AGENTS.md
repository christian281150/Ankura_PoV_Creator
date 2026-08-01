# AGENTS.md â€” Company Profile Builder

Implementation brief for coding agents (Codex, Claude Code, Cursor).
Read this before touching the repo. Full design rationale lives in
`company-profile-builder-spec.md`; this file is the operational contract.

---

## Project in one paragraph

Generate a four-box "At a glance" company profile slide for private German
companies, from Handelsregister + Bundesanzeiger filings + web sources. Every
figure on the slide must trace to a named line in a named filing on a named page.
The system's value is the reconciliation and coverage layer, not the slide
rendering. Targets are mostly GmbH / GmbH & Co. KG mid-caps with incomplete
disclosure.

---

## Prime directive

> **A confidently wrong output is worse than a crash.**

Missing or ambiguous data must produce a visible gap or a blocking flag. Never a
plausible-looking default, never a silent substitution, never an interpolation.

Concretely, agents must **not**:

- fill a missing year by interpolation or carry-forward
- substitute a different content block when the canonical one is unavailable
- resolve a company by name string
- emit a figure without `std_id`, `unit`, `presentation_basis`, and provenance
- widen a fuzzy match to make a row map
- catch and swallow a validation failure

---

## Repo layout (target)

```
profile_builder/
  entity/          resolution: register lookup, group tree, confirmation
  acquire/         filings (existing tool), register, web, jobs, news
  normalise/       sheet classifier, HGB mapping, units, basis, flags
  validate/        rules V1â€“V9, anomaly detection, footnote generation
  blocks/          content block catalogue + scoring
  gui/             screens 1â€“7
  render/          python-pptx â†’ Ankura master
  mappings/        hgb_taxonomy.csv, label_synonyms.csv, account_ranges.csv, ...
  tests/
    fixtures/      Seidensticker FY2015â€“FY2025 workbook + expected JSON
```

Python 3.11+. Stdlib + `openpyxl`, `pdfplumber`, `python-pptx`, `pydantic`,
`httpx`, `beautifulsoup4`. No pandas in the normalise layer â€” column semantics
matter more than dataframe ergonomics here.

---

## Ground-truth test case

**Textilkontor Walter Seidensticker GmbH & Co. KG**, HRA 8217, AG Bielefeld.
FYE 30 April. Â§267 gross. 11 fiscal years of Konzernabschluss (FY2015â€“FY2025).

Two facts about this fixture that every agent must know:

1. The website Impressum names **TK Store-Management GmbH**. That is a
   subsidiary, not the group. Any pipeline that accepts it is broken.
2. The published deck charts a series labelled "Revenue in â‚¬m" that is actually
   **Gesamtleistung** (UmsatzerlÃ¶se + BestandsverÃ¤nderung + sonstige betriebliche
   ErtrÃ¤ge). Rule V1 exists to catch exactly this.

### Golden reconciliation (all values EUR m, from `p0_normalise.py`)

| FY | UmsatzerlÃ¶se | Bestandsver. | Sonst. ErtrÃ¤ge | Gesamtleistung |
|---|---|---|---|---|
| 2017 | 198.8 | (0.1) | 4.4 | 203.0 |
| 2018 | 184.4 | 0.1 | 7.2 | 191.7 |
| 2019 | 178.7 | (1.5) | 1.7 | 178.9 |
| 2020 | 139.4 | 0.3 | 6.6 | 146.3 |
| 2021 | 100.4 | (4.0) | 9.8 | 106.2 |
| 2022 | 103.1 | 5.1 | 9.2 | 117.3 |
| 2023 | 126.8 | 4.0 | 3.1 | 134.0 |
| 2024 | 103.2 | **(8.8)** | 7.8 | 102.1 |
| 2025 | 111.8 | 2.7 | 1.9 | 116.5 |

The Gesamtleistung column reproduces the published deck for all nine years.
Any regression that changes these numbers is a failure.

Derived assertions for tests:

- `revenue_growth_FY25 == +8.4%` (on UmsatzerlÃ¶se) â€” **not** +14.1%
- `revenue_change_FY24 == âˆ’18.6%` (on UmsatzerlÃ¶se) â€” **not** âˆ’24%
- `FY24 bestandsveraenderung == âˆ’8_833_400.55` exactly

---

## Task list

### P0 â€” Extraction fixes  âœ… reference implementation in `p0_normalise.py`

| ID | Task | Acceptance |
|---|---|---|
| P0.1 | Wire the mapper into export | `Mapping Audit` map rate â‰¥ 90%; currently 0% |
| P0.2 | Year-block column coalescing | UmsatzerlÃ¶se non-null for all 12 years in the multi-year GuV |
| P0.3 | German number parsing | `'+ 1.914.645,32'` â†’ `1914645.32`; `'+142.366,40'` â†’ `142366.40` |
| P0.4 | Unit normalisation | FY2015â€“16 TEuro sheets scaled Ã—1000; no 1000Ã— cliff in any series |
| P0.5 | Merge on `std_id` not raw label | No duplicate `6. Abschreibungen` rows; no `- davon` rows in output |
| P0.6 | Longest-match mapper | `4. Materialaufwand` â†’ parent, **never** `PL_GKV-5a` |
| P0.7 | Add missing taxonomy rows | `VerÃ¤nderung des Bestandsâ€¦`, `Konzernbilanzverlust`, `Nicht durch VermÃ¶genseinlagen gedeckter Verlustanteil` all resolve |

Notes for the agent:

- The GuV column layout is: label in col 0, then **one column block per fiscal
  year**, each block containing a detail column and a subtotal column. A line's
  value may sit in either. Coalesce left-to-right within the year's block. This
  is why revenue was blank while material costs were populated.
- FY2016 and earlier use a different presentation (Lagebericht Ertragslage
  table, TEuro, explicit `Gesamtleistung` row). Detect, don't assume.
- The bundled `hgb_map.py` does exact-normalised lookup only and returns `none`
  on any miss. Use `hgb_lookup_reference.py` as the base and add longest-match.

### P1 â€” Sheet classifier

The extractor already captures Konzernanhang, Anlagenspiegel,
Eigenkapitalspiegel, Konsolidierungskreis, Fristigkeiten, Â§285 Nr. 4 revenue
splits, and Lagebericht sections. They land in sheets named `FY2021_ (5)` and
`FY2023_Tâ‚¬ 0 verrechnet. Der ver`.

Classify each sheet into: `bilanz` Â· `guv` Â· `kapitalflussrechnung` Â·
`anhang_umsatzsplit` Â· `anhang_konsolidierungskreis` Â· `anlagenspiegel` Â·
`eigenkapitalspiegel` Â· `fristigkeiten` Â· `lagebericht_vermoegenslage` Â·
`lagebericht_finanzlage` Â· `unknown`.

Classify on **content signature** (header tokens, column shape, row labels), not
on sheet name. Sheet names are truncated PDF headings and unreliable.

**Acceptance:** â‰¥ 85% of the 150 sheets in the fixture classified; `unknown`
rate reported, never silently dropped.

### P2 â€” JSON output + provenance

Every value carries:

```json
{
  "std_id": "PL_GKV-1",
  "raw_label": "1. UmsatzerlÃ¶se",
  "match_type": "exact",
  "fy": 2025,
  "value": 111815106.14,
  "unit": "EUR",
  "presentation_basis": "umsatzerloese",
  "provenance": { "doc": "Konzernabschluss FY2025", "sheet": "...", "row": 7, "page": null },
  "scope_flag": null,
  "method_flag": "GKV"
}
```

`page` is null until PDF page tracking is added upstream â€” model it now.

### P3 â€” Entity resolution service

Standalone, unattended, no CAPTCHA. Register-first.

- Resolve to `{court, register_type, number}`, never a name
- Walk shareholding tree upward to the terminal parent
- **Hard flag:** legal-form / register-type mismatch (a Konzernabschluss filer
  registered as HRB when the operating parent is a KG under HRA)
- Track historical names and predecessor parents
- Persist: Gesellschafterliste changes, officer changes, scope changes,
  filing lateness vs. Â§325 deadline

**Acceptance:** given `seidensticker.com`, returns HRA 8217 as target and
TK Store-Management GmbH as subsidiary, with a warning that the Impressum entity
is not the group.

### P4 â€” Validation rules

| Rule | Check | On failure |
|---|---|---|
| V1 | Series labelled "Revenue" has `presentation_basis == umsatzerloese` | block |
| V2 | Single unit within a series | block |
| V3 | Consolidation perimeter change between adjacent years | require note |
| V4 | GKVâ†”UKV switch mid-series | require note |
| V5 | Line moves > 15% YoY | require note |
| V6 | Cost ratio breaks trend > 5pp | require note |
| V7 | Unmapped label used in a charted series | block |
| V8 | Aktiva == Passiva | block |
| V9 | `Nicht durch VermÃ¶genseinlagen gedeckter Verlustanteil` present | flag, never suppress |

Notes written against V3â€“V6 become slide footnotes automatically.

**Acceptance on fixture:** V5 fires on FY24 revenue (âˆ’18.6%) and FY20 (âˆ’22.0%);
V6 fires on the FY24 material-cost ratio; V1 fires if any series is charted as
"Revenue" on a Gesamtleistung basis.

### P5â€“P7 â€” Web/jobs scraper, coverage probe, content blocks

See spec Â§4, Â§7, Â§8. Block schema:

```json
{
  "id": "fin.revenue_ebitda_series",
  "kind": "chart.column_line",
  "eligible_slots": ["top_right", "bottom_right"],
  "coverage": 0.93,
  "confidence": "high",
  "presentation_basis": "umsatzerloese",
  "blocking_flags": [],
  "footnotes_auto": ["FY24 depressed by â‚¬8.8m inventory drawdown"],
  "provenance": [ ... ]
}
```

Ordering in the GUI dropdown is `coverage Ã— confidence`, descending.

### P8 â€” GUI

Wireframe: `gui-slot-assignment-wireframe.svg`. Screens 1â€“7 per spec Â§9.1.

Non-negotiable behaviours:

- **Screen 2 (entity confirmation) cannot be skipped or defaulted.**
- Unavailable blocks render greyed **with reason**, never hidden
- Blocks with unresolved blocking flags are listed but not selectable
- Deviation from canonical layout is allowed, badged, and written to metadata
- `Export .pptx` disabled while any blocking flag is unresolved
- `Lock layout` persists slot assignment across data refreshes

### P9 â€” Render

`python-pptx` into the Ankura master. Footnotes assembled from `footnotes_auto`
plus human notes. Every rendered figure writes `std_id` + doc + page into slide
notes so the deck is auditable after delivery. Emit a companion `.json`.

---

## Coverage limits to encode, not work around

Â§267 HGB size class determines what exists at all:

| Class | Available | Consequence |
|---|---|---|
| Klein | Balance sheet only | No financials box from filings. Say so. |
| MittelgroÃŸ | Abridged GuV from Rohergebnis (Â§276) | **Revenue frequently invisible.** Say so. |
| Gross | Full GuV, Lagebericht, Â§285 Nr. 4 split | Full profile |

The mittelgroÃŸ case is the core PE hunting ground and the most common. The
correct output when revenue is not disclosed is:

> *Revenue not separately disclosed (Â§276 HGB abridgement â€” Rohergebnis only)*

Not an estimate. Not a proxy. Not a blank chart.

---

## Conventions

- All amounts stored in **EUR**, never TEUR. Presentation scaling happens in render only.
- Fiscal year keyed by **end year** (`2025` = 1 May 2024 â€“ 30 Apr 2025). Non-calendar FYE must be carried in entity metadata and shown on every slide.
- German labels preserved verbatim in `raw_label`. Never translate before mapping.
- Normalisation for matching: lowercase, umlaut expansion (Ã¤â†’ae, ÃŸâ†’ss), strip non-alphanumeric. Must match build-side normalisation exactly.
- Type hints everywhere. `pydantic` models for anything crossing a layer boundary.
- No network calls in `normalise/` or `validate/`.

## Do not

- Do not add a fuzzy-match threshold to raise the map rate. Add taxonomy rows instead.
- Do not use `ws.max_row` from openpyxl in read-only mode.
- Do not assume `"Summe Passiva"` terminates the Bilanz â€” it breaks on abweichende Gliederung and IFRS-converged presentation.
- Do not scrape every page of a company site. Target the page classes in spec Â§4.1c.
- Do not treat an Impressum as a corporate-structure source.
- Do not compare margins across business models (vertically integrated manufacturer vs. asset-light DTC) without a `business_model` tag and a flag.


### Lane D - known bugs, fix before F1

- D0.1  The same block can be assigned to two slots simultaneously. A block
        assigned elsewhere must render disabled with reason "already in <slot>".
- D0.2  Deselecting a block silently clears its open flags, which can unblock
        export. exportBlocked must also require: all four slots assigned, and
        at least one assigned block carrying a financial series.
- D0.3  Action bar overlaps the last slot card at narrow viewports.


## Mapping discipline - inherited from the extractor's CLAUDE.md

The mapper is exact-match only. Never auto-pick an ambiguous match: exact match,
else queue to py/normalise/reviews/unmapped_queue.csv. Raise the map rate by
adding taxonomy rows or client aliases, never by widening the matcher.

Report map rate and queue length separately. A lower map rate with an honest
queue beats a high one with silent misclassifications. A queue of pre-BilRUG
subtotals is a healthy end state - do not force it to zero.

The taxonomy is generated from HGB_GKV_UKV_Standardisation_Map.xlsx. Do not
hand-edit lib/hgb_map.py embedded data. Aliases go in
py/normalise/aliases/client_aliases.csv with a note explaining why each mapping
is correct - "exact published-label variant" is not a justification.


## Environment

Agent sandboxes have NO network access. Do not attempt pip install or npm install.
Dependencies are pre-installed by the human before the session starts.
Use .venv\Scripts\python.exe directly; do not activate the venv.
If a dependency is missing, stop and report it - do not work around it.
## Unmapped queue location

Lane A writes its queue to py/normalise/reviews/unmapped_queue.csv.
The file at py/acquire/bundesanzeiger/reviews/ is inside the submodule and is
the extractor's own queue - read it as a format reference, never write to it.
The mapper is exact-match only. Never auto-pick an ambiguous match: exact match, else queue to py/normalise/reviews/unmapped_queue.csv. Raise the map rate by adding taxonomy rows or client aliases, never by widening the matcher.