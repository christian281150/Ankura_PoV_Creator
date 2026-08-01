# profile-builder-ui

Slot-assignment UI (screen 5) for the Company Profile Builder. Vite + React 18 +
TypeScript + Tailwind. Runnable now against a fixture derived from real
Seidensticker extraction output.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build
npm run typecheck
```

Verified: builds clean, **53 KB gzip JS / 3.8 KB gzip CSS**.

---

## Profile and budgets

`vite-spa` — auth-walled internal tool, desktop/corporate primary, no SEO.
Next.js was rejected: no SEO benefit, and RSC would put a server in the path of
confidential client filings for no gain.

| Gate | Target | Current |
|---|---|---|
| JS bundle, initial | ≤ 200 KB gzip | **53 KB** |
| CSS | ≤ 20 KB gzip | **3.8 KB** |
| LCP p75, desktop LAN | ≤ 2500 ms | n/a — measure after API wiring |
| INP p75 | ≤ 200 ms | n/a |
| CLS | ≤ 0.1 | 0 — no async layout shift by construction |
| Lighthouse a11y | ≥ 95 | run in CI |

Runtime dependencies: `react`, `react-dom`. Nothing else. State is one
`useReducer` — a state library would cost more than it saves for four slots and
five transitions.

---

## Design direction

**Audit workpaper.** The subject is the German commercial register and the
Bundesanzeiger filing: typed, dense, footnoted documents where every figure is
traceable. The UI borrows their vernacular — hairline rules, tabular numerals,
marginalia, 2 px radius ceiling, no shadows, no gradients.

- **Type:** IBM Plex Sans / IBM Plex Mono. Every figure, identifier, and source
  reference is set in mono with `font-variant-numeric: tabular-nums`, because
  figures are meant to be compared column-wise and audited, not skimmed.
- **Colour:** cool paper (`#F7F8F7`), pine (`#0E3B37`, from the Ankura master),
  amber for "incomplete but usable", rust for "blocks export". Three signal
  colours, no decorative palette.
- **Signature — the provenance gutter.** A 3 px strip on the left edge of every
  data card, coloured by source confidence. Auditability is the product, so it
  is a permanent structural element rather than a tooltip. Clicking the source
  count in the card footer expands the filing, sheet, row and `std_id` behind
  the block.

---

## Architecture

```
src/
  types/profile.ts        domain model, mirrors the Python JSON contract
  data/seidensticker.ts   fixture — REPLACE with a fetch in production
  lib/format.ts           EUR/pct/FY formatting; scaling happens here only
  lib/scoring.ts          rank = coverage × confidence; selectability
  state/profileStore.tsx  single reducer + context
  components/
    EntityBar.tsx         entity identity + rejected near-miss entities
    SlotCard.tsx          one slot; radiogroup of eligible blocks
    FlagPanel.tsx         open validation flags; notes become footnotes
    BasisGuard.tsx        rule V1 made interactive
    PreviewPane.tsx       live four-box preview + auto footnotes
    CoverageRail.tsx      coverage by dimension
    ActionBar.tsx         reset / lock / export
    ui/                   Badge, Meter
```

### Invariants encoded in code, not convention

| Invariant | Where |
|---|---|
| Unavailable blocks render greyed **with reason**, never hidden | `eligibleFor` sorts them last; `BlockOption` prints `unavailableReason` |
| Blocks with unresolved blocking flags are listed but not selectable | `isSelectable` |
| Dropdown order is `coverage × confidence` | `rank` |
| Deviation from canonical layout is badged and recorded | `SlotCard` header + `isCanonical` |
| Export is disabled while any flag is unresolved | `exportBlocked` in the store |
| Notes written against flags become slide footnotes | `footnotes` in the store, rendered in `PreviewPane` |
| A series labelled "Revenue" must be Umsatzerlöse | `BasisGuard` + `exportBlocked` |
| Layout lock freezes assignment across data refreshes | reducer short-circuits `assign` |

The last two are the ones that matter. `BasisGuard` exists because the published
POV charted Gesamtleistung under a "Revenue in €m" axis for nine consecutive
years. Switching the basis relabels the headline and the axis, and blocks export.

---

## Wiring to the Python layer

Replace `src/data/seidensticker.ts` with a fetch. The shape is already the
contract:

```ts
// src/lib/api.ts
export async function loadProfile(entityId: string): Promise<ProfileFixture> {
  const res = await fetch(`/api/profiles/${entityId}`);
  if (!res.ok) throw new Error(`profile ${entityId}: ${res.status}`);
  return res.json() as Promise<ProfileFixture>;
}
```

Then in `App.tsx`, wrap `ProfileProvider` in a Suspense boundary and hydrate from
the API. **Do not** add a client-side transform layer: `presentationBasis`,
`coverage`, `confidence`, and `flags` are computed in `validate/` and must not be
recomputed in the browser, or the UI and the export can disagree.

`provenance.page` is `null` throughout the fixture. That is deliberate and
correct — PDF page tracking has to be added upstream in the pdfplumber
extraction. The UI renders `page n/a` in amber so the gap stays visible.

---

## Remaining work for Codex

| # | Task | Acceptance |
|---|---|---|
| F1 | Screens 1–4 and 6–7 (entity search, confirmation, acquisition, flag resolution, export) | Screen 2 cannot be skipped or defaulted |
| F2 | `lib/api.ts` + Suspense boundary; delete the fixture import | No domain transform in the browser |
| F3 | Real chart components for `chart.column_line` and `chart.stacked_column` | Axis label derives from `presentationBasis`, never hardcoded |
| F4 | Keyboard nav across the 2×2 grid (arrow keys between slots) | Tab order matches visual order; roving tabindex within each radiogroup |
| F5 | Persist assignment + notes per entity | `Lock layout` survives a data refresh |
| F6 | Vitest + Testing Library | Cover: export blocked with an open flag; unavailable block not selectable; V1 fires on a Gesamtleistung basis |
| F7 | CI gates | `tsc --noEmit`, bundle budget check, Lighthouse a11y ≥ 95 |

### Do not

- Do not hide unavailable blocks to tidy the dropdown. The absence is information.
- Do not add an "auto-fill best blocks" action. Slot assignment is the analyst's judgment; automating it removes the review step the tool exists to enforce.
- Do not let the preview render a figure the export would refuse.
- Do not introduce a component library. The visual language is deliberately not
  a SaaS dashboard, and shadcn/Radix defaults would pull it there.
