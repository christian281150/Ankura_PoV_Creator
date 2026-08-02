# Company Profile Builder — Project Specification

**Purpose:** Generate the four-box "At a glance" company profile slide for German
private companies, from register + filing + web sources, with per-box content
selection and full provenance.

**Status:** Specification draft. Extraction layer partially built
(`Bundesanzeiger_Financial_Extracts`). Entity resolution, content-block model,
QA layer, and rendering not yet built.

**Context:** PE-facing performance improvement / turnaround advisory. Targets are
predominantly private German mid-caps (GmbH, GmbH & Co. KG), often family-owned,
often with incomplete disclosure.

---

## 1. What this is and is not

**Is:** a system that produces a defensible, provenance-carrying company profile
where every number on the slide traces to a named line in a named filing on a
named page.

**Is not:** a slide generator. Generation is the cheap part and will be commodity
within twelve months. The durable asset is the reconciliation and coverage
layer — knowing what can and cannot be said, and refusing to say the rest.

### Design principle

> A confidently wrong output is worse than a crash.

Every layer below is built so that missing or ambiguous data produces a visible
gap or a blocking flag, never a plausible-looking default.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ 0. ENTITY RESOLUTION            register-first, human-gated │
│    name/URL → HRA/HRB + Amtsgericht → group tree → target   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. ACQUISITION                                              │
│    1a Filings   (Unternehmensregister — existing tool)      │
│    1b Register  (Handelsregister, Gesellschafterlisten)     │
│    1c Web       (site, Wayback, careers, press)             │
│    1d News      (trade + regional press)                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. NORMALISATION                                            │
│    sheet classification → HGB std_id mapping → units →      │
│    presentation basis → scope/method flags                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. VALIDATION / QA          ← the actual product            │
│    reconciliation rules, anomaly detection, blocking flags  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. CONTENT BLOCKS                                           │
│    typed, slot-eligible, scored candidate blocks            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. GUI — SLOT ASSIGNMENT    ← the requested end state       │
│    per-box: ranked candidates, swap, preview, lock          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. RENDER                                                   │
│    python-pptx → Ankura master, footnotes auto-generated    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Layer 0 — Entity resolution

### Why this is layer zero

The Seidensticker Impressum names **TK Store-Management GmbH** as responsible for
website content under §5 TMG. That is a subsidiary. The group is **Textilkontor
Walter Seidensticker GmbH & Co. KG, HRA 8217 Bielefeld**, which files the
Konzernabschluss and holds ~22 shareholdings including TK Store-Management.

Feeding the wrong name to the extractor produces a clean, well-formatted,
completely wrong profile. Nothing downstream can detect this.

### Rules

| Rule | Detail |
|---|---|
| R0.1 | Resolve to `Amtsgericht + register type + number`, never to a name string |
| R0.2 | Walk the shareholding tree upward until no parent remains |
| R0.3 | An Impressum is a liability notice, not a corporate-structure statement |
| R0.4 | **Legal-form / register-type check:** a group filing a Konzernabschluss under an HRB when the operating parent is a KG (HRA) is a hard flag |
| R0.5 | Track historical names (`Textilkontor N.N. GmbH & Co. KG`) and predecessor parents |
| R0.6 | Human confirmation of the resolved entity is **permanent**, not a build-phase crutch |

### Output

```yaml
entity:
  legal_name: "Textilkontor Walter Seidensticker GmbH & Co. KG"
  register: { court: "Bielefeld", type: "HRA", number: "8217" }
  legal_form: "GmbH & Co. KG"
  komplementaer: "Seidensticker Verwaltungs GmbH"
  seat: "Bielefeld"
  fiscal_year_end: "30-04"
  files_konzernabschluss: true
  consolidated_entities_count: 22
  size_class: "gross"          # §267 HGB
  aliases: ["Seidensticker Gruppe", "Textilkontor N.N. GmbH & Co. KG"]
  subsidiaries_seen: ["TK Store-Management GmbH", "Seidensticker GmbH", ...]
  resolution_confirmed_by: "<user>"
  resolution_confirmed_at: "<timestamp>"
```

---

## 4. Layer 1 — Acquisition

### 1a. Filings (existing tool, needs fixes — see §5)

