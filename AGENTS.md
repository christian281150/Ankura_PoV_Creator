# AGENTS.md  Company Profile Builder

Implementation brief for coding agents (Codex, Claude Code, Cursor).
Read this before touching the repo. Full design rationale lives in
`company-profile-builder-spec.md`; this file is the operational contract.
---

## Active operational plan

``docs/final-push-lanes.md`` — lane ownership, Wave 0 blockers, per-lane acceptance
witnesses and agent prompts for the current push. Read it before starting any lane.

Note: that document records four defects in this file and in
``docs/company-profile-builder-spec.md``. Until AGENTS.md ss.P0 is rewritten, ss.P0.6 is
WRONG: it instructs mapping ``4. Materialaufwand`` to a parent that does not exist in
``hgb_taxonomy.csv`` and must not. ``_UNSAFE_AGGREGATE_KEYS`` leaves it unmapped by design.

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

### Golden reconciliation (all values EUR m)

> **Provenance warning.** This table was produced by `p0_normalise.py`, the
> superseded normaliser whose other outputs (`out.json`, `py/render/qa/*`) have been
> deleted as unwitnessed. It is retained because parts of it *do* have external
> witnesses — but not all of it, and the difference matters:
>
> | Rows | Witness |
> |---|---|
> | Gesamtleistung, FY2021–FY2025 | **The published deck.** Five-for-five against the slide (spec §6.1). Genuine external corroboration |
> | FY2024 Umsatzerlöse 103.2 | **The extractor**, independently, from the PDF: 103,152,036.57 |
> | FY2017–FY2020, all columns | **None.** `p0_normalise` self-report only |
> | Every component column not listed above | **None.** Self-report |
>
> Treat unwitnessed rows as provisional. Do not cite a coverage or map-rate figure
> derived from them. Note also that the one figure in this project with an
> independent witness — **EBIT −993,758.07, corroborated by the FY2024 Lagebericht's
> T€ −993 through `tests/test_lagebericht.py`** — does not appear in this table at
> all. It is the strongest acceptance target the project has.

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

### P0 — Extraction fixes  ✅ LANDED. Do not re-implement.

> Verified against `main` @ ddc94e6, `109 passed, 1 xfailed`. The live
> implementation is `py/acquire/bundesanzeiger/extractor/consolidate.py`, **not**
> `p0_normalise.py`. Rows below are kept for provenance; all are done, and P0.6 as
> originally written is **wrong** — see the note beneath the table.

| ID | Task | Acceptance |
|---|---|---|
| ~~P0.1~~ | Wire the mapper into export | DONE. 14 rows consolidate on the FY2024 GuV; six labels unmapped on that fixture. "0%" and "93 unmapped" are both stale |
| ~~P0.2~~ | Year-block column coalescing | DONE — `_year_blocks` + `_column_actuals`. FY2024 Umsatzerlöse = 103,152,036.57 |
| ~~P0.3~~ | German number parsing | DONE — `_parse_eur` / `_parse_num_cell` |
| ~~P0.4~~ | Unit normalisation | DONE — `_unit_multiplier`. Note: a **mid-series** T€→€ break still cannot be expressed per-year in Path B |
| ~~P0.5~~ | Merge on `std_id` not raw label | DONE, plus `_is_davon_note` exclusion and std_id collision detection that queues **both** sides |
| **P0.6** | ~~Longest-match mapper~~ | **SUPERSEDED — THIS INSTRUCTION IS WRONG. DO NOT FOLLOW IT.** See below |
| ~~P0.7~~ | Add missing taxonomy rows | DONE, but **not** as taxonomy rows — as `_SUBTOTAL_EXTENSIONS` (`PL_GKV-GESAMTLEISTUNG`, `-ROHERGEBNIS`, `-BILANZVERLUST`) and a client alias for `Veränderung des Bestands…` |

#### P0.6 is inverted — read this before touching the mapper

There is **no parent** to map an aggregate heading to. `PL_GKV-5`, `PL_GKV-6` and
`PL_GKV-7` are **deliberately absent from `hgb_taxonomy.csv`** so that a heading can
never resolve to one of its own children. `_UNSAFE_AGGREGATE_KEYS` in
`consolidate.py` covers `materialaufwand`, `personalaufwand`, `abschreibungen` and
returns `unsafe_aggregate_heading`, leaving the row **unmapped and visible in the
review queue**.

