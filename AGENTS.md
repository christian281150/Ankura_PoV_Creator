# AGENTS.md — Company Profile Builder

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
  validate/        rules V1–V9, anomaly detection, footnote generation
  blocks/          content block catalogue + scoring
  gui/             screens 1–7
  render/          python-pptx → Ankura master
  mappings/        hgb_taxonomy.csv, label_synonyms.csv, account_ranges.csv, ...
  tests/
    fixtures/      Seidensticker FY2015–FY2025 workbook + expected JSON
```

Python 3.11+. Stdlib + `openpyxl`, `pdfplumber`, `python-pptx`, `pydantic`,
`httpx`, `beautifulsoup4`. No pandas in the normalise layer — column semantics
matter more than dataframe ergonomics here.

---

## Ground-truth test case

**Textilkontor Walter Seidensticker GmbH & Co. KG**, HRA 8217, AG Bielefeld.
FYE 30 April. §267 gross. 11 fiscal years of Konzernabschluss (FY2015–FY2025).

Two facts about this fixture that every agent must know:

1. The website Impressum names **TK Store-Management GmbH**. That is a
   subsidiary, not the group. Any pipeline that accepts it is broken.
2. The published deck charts a series labelled "Revenue in €m" that is actually
   **Gesamtleistung** (Umsatzerlöse + Bestandsveränderung + sonstige betriebliche
   Erträge). Rule V1 exists to catch exactly this.

### Golden reconciliation (all values EUR m, from `p0_normalise.py`)

| FY | Umsatzerlöse | Bestandsver. | Sonst. Erträge | Gesamtleistung |
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

- `revenue_growth_FY25 == +8.4%` (on Umsatzerlöse) — **not** +14.1%
- `revenue_change_FY24 == −18.6%` (on Umsatzerlöse) — **not** −24%
- `FY24 bestandsveraenderung == −8_833_400.55` exactly

---

## Task list

### P0 — Extraction fixes  ✅ reference implementation in `p0_normalise.py`

| ID | Task | Acceptance |
|---|---|---|
| P0.1 | Wire the mapper into export | `Mapping Audit` map rate ≥ 90%; currently 0% |
| P0.2 | Year-block column coalescing | Umsatzerlöse non-null for all 12 years in the multi-year GuV |
| P0.3 | German number parsing | `'+ 1.914.645,32'` → `1914645.32`; `'+142.366,40'` → `142366.40` |
| P0.4 | Unit normalisation | FY2015–16 TEuro sheets scaled ×1000; no 1000× cliff in any series |
| P0.5 | Merge on `std_id` not raw label | No duplicate `6. Abschreibungen` rows; no `- davon` rows in output |
| P0.6 | Longest-match mapper | `4. Materialaufwand` → parent, **never** `PL_GKV-5a` |
| P0.7 | Add missing taxonomy rows | `Veränderung des Bestands…`, `Konzernbilanzverlust`, `Nicht durch Vermögenseinlagen gedeckter Verlustanteil` all resolve |

Notes for the agent:

- The GuV column layout is: label in col 0, then **one column block per fiscal
  year**, each block containing a detail column and a subtotal column. A line's
  value may sit in either. Coalesce left-to-right within the year's block. This
  is why revenue was blank while material costs were populated.
- FY2016 and earlier use a different presentation (Lagebericht Ertragslage
  table, TEuro, explicit `Gesamtleistung` row). Detect, don't assume.
- The bundled `hgb_map.py` does exact-normalised lookup only and returns `none`
  on any miss. Use `hgb_lookup_reference.py` as the base and add longest-match.

### P1 — Sheet classifier

The extractor already captures Konzernanhang, Anlagenspiegel,
Eigenkapitalspiegel, Konsolidierungskreis, Fristigkeiten, §285 Nr. 4 revenue
splits, and Lagebericht sections. They land in sheets named `FY2021_ (5)` and
`FY2023_T€ 0 verrechnet. Der ver`.

Classify each sheet into: `bilanz` · `guv` · `kapitalflussrechnung` ·
`anhang_umsatzsplit` · `anhang_konsolidierungskreis` · `anlagenspiegel` ·
`eigenkapitalspiegel` · `fristigkeiten` · `lagebericht_vermoegenslage` ·
`lagebericht_finanzlage` · `unknown`.

Classify on **content signature** (header tokens, column shape, row labels), not
on sheet name. Sheet names are truncated PDF headings and unreliable.

**Acceptance:** ≥ 85% of the 150 sheets in the fixture classified; `unknown`
rate reported, never silently dropped.

### P2 — JSON output + provenance

Every value carries:

```json
{
  "std_id": "PL_GKV-1",
  "raw_label": "1. Umsatzerlöse",
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

`page` is null until PDF page tracking is added upstream — model it now.

### P3 — Entity resolution service

Standalone, unattended, no CAPTCHA. Register-first.

- Resolve to `{court, register_type, number}`, never a name
- Walk shareholding tree upward to the terminal parent
- **Hard flag:** legal-form / register-type mismatch (a Konzernabschluss filer
  registered as HRB when the operating parent is a KG under HRA)
- Track historical names and predecessor parents
- Persist: Gesellschafterliste changes, officer changes, scope changes,
  filing lateness vs. §325 deadline

**Acceptance:** given `seidensticker.com`, returns HRA 8217 as target and
TK Store-Management GmbH as subsidiary, with a warning that the Impressum entity
is not the group.

### P4 — Validation rules

| Rule | Check | On failure |
|---|---|---|
| V1 | Series labelled "Revenue" has `presentation_basis == umsatzerloese` | block |
| V2 | Single unit within a series | block |
| V3 | Consolidation perimeter change between adjacent years | require note |
| V4 | GKV↔UKV switch mid-series | require note |
| V5 | Line moves > 15% YoY | require note |
| V6 | Cost ratio breaks trend > 5pp | require note |
| V7 | Unmapped label used in a charted series | block |
| V8 | Aktiva == Passiva | block |
| V9 | `Nicht durch Vermögenseinlagen gedeckter Verlustanteil` present | flag, never suppress |

Notes written against V3–V6 become slide footnotes automatically.

**Acceptance on fixture:** V5 fires on FY24 revenue (−18.6%) and FY20 (−22.0%);
V6 fires on the FY24 material-cost ratio; V1 fires if any series is charted as
"Revenue" on a Gesamtleistung basis.

### P5–P7 — Web/jobs scraper, coverage probe, content blocks

See spec §4, §7, §8. Block schema:

```json
{
  "id": "fin.revenue_ebitda_series",
  "kind": "chart.column_line",
  "eligible_slots": ["top_right", "bottom_right"],
  "coverage": 0.93,
  "confidence": "high",
  "presentation_basis": "umsatzerloese",
  "blocking_flags": [],
  "footnotes_auto": ["FY24 depressed by €8.8m inventory drawdown"],
  "provenance": [ ... ]
}
```

Ordering in the GUI dropdown is `coverage × confidence`, descending.

### P8 — GUI

Wireframe: `gui-slot-assignment-wireframe.svg`. Screens 1–7 per spec §9.1.

Non-negotiable behaviours:

- **Screen 2 (entity confirmation) cannot be skipped or defaulted.**
- Unavailable blocks render greyed **with reason**, never hidden
- Blocks with unresolved blocking flags are listed but not selectable
- Deviation from canonical layout is allowed, badged, and written to metadata
- `Export .pptx` disabled while any blocking flag is unresolved
- `Lock layout` persists slot assignment across data refreshes

### P9 — Render

`python-pptx` into the Ankura master. Footnotes assembled from `footnotes_auto`
plus human notes. Every rendered figure writes `std_id` + doc + page into slide
notes so the deck is auditable after delivery. Emit a companion `.json`.

---

## Coverage limits to encode, not work around

§267 HGB size class determines what exists at all:

| Class | Available | Consequence |
|---|---|---|
| Klein | Balance sheet only | No financials box from filings. Say so. |
| Mittelgroß | Abridged GuV from Rohergebnis (§276) | **Revenue frequently invisible.** Say so. |
| Gross | Full GuV, Lagebericht, §285 Nr. 4 split | Full profile |

The mittelgroß case is the core PE hunting ground and the most common. The
correct output when revenue is not disclosed is:

> *Revenue not separately disclosed (§276 HGB abridgement — Rohergebnis only)*

Not an estimate. Not a proxy. Not a blank chart.

---

## Conventions

- All amounts stored in **EUR**, never TEUR. Presentation scaling happens in render only.
- Fiscal year keyed by **end year** (`2025` = 1 May 2024 – 30 Apr 2025). Non-calendar FYE must be carried in entity metadata and shown on every slide.
- German labels preserved verbatim in `raw_label`. Never translate before mapping.
- Normalisation for matching: lowercase, umlaut expansion (ä→ae, ß→ss), strip non-alphanumeric. Must match build-side normalisation exactly.
- Type hints everywhere. `pydantic` models for anything crossing a layer boundary.
- No network calls in `normalise/` or `validate/`.

## Do not

- Do not add a fuzzy-match threshold to raise the map rate. Add taxonomy rows instead.
- Do not use `ws.max_row` from openpyxl in read-only mode.
- Do not assume `"Summe Passiva"` terminates the Bilanz — it breaks on abweichende Gliederung and IFRS-converged presentation.
- Do not scrape every page of a company site. Target the page classes in spec §4.1c.
- Do not treat an Impressum as a corporate-structure source.
- Do not compare margins across business models (vertically integrated manufacturer vs. asset-light DTC) without a `business_model` tag and a flag.


### Lane D - known bugs, fix before F1

- D0.1  The same block can be assigned to two slots simultaneously. A block
        assigned elsewhere must render disabled with reason "already in <slot>".
- D0.2  Deselecting a block silently clears its open flags, which can unblock
        export. exportBlocked must also require: all four slots assigned, and
        at least one assigned block carrying a financial series.
- D0.3  Action bar overlaps the last slot card at narrow viewports.
"@ -Encoding UTF8

Add-Content "$Repo\AGENTS.md" @"

## Mapping discipline - inherited from the extractor's CLAUDE.md

p0_normalise.py currently uses a longest-substring fallback. That VIOLATES the
extractor's rule 1: never auto-pick an ambiguous match. Lane A must replace it
with the documented behaviour - exact match, else queue to
reviews/unmapped_queue.csv - and raise the map rate by ADDING TAXONOMY ROWS,
never by widening the matcher. Report map rate and queue length separately.
A lower map rate with an honest queue beats 93% with silent misclassifications.

The taxonomy is generated from HGB_GKV_UKV_Standardisation_Map.xlsx. Do not
hand-edit lib/hgb_map.py embedded data. Aliases go in aliases/client_aliases.csv.
"@ -Encoding UTF8