Current coverage on the Seidensticker test case: **FY2015–FY2025, 11 fiscal
years of Konzernabschluss.** The tool already extracts more than its README
claims:

- Konzernbilanz, Konzern-GuV, Konzern-Kapitalflussrechnung
- Konzernanhang (incl. §285 Nr. 4 revenue-split tables)
- Konzernanlagenspiegel, Konzerneigenkapitalspiegel
- Konsolidierungskreis
- Fristigkeiten der Verbindlichkeiten
- Lagebericht sections (3.2 Vermögenslage, 3.3 Finanzlage)

The blocker is **not acquisition**. It is that this content lands in sheets named
`FY2021_ (5)` and `FY2023_T€ 0 verrechnet. Der ver`. Sheet classification is a
small job that unlocks three of the four boxes.

### 1b. Register layer — build as a standing service

Structured, free, continuously updated, no CAPTCHA. Unlike the filing extractor,
this can run unattended.

Signals: Gesellschafterliste changes · Geschäftsführer / Prokurist changes ·
subsidiaries entering or leaving consolidation scope · §264 Abs. 3 / §264b
exemption filings · late filing · insolvency entries.

### 1c. Web scrape — targeted, not exhaustive

Full-text-every-page is the wrong spec. Target page classes:

| Class | German URL patterns | Feeds |
|---|---|---|
| Über uns / Historie | `/ueber-uns`, `/unternehmen`, `/historie` | Timeline, founding, family narrative |
| Standorte | `/standorte`, `/locations`, `/kontakt` | Footprint box (often better than the Anhang) |
| Presse / Aktuelles | `/presse`, `/news` | Dated own-voice event log |
| Karriere | `/karriere`, `/jobs` | Operating-model x-ray (see below) |
| Produkte | `/produkte`, `/sortiment` | Product box + images |
| Nachhaltigkeit | `/nachhaltigkeit` | Certifications, supply-chain claims |
| Impressum | `/impressum` | **Entity candidates only — never authoritative** |

**Wayback deltas** on the same URLs: store-count decline, dropped markets, pruned
product lines. These surface years before they appear in a filing.

**Job postings** are the most underused source. Dated, current, unfiltered by IR.
They reveal: ERP state (an S/4 migration ad = active transformation + capex
commitment), whether procurement is being centralised, which sites are growing,
whether finance is being rebuilt, and whether interim/restructuring profiles are
being hired. A "Head of Group Procurement (neu geschaffene Position)" ad tells
you sourcing consolidation has *not* happened — which is directly the
value-creation lever you would otherwise be guessing at. This source survives
when the filing is `klein`-class and says nothing.

**Images:** extraction is easy; classification is the work. Filter product shots
from hero/lifestyle/team photos on aspect ratio, alt-text, and DOM proximity to
product markup, then human-confirm. Flag copyright: acceptable for internal POV,
riskier if the deck circulates externally.

### 1d. News

Trade press (TextilWirtschaft, Lebensmittel Zeitung, Möbelmarkt) is where
mid-market restructuring surfaces, and it is paywalled. Regional press
(Westfalen-Blatt, used in the Seidensticker deck) is often free and covers
Mittelstand better than nationals.

---

## 5. Layer 2 — Normalisation, and current extractor defects

> **STALE — defects 1–5 below are fixed.** Diagnosed in 2026 against the FY2025
> Seidensticker *model workbook*, before the extractor was absorbed. The live
> normalisation path is `py/acquire/bundesanzeiger/extractor/consolidate.py`, which
> reads extracted-tables JSON, not the workbook. Verified against `main` @ ddc94e6,
> `109 passed, 1 xfailed`. Retained for provenance; do not action.
>
> | # | Status |
> |---|---|
> | 1 mapper not wired | Fixed. 14 rows consolidate on the FY2024 GuV |
> | 2 column-offset loss | Fixed in `consolidate.py` (`_year_blocks`). **Still open in the `ALL —` workbook writer**, which is a different module |
> | 3 German numbers | Fixed (`_parse_eur`) |
> | 4 unit mixing | Fixed per source table (`_unit_multiplier`) |
> | 5 phantom rows | Fixed (`_is_davon_note`, std_id collision detection) |
> | 6 year coverage | Open — multi-year assembly does not exist |
>
> **§5.2 is inverted.** It prescribes "longest-match wins, plus a parent/child level
> check." The implementation went further and better: `PL_GKV-5`, `-6`, `-7` are
> **deliberately absent from the taxonomy**, and `_UNSAFE_AGGREGATE_KEYS` leaves an
> aggregate heading unmapped rather than resolving it anywhere. An aggregate maps to
> nothing; sum its children. See `AGENTS.md` §P0.6.
>
> **§5.3** landed as `_SUBTOTAL_EXTENSIONS` plus a client alias, not as taxonomy rows.