That is the intended behaviour, not a defect. An agent that "fixes" P0.6 as written
will reintroduce the parent/child conflation the guard exists to prevent, and the
fix will look like it works.

Correct rule: **an aggregate heading maps to nothing. Sum its children instead.**
This filing reports `PL_GKV-7a` only; a filing reporting 7a *and* 7b must sum both,
and must fail closed when it cannot distinguish "child absent from the filing" from
"child present but unmapped" (rule V12, not yet written).

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


## Mapping discipline - inherited from the extractor's CLAUDE.md

The mapper is exact-match only. Never auto-pick an ambiguous match: exact match,
else queue to py/normalise/reviews/unmapped_queue.csv. Raise the map rate by
adding taxonomy rows or client aliases, never by widening the matcher.

Report map rate and queue length separately. A lower map rate with an honest
queue beats a high one with silent misclassifications. A queue of pre-BilRUG
subtotals is a healthy end state - do not force it to zero.

The taxonomy is generated from HGB_GKV_UKV_Standardisation_Map.xlsx. Do not
hand-edit lib/hgb_map.py embedded data.

**Aliases go in `py/acquire/bundesanzeiger/aliases/client_aliases.csv`.** This
instruction previously named `py/normalise/aliases/client_aliases.csv`, which is
read by `p0_normalise.py` only. `consolidate.py` — the live mapper — resolves
`_ALIASES_PATH` to the extractor directory and **never reads the normalise file**.
Following the old instruction adds a row that loads without error and never
matches: silent, and the direct cause of the two divergent alias files that existed
until e033262.

Schema is `client_label,std_id,client,note`. Quote any field containing a comma —
an unquoted `Roh-, Hilfs-` splits silently, no parse error, no queue entry, the
mapping simply never happens. Ensure the file ends with a newline before appending.

Every alias needs a note stating **why the mapping is accounting-correct**. "Exact
published-label variant" is not a justification; every row that carried only that
note has been reviewed, and two were wrong (see e033262).


## Environment

Agent sandboxes have NO network access. Do not attempt pip install or npm install.
Dependencies are pre-installed by the human before the session starts.
Use .venv\Scripts\python.exe directly; do not activate the venv. (Activating also
works, but calling the interpreter by path removes a whole class of
"ModuleNotFoundError on a package that is already installed" false alarms caused by
hitting the global interpreter.)
If a dependency is missing, stop and report it - do not work around it.

Known trap: `rich` is a **hard import at `extractor/_core.py:7`**. Without it the
suite does not fail — it fails to *collect*, and reports nothing at all. A CLI
presentation library currently gates test collection. Lazy-import it when convenient.

`pwsh` is not installed; use `powershell`. PowerShell has no heredoc: use `@'...'@`
for literal here-strings, `@"..."@` for interpolating. `Get-Content` renders UTF-8
as cp1252 — `VerÃ¤nderung` in the console does not mean the file is corrupt; check
bytes with `python -c "print(open(p,'rb').read()[:120])"` and expect `\xc3\xa4`.
## Unmapped queue location

**Inverted as of the absorb — the old text below the line was correct only while
the extractor was a submodule. It is not one.**

`consolidate.py` resolves `_QUEUE_PATH` to
`py/acquire/bundesanzeiger/reviews/unmapped_queue.csv` and **writes there**. That is
the live queue (238 rows, 8 columns, carrying `doc_label` / `heading` / `page_start`).
`py/normalise/reviews/unmapped_queue.csv` (12 rows, 4 columns) belongs to
`p0_normalise.py` and cannot carry page provenance.

Two standing cautions on the live queue:

1. It is **append-only across every filing ever run** and mixed-provenance — the
   "93 unmapped labels" figure is the deduped historical total including 124 CTEC
   IFRS refusals, not a per-run number. Filter before quoting it.
2. It **systematically under-reports.** Rows discarded by `if not label: continue`
   (`consolidate.py`, ~line 220) never reach the mapper, so they never reach the
   queue. Any coverage metric built on it is optimistic by exactly the subtotal rows
   — which are the structurally important ones. Unresolved: whether this file is
   tracked state or scratch.
