# Appendix — Enum Dictionary

> Every code/enum/constant the product behaviour depends on. Sources: `config.py`,
> `tokens.py`, `ur_extractor.py`, `lib/hgb_map.py`.

## Statement type codes (`type`)
The integer that classifies every table and drives grouping, badges, and tabs.

| Code | `config.TYPE_LABELS` | GUI label (`_TYPE_LABELS`) | Meaning |
|------|----------------------|----------------------------|---------|
| 0 | Bilanz | Bilanz | Balance sheet (HGB §266) |
| 1 | GuV / Ergebnis | GuV | Profit & loss (HGB §275) |
| 2 | Kapitalfluss | Cashflow | Cash flow statement (DRS 21) |
| 99 | Sonstige | Other | Notes / Anhang / anything else — never consolidated |

**Effective type** = a manual override (when `_override_applied` and integer `type`) wins
over the automatic content classifier `_classify_table()`.

### `_classify_table()` keyword signals (automatic classification)
- **0 Bilanz** — rows/heading contain: aktiva, passiva, bilanzsumme, eigenkapital,
  verbindlichkeiten, anlagevermögen (heading: konzernbilanz / jahresbilanz / `bilanz`).
- **2 Kapitalfluss (checked before GuV)** — cashflow, zahlungsmittel, kapitalfluss,
  investitionstätigkeit, finanzierungstätigkeit (indirect-method CF starts with
  "Jahresüberschuss", a GuV word — heading disambiguates).
- **1 GuV** — umsatzerlöse, jahresergebnis, ergebnis, gewinn, verlust, ebitda, ebit,
  zinsergebnis (heading: gewinn-…-verlust / ergebnisrechnung).
- **99 Sonstige** — Eigenkapitalveränderungs-/spiegel, Anhang/notes, anything unmatched.

## Type badge styling (`tokens.BADGE["type"]`)
| Type | Background | Foreground | Border | Intent |
|------|-----------|-----------|--------|--------|
| Bilanz / GuV / Cashflow | neutral grey `#F3F4F6` | `#374151` | `#E5E7EB` | Engine success ≠ celebration |
| Other | amber `#FFFBEB` | `#B45309` | `#F59E0B` | Workflow item demanding attention |

## In-overview badge (`tokens.BADGE["in_overview"]`)
| State | Glyph | Colour | Meaning |
|-------|-------|--------|---------|
| included | ✓ | green `#10B981` | Table feeds its statement's consolidation |
| excluded | — | grey `#9CA3AF` | Excluded by the analyst |
| overridden | ✓* | green | Included via a manual override |

## HGB lookup `match_type` (`hgb_map.lookup`)
| Value | Meaning | UI treatment |
|-------|---------|--------------|
| normalized | exactly one canonical match | high-confidence dot; Canonical/std_id shown |
| ambiguous | the normalized key maps to >1 canonical code | listed as candidates with **Remap**; queued for review |
| none | no curated synonym matched | "No HGB match"; queued for **Needs Review** |

> Lookup is exact-normalized only — it never substring/fuzzy-guesses (project rule).

## Canonical `row_type` (drives grid row styling)
| Value | Derivation | Grid effect |
|-------|-----------|-------------|
| subtotal | taxonomy `is_subtotal = true` (e.g. Bruttoergebnis vom Umsatz, Jahresüberschuss) | bold, tinted |
| memo | Balance-sheet section headers (level ≤ 2: AKTIVA/PASSIVA, A./B./C. blocks) | section-header style |
| line | everything else | normal line item (indented, alternating tint) |

## Canonical std_id scheme (HGB code) — `lib/hgb_map.py`
| Prefix | Statement | Example |
|--------|-----------|---------|
| `BS-A.*` | Bilanz — Aktiva | `BS-A.B.II.1` = Forderungen aus L+L |
| `BS-P.*` | Bilanz — Passiva | `BS-P.C.2` = Verb. ggü. Kreditinstituten |
| `PL_GKV-*` | P&L, nature-of-expense (§275 Abs. 2) | `PL_GKV-5a` = Materialaufwand |
| `PL_UKV-*` | P&L, function-of-expense (§275 Abs. 3) | `PL_UKV-2` = Herstellungskosten (COGS) |
| `STAT` | statistical / carry-forward (not in the JA) | — |

## P&L format (`pnl_format`) — GKV vs UKV
| Value | Meaning |
|-------|---------|
| GKV | Gesamtkostenverfahren (nature of expense) — Material/Personal/AfA lines |
| UKV | Umsatzkostenverfahren (function) — Herstellungs-/Vertriebs-/Verwaltungskosten |
| BS / STAT | balance-sheet / statistical positions |

GKV↔UKV are **not** 1:1; the bridge (`pnl_format_bridge`) flags positions needing
cost-centre allocation. See [data-schemas-and-mapping.md](./data-schemas-and-mapping.md#hgb-mapping).

## SKR variants (account-number ranges) — reference data
| Variant | Note |
|---------|------|
| SKR03 | Revenue 8xxx, Material 3xxx, Personal 4xxx |
| SKR04 | Revenue 4xxx, Material 5xxx, Personal 6xxx (inverted vs SKR03) |
| IKR | Industrie-Kontenrahmen |

> Used by the reference helper (`lib/hgb_data/hgb_lookup_reference.py`) for account-level
> mapping; the GUI currently maps **labels**, not account numbers.

## Currency units (`config.CURRENCY_UNITS`) — display only
`TEUR` (default) · `€k` · `€'000` · `€m` · `none`. Shown once in OVERVIEW year headers;
never converts values.

## Themes (`config.build_theme`)
`Light` (default) and `Dark`. Each is a flat palette dict (BG, PANEL, CARD, BORDER, IND,
text T1/T2/T3, GREEN/AMBER/RED, ROW_* grid tints, TREE_* treeview colours, LOG_*).

## Number format (Settings)
| Option | Decimal | Thousands |
|--------|---------|-----------|
| German (default) | `,` | `.` |
| English | `.` | `,` |

## Worker State machine (`ur_extractor.State`)
`SEARCH · SELECT_DOC · CAPTCHA · DOWNLOAD · EXTRACT · EXPORT · QUIT` — the internal phases
of the acquisition pipeline.

## Timeouts (`config.py`, ms unless noted)
`PAGE_LOAD 15000 · SEARCH 20000 · CAPTCHA 20000 · DOWNLOAD 15000 · CLICK 8000 ·
CAPTCHA_WAIT_S 2 (seconds)`.