Diagnosed against the FY2025 Seidensticker Konzernabschluss workbook.

| # | Defect | Evidence | Severity |
|---|---|---|---|
| 1 | HGB mapper not wired into export | `Mapping Audit`: `match_type = none` on every row, `std_id` empty throughout | Critical |
| 2 | Column-offset loss | FY25 Umsatzerlöse (111,815,106.14) sits in col 2; Materialaufwand in col 1. Overview reads col 1 → **revenue blank for all years** in `ALL — GuV` | Critical |
| 3 | German number strings unparsed | `'+ 1.914.645,32'` stored as text; every Bestandsveränderung and Sonstige-Erträge row lost | Critical |
| 4 | Unit mixing | FY2015–16 Bilanz in T€ (`18124`); FY2017+ in € (`2935515.69`) — same column | High |
| 5 | Phantom rows from label drift | `6. Abschreibungen` and `6. Abschreibungen auf immate` as separate rows; `- davon für Altersversorgung` three times | High |
| 6 | Inconsistent year coverage | Bilanz overview: 12 year columns. GuV overview: 4 | Medium |

### 5.1 Two mappers exist; the wrong one is bundled

- `hgb_map.py` (bundled) — exact-normalised lookup only, returns `none` on any
  miss, no fallback. **This produced the all-`none` Mapping Audit.**
- `hgb_lookup_reference.py` (newer) — resolves `1. Umsatzerlöse → PL_GKV-1`,
  `A. Anlagevermögen → BS-A.A` correctly. 95 taxonomy rows, 205 synonyms.

Swapping in the reference mapper largely resolves defects 1 and 5.

### 5.2 Mapper precision bug

`4. Materialaufwand → PL_GKV-5a` — the *sub-item*
("Aufwendungen Roh-, Hilfs-, Betriebsstoffe"), not the parent. The substring
fallback returns first-match on dict-iteration order: nondeterministic and
silently wrong.

**Fix:** longest-match wins, plus a parent/child level check. Never let a heading
resolve to one of its own children.

### 5.3 Taxonomy gaps (all return `None`)

| Missing label | Why it matters |
|---|---|
| `Veränderung des Bestands an unfertigen und fertigen Erzeugnissen` | Produced the finding in §6 |
| `Konzernbilanzverlust` | Accumulated loss position |
| `Nicht durch Vermögenseinlagen gedeckter Verlustanteil` | **Negative equity.** Highest-signal line in a German balance sheet for a turnaround shop |

### 5.4 Additional normalisation requirements

- **Unit normalisation** per source table, not per workbook (`EUR` vs `TEUR`)
- **Scope flag** per year: consolidation perimeter changes, entities added/removed
- **Method flag** per year: GKV vs UKV, and any switch between them
- **Statement splitter:** current logic uses `"Summe Passiva"` as the Bilanz
  terminator — a GKV/German-label assumption that breaks on abweichende
  Gliederung and IFRS-converged presentation
- **Cash flow:** CF rows currently bypass HGB lookup for regex synonyms due to
  encoding artefacts in embedded data. Data-hygiene fix, but it will break on
  DRS 21 variants

---

## 6. Layer 3 — Validation / QA

**This layer is the product.** Generation will be commodity; reconciliation will not.

### 6.1 The finding that justifies the layer

The published Seidensticker POV charts a series labelled **"Revenue in €m"**.
It is not revenue. It is Gesamtleistung — Umsatzerlöse plus Bestandsveränderung
plus sonstige betriebliche Erträge. Reconciled across five years from the
Konzern-GuV:

| FY | Umsatzerlöse | Bestandsveränderung | Sonst. betr. Erträge | = Deck "Revenue" |
|---|---|---|---|---|
| FY21 | 100.4 | (4.0) | 9.8 | 106.2 ✓ |
| FY22 | 103.1 | 5.1 | 9.2 | 117.3 ✓ |
| FY23 | 126.8 | 4.0 | 3.1 | 134.0 ✓ |
| FY24 | 103.2 | **(8.8)** | 7.8 | 102.1 ✓ |
| FY25 | 111.8 | 2.7 | 1.9 | 116.5 ✓ |

Five-for-five against the slide. Consequences:

- **"+14.1% back to growth" is +8.4%** on actual revenue. The gap is almost
  entirely the FY24 inventory drawdown — the same €8.8m the deck footnotes for
  material costs but does not apply to the topline it equally distorts.
- **FY23→FY24 is −18.6% on Umsatzerlöse**, not −24%. Still unexplained on the slide.
- **Sonstige betriebliche Erträge fell 9.8 → 1.9** over five years, sitting
  inside the "revenue" line — flattering FY21–22 and steepening the apparent
  recovery. This is where disposal gains and one-offs live.

A rule that reconciles every headline figure to a GuV line catches this before
the deck leaves the building.

### 6.2 Blocking rules

| Rule | Behaviour on failure |
|---|---|
| V1 `presentation_basis` | Any figure labelled "Revenue" whose basis ≠ `umsatzerloese` → **block render** |
| V2 Unit consistency | Mixed EUR/TEUR within one series → **block render** |
| V3 Scope continuity | Perimeter change between adjacent years with no note → **require human note** |
| V4 Method continuity | GKV↔UKV switch mid-series → **require human note** |
| V5 Material YoY move | Any line moving >15% YoY → **require human note** |
| V6 Ratio break | Cost ratio breaking trend >5pp → **require human note** |
| V7 Unmapped label | Label with no `std_id` used in a charted series → **block render** |
| V8 Bilanz balance | Aktiva ≠ Passiva → **block render** |
| V9 Negative equity | `Nicht durch Vermögenseinlagen gedeckter Verlustanteil` present → **flag, never suppress** |

### 6.3 Auto-footnote generation

Every human note attached to a V3–V6 flag becomes a slide footnote automatically.
This is how the pipeline produces the `−€8.8m inventory drawdown` type of
footnote rather than depending on someone being awake.

### 6.4 Peer-comparison guardrail

Not slide-6 scope, but the same discipline applies downstream: benchmarking a
vertically integrated own-manufacturer against asset-light DTC peers (e.g.
Charles Tyrwhitt) or an unnamed private-label player compares structurally
different margin profiles. Any peer set must carry a `business_model` tag and
flag cross-model comparisons.

---

## 7. Layer 4 — Content block model

This is the layer that makes the requested GUI possible.

### 7.1 Core idea

Content is **not** authored per box. It is produced as a pool of typed blocks,
each declaring which slots it can occupy and how well it is evidenced. The GUI
then offers, per box, a ranked list of eligible blocks.

```yaml
block:
  id: "fin.revenue_ebitda_series"
  kind: "chart.column_line"
  title: "Financials"
  eligible_slots: ["top_right", "bottom_right"]
  coverage: 0.95            # 0-1, how complete the underlying data is
  confidence: "high"        # high | medium | low
  years_available: [2015, ..., 2025]
  presentation_basis: "umsatzerloese"
  units: "EUR_m"
  provenance:
    - { field: "revenue_FY25", doc: "Konzernabschluss FY2025",
        page: 12, line: "1. Umsatzerlöse", std_id: "PL_GKV-1" }
  validation: { V1: pass, V2: pass, V5: ["FY24: -18.6% — note required"] }
  blocking_flags: []
  footnotes_auto: ["FY24 depressed by €8.8m inventory drawdown"]
```

### 7.2 Block catalogue (v1)

| Block ID | Kind | Source | Typical slot |
|---|---|---|---|
| `bo.business_overview` | bullets | Lagebericht + site | top-left |
| `bo.identity_ownership` | bullets | Register | top-left |
| `fin.revenue_ebitda_series` | column+line chart | GuV | top-right |
| `fin.cost_structure` | stacked column | GuV | top-right |
| `fin.balance_summary` | table | Bilanz | top-right |
| `geo.revenue_split` | stacked column | Anhang §285 Nr. 4 | bottom-right |
| `geo.footprint_map` | map | Anhang + site | bottom-right |
| `prod.product_grid` | image grid | Site | bottom-left |
| `prod.segment_table` | table | Anhang | bottom-left |
| `mgmt.leadership` | bullets | Register + site | bottom-left |
| `time.event_timeline` | timeline | Press + Lagebericht | any |