The mapper is exact-match only. Never auto-pick an ambiguous match: exact match, else queue to py/normalise/reviews/unmapped_queue.csv. Raise the map rate by adding taxonomy rows or client aliases, never by widening the matcher.

## Backlog - mapper correctness (lane A follow-up)

1. ~~Collision detection.~~ **DONE.** `_column_actuals` queues both sides with
   `match_type = std_id_collision` and drops the entry rather than first-wins.
2. Alias justification. "Exact published-label variant" is not a reason. Each
   alias needs a note stating why the mapping is accounting-correct.
3. CSV loaders must use encoding="utf-8-sig". PowerShell's Set-Content -Encoding
   UTF8 writes a BOM; utf-8 parsing then corrupts the first column header.
4. Taxonomy gaps to propose upstream: minority interest (auf nicht beherrschende
   Anteile entfallender Gewinn/Verlust), participation losses (the taxonomy has
   Ertraege only), and a decision on whether Gewinnruecklagen appropriation flows
   belong in the model at all.
5. V10 tie-out check. **The rule is written** — `contract/rules.json` V10,
   implemented at `py/validate/validator.py:392` with an expected/actual/delta
   message. It has nothing to check, because the subtotal rows are discarded at
   `consolidate.py` ~line 220 before the mapper sees them. **Removing that guard
   turns on a rule that already exists** — which is the acceptance criterion for
   that work, not a new test. Subtotals are retained with row_type = "subtotal".
   Betriebsergebnis should equal the operating lines above it; Ergebnis nach
   Steuern should equal the lines above it. Where a subtotal does not reconcile,
   either the parser missed a row or the filing uses a different presentation
   basis than assumed. This is the only validation that checks against the
   filing's own arithmetic rather than against our assumptions. Implement in P4.

## Extractor is the binding constraint

Two findings, same root cause: the extractor emits tables only, and loses page
numbers.

- The Lagebericht narrative (§3.1 Ertragslage, §3.2 Vermögenslage, Nachtragsbericht,
  Chancen- und Risikobericht) is absent from the workbook. py/normalise/lagebericht.py
  is complete and correct but has nothing to parse.
- provenance.page is null throughout, because the export lost the page mapping.

Everything downstream is well-built and starved of input. Effort belongs in
py/acquire/bundesanzeiger, not in py/normalise.

## Multi-year assembly is missing

The eleven-year series in the Seidensticker model workbook was stitched from
eleven separate PDFs. The canonical chain handles one PDF at a time, and every
downstream consumer assumes a multi-year series exists.

PDF -> extract_tables_from_pdf -> consolidate -> canonical JSON is single-filing.
There is no step that merges N canonical exports into one entity series, resolves
overlapping comparatives (each filing states current and prior year), or flags
restatements where the same fiscal year differs between filings.

That last point matters most: when FY2024 appears as a comparative in the FY2025
filing and as the current year in the FY2024 filing, a difference is a restatement
and must be flagged, never silently resolved by taking one.


## Path B — user-supplied financials (40% of engagements)

Non-German targets have no Bundesanzeiger filing. The analyst supplies financials
as xlsx or PDF, plus a website for narrative and images.

Architecture: canonical JSON is the product boundary. Path A (German filing ->
extractor) and Path B (user file -> mapping screen) both emit it; everything
downstream consumes it and must never assume which path produced it.

Path B requires an explicit mapping screen. The user maps their columns to std_ids
once per company, and MUST declare framework, pnl_method, unit, fiscal-year
convention, and presentation_basis per series. No defaults, no inference. If a
declaration is missing, no canonical JSON is emitted.

earnings_basis = adjusted is only available if the user supplies the reconciliation
adjustments, same rule as Path A.

Open question: are non-German engagements one-off or recurring? Recurring requires
saved mappings per company and a refresh path — a materially larger build.
## Untracked state

py/acquire/bundesanzeiger/data/ is gitignored (.gitignore:19). It holds two append-only GUI event logs: row_merges.csv (label-merge decisions — genuine asserted judgment, currently unattributed and unversioned) and table_overrides.csv (overview-inclusion toggles — UI noise). Both are CTEC-only as of 2026-06-28. row_merges belongs in the asserted-content layer when that is built.
