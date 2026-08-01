# HGB Standardisation — Claude Code project memory

Standardise German HGB statutory packs (GKV/UKV P&L, §266 balance sheet, DRS 21 cash flow)
to one canonical chart so entities can be compared across a portfolio. The canonical key is
`std_id`. **Always map through the `hgb_map` utility — never hand-roll German→canonical guesses
and never hardcode statutory line names in analysis code.**

## The mapping utility

`lib/hgb_map.py` — self-contained, zero dependencies, data embedded. Import and use:

```python
import lib.hgb_map as h

h.by_id("PL-010")          # full record by canonical id
h.lookup(label)            # client label -> {query, normalized, match_type, candidates}
h.resolve(label)           # single std_id if unambiguous, else None
h.records("pl")            # all records for "pl" | "balance_sheet" | "cash_flow"
h.to_dataframe("pl")       # pandas view (lazy import)
h.normalize(text)          # the matching normaliser (lower, drop parens/punct, keep umlauts)
h.SYNONYM_INDEX            # {normalized_form: [std_id, ...]}
h.DRIFT_LOG                # reform/synonym reference (BilMoG, BilRUG, DRS 21, SKR03/04)
```

Each record carries: `std_id`, `canonical_en`, `canonical_de`, `hgb_ref`, `row_type`,
`ifrs_analogue`, `synonyms`, `note`; P&L adds `gkv_de`/`gkv_no`/`ukv_de`/`ukv_no`/`block`/`section`;
CF adds `drs21_de`/`sign`/`ias7_analogue`. `row_type ∈ {line, memo, subtotal, removed}`.

## Rules (these override convenience — the strings *look* related but the accounting isn't)

1. **Never auto-pick an ambiguous match.** `lookup()` returns `match_type` and a `candidates`
   list. If `match_type == "none"` OR `len(candidates) > 1`, append the label to
   `reviews/unmapped_queue.csv` and leave it unmapped. Do **not** eyeball a "closest" guess —
   a wrong bucket is a silent six-figure misclassification nobody catches until reconciliation.
   `resolve()` already returns `None` on ambiguity; respect that, don't work around it.
2. **Filter `row_type == "line"` when mapping actuals.** Exclude `memo`, `subtotal`, and
   BilRUG-`removed` rows so they don't pollute joins or get double-counted.
3. **GKV ≠ UKV line-for-line.** Never equate `Materialaufwand` with `COGS`, or a nature-method
   cost line with a function-method one. The bridge is
   `COGS+Selling+Admin = Material+Personnel+D&A − Δinventory − own-work-capitalised`.
   To compare cost categories across mixed-method entities you need the Anhang nature-breakdown —
   flag this rather than forcing a comparison.
4. **Respect the BilRUG (FY2016) boundary.** `Umsatzerlöse` was redefined that year (absorbed
   items from `sonstige betriebliche Erträge`). Same label, bigger number. Never compare revenue
   or margins across the FY2015/FY2016 line without flagging the definition change. The
   `Ergebnis der gewöhnlichen Geschäftstätigkeit` subtotal and the extraordinary block were also
   deleted — rebuild them manually for post-2016 data if a legacy model needs them.
5. **Confirm the method before mapping a P&L.** Determine whether the pack is GKV (Abs. 2) or
   UKV (Abs. 3) — the line set differs. Don't assume.
6. **Tie-outs:** cash-flow closing balance should tie to `BS-A-240`; net income `PL-240` ties to
   `BS-P-150`. Surface a mismatch, don't paper over it.

## Standard trial-balance mapping workflow

When asked to map a client trial balance / statutory pack:
1. Read client line labels.
2. For each label: check `aliases/client_aliases.csv` first (client-specific overrides win),
   else `h.lookup(label)`.
3. Unambiguous → assign `std_id`. Ambiguous or no match → write to `reviews/unmapped_queue.csv`
   with the label, `match_type`, and candidate ids. Never silently fill the gap.
4. Emit the mapped output **plus a coverage report**: % of value mapped, count queued, list of
   unresolved labels. Coverage is a deliverable, not an afterthought.
5. Resolved review items get added to `aliases/client_aliases.csv` (the authoritative, version-
   controlled alias list) so the queue trends toward zero on the next pack.

## Don't

- Don't fuzzy-match line items by eye or add a Levenshtein/embedding matcher — failing loud on
  ambiguity is the design, not a gap to fix.
- Don't edit the embedded data inside `lib/hgb_map.py` by hand. It is generated from the source
  workbook; regenerate from there so the Excel and the code stay in sync.
- Don't store learned aliases only in Claude Code auto-memory — keep the authoritative list in
  `aliases/client_aliases.csv` so it's shared, reviewable, and survives.

## Reference

Background and the "why" behind the traps live in the source workbook
(`HGB_GKV_UKV_Standardisation_Map.xlsx`, tab `03_GKV-UKV_Bridge` and `06_Naming_Drift_Log`) and
in `h.DRIFT_LOG`. Paths above assume `lib/`, `data/`, `aliases/`, `reviews/` — adjust if your
layout differs.