### 7.3 Comparability constraint

Free box-level swapping breaks cross-profile comparability. If Target A shows
Products & Geography and Target B shows Management & Timeline, ten profiles
cannot be laid side by side — and for PE screening, comparability *is* the value.

**Rule:** a canonical default layout exists per size class. Deviation is allowed
but recorded in the profile metadata and shown in the GUI as
`⚠ non-standard layout`.

### 7.4 Degradation, not substitution

When a box's canonical block is unavailable, the box prints the gap:

> *Revenue not separately disclosed (§276 HGB abridgement — Rohergebnis only)*

It does **not** silently swap in a product grid. A stated gap is information; a
substitution is a lie by omission.

---

## 8. Coverage probe

Runs after acquisition, before slot assignment. Drives the GUI's ranked lists.

```
COVERAGE — Textilkontor Walter Seidensticker GmbH & Co. KG (HRA 8217)

  Financials        ████████░░  high    11y Konzernabschluss FY15–FY25
  Business model    ████████░░  high    Lagebericht + corporate site
  Geography split   ██████░░░░  medium  §285 Nr. 4, group level only
  Products          ████████░░  high    site, ~40 product images
  Management        ████████░░  high    register + site
  Timeline          ███████░░░  high    press + Lagebericht
  Jobs signal       █████░░░░░  medium  6 open roles

  ⚠ 3 blocking flags · 4 notes required
```

Expected distribution by §267 class:

| Class | Threshold (2 of 3) | Available | Profile viability |
|---|---|---|---|
| Klein | ≤€7.5m BS / ≤€15m rev / ≤50 FTE | Balance sheet only | Financials box impossible from filings |
| Mittelgroß | ≤€25m / ≤€50m / ≤250 | Abridged GuV (from Rohergebnis), Lagebericht, Anhang | **Revenue often invisible** (§276) |
| Groß | above | Full GuV, Lagebericht, §285 Nr. 4 split | Full profile |

The mittelgroß case is the one to internalise: §276 permits collapsing revenue
and material costs into **Rohergebnis**. For a PE mid-market target — the core
hunting ground — revenue is frequently not visible at all. That is a coverage
limit, not an engineering problem, and it determines the addressable universe.

---

## 9. Layer 5 — GUI specification

### 9.1 Screen flow

```
[1] Entity search        name / URL / HRB
        ↓
[2] Entity confirmation  resolved tree, size class, filings found
        ↓                MANDATORY — cannot be skipped
[3] Acquisition run      progress per source; CAPTCHA gate on filings
        ↓
[4] Coverage probe       matrix + blocking flags
        ↓
[5] Slot assignment      ← the main screen
        ↓
[6] Flag resolution      write notes for V3–V6; unblock V1/V2/V7/V8
        ↓
[7] Preview & export     .pptx into Ankura master
```

### 9.2 Slot assignment screen

```
┌──────────────────────┬──────────────────────┐
│ TOP-LEFT             │ TOP-RIGHT            │
│ [Business Overview ▾]│ [Financials ▾]       │
│  ● Business Overview │  ● Revenue & EBITDA  │
│  ○ Identity & Owner. │  ○ Cost structure    │
│  ○ Timeline          │  ○ Balance summary   │
│                      │  ⚠ 1 note required   │
├──────────────────────┼──────────────────────┤
│ BOTTOM-LEFT          │ BOTTOM-RIGHT         │
│ [Products ▾]         │ [Geography ▾]        │
│  ● Product grid      │  ● Revenue split     │
│  ○ Segment table     │  ○ Footprint map     │
│  ○ Leadership        │  ⊘ Segment detail    │
│                      │    (not disclosed)   │
└──────────────────────┴──────────────────────┘

 ● selected   ○ available   ⊘ unavailable (reason shown)
 [Preview]  [Lock layout]  [Export .pptx]
```

Behaviour:

- Dropdown lists only blocks whose `eligible_slots` include this slot
- Options ordered by `coverage × confidence`
- Unavailable blocks are **shown greyed with reason**, not hidden — the absence
  is itself information
- Selecting a block updates the preview and the footnote set live
- Blocks with unresolved blocking flags cannot be selected until resolved
- Deviating from canonical layout raises `⚠ non-standard layout`
- `Lock layout` freezes the assignment so a re-run with fresher data keeps it

### 9.3 Non-negotiable

Screen [2] stays human-gated permanently. Everything downstream inherits an
entity error and nothing downstream can detect it.

---

## 10. Layer 6 — Render

- `python-pptx` into the Ankura master template
- Footnotes assembled automatically from `footnotes_auto` + human notes
- Source line assembled from the provenance set
- Every rendered figure carries a hidden `std_id` + doc + page tag in slide notes,
  so the deck is auditable after the fact
- Export a companion `.json` profile alongside the `.pptx`

---

## 11. Build sequence

| Phase | Deliverable | Rationale |
|---|---|---|
| **P0** | Fix extraction defects 1–4; swap in reference mapper; add the 3 missing taxonomy rows | Nothing downstream is trustworthy until this is done |
| **P1** | Sheet classifier — name the `FY2021_ (5)` sheets by content type | Unlocks 3 of 4 boxes from data already on disk |
| **P2** | JSON output + provenance layer | Excel is a dead end for a pipeline |
| **P3** | Entity resolution service (register layer) | Also the origination spine — see §12 |
| **P4** | Validation rules V1–V9 + auto-footnotes | The product |
| **P5** | Web + jobs scraper | Fills non-financial boxes |
| **P6** | Coverage probe | Drives the GUI |
| **P7** | Content block model | Enables slot assignment |
| **P8** | GUI slot assignment | The requested end state |
| **P9** | python-pptx render | Cheapest layer, built last on purpose |

---

## 12. Strategic note

**The exhaust is worth more than the output.**

Running this across a target universe produces something more valuable than 400
profiles: a coverage map whose *holes* are the signal. In German mid-market,
disclosure behaviour degrades before financials do, because the Geschäftsführer
controls filing timing and the auditor controls language.

Monitorable, unattended, no CAPTCHA:

- filing lateness vs. §325 deadline
- abridgement beyond the legal minimum for the size class
- Fortführungsprognose language shifts year over year
- Gesellschafterliste and Geschäftsführer changes
- subsidiaries entering or leaving consolidation scope
- careers-page signals (interim/restructuring hires, ERP migrations)

Knowing which of 400 family-owned Mittelständler just filed nine months late with
softened going-concern language is an origination signal no sponsor has. A nice
four-box slide is a slide.

**Corollary on positioning:** if POV production gets cheap, the savings accrue to
sponsors, not to the firm. Today an outside-in POV is a costly, credible signal.
Drop its cost 70% and sponsors expect one from six firms instead of two, on every
situation. Pitch-stage margin goes to zero and the moat migrates from
*identifying* potential to *underwriting* it. Build this as a defensive necessity
and an origination engine — not as a margin play.

---

## 13. Open items

### Blocking on user

1. **Web/news licensing** — TextilWirtschaft, Genios, LexisNexis, or open web only?
2. **Render target confirmation** — python-pptx into the Ankura master, or
   Markdown/HTML intermediate an analyst finishes manually?
3. **Ankura master template** — a `.potx` or a representative `.pptx` with the
   four-box layout, to bind placeholders against
4. **Size-class mix of the target list** — determines how much of the build is
   degradation handling vs. full-profile rendering
5. **GUI framework** — extend the existing CustomTkinter app, or a separate web UI?

### Decisions taken

- Fixed four-box skeleton with graceful degradation, not variable box topics
- Entity confirmation is permanently human-gated
- Register layer built as a standing service, not a per-profile lookup
- Validation layer built before rendering

### Known unknowns

- §285 Nr. 4 geography split granularity varies by year; may not support a
  consistent 9-year series
- Product image copyright position for externally circulated decks
- CAPTCHA on the filings source caps throughput and prevents unattended batch
  refresh of the financial layer

---

*Test case throughout: Textilkontor Walter Seidensticker GmbH & Co. KG,
HRA 8217 Bielefeld. FY2015–FY2025 Konzernabschluss extracted; findings in §5–§6
derived from that workbook.*
