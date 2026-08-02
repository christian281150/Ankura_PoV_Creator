# Final push — lane plan

| | |
|---|---|
| **Status** | ACTIVE — operational plan, not architecture |
| **Verified against** | `main` after the `w0/deprecate-p0normalise` merge |
| **Expected suite** | `114 passed, 1 xfailed` — verify before trusting anything below |
| **Expires** | On completion of Wave 2, or when any lane below is resolved differently |
| **Supersedes** | The version written before Wave 0. That one is wrong about Lane B, Lane G, and two diagnoses that were later disproven |

> Dated operational plan, not a durable spec. If the suite count above does not
> match your `pytest -q`, re-verify before acting. Delete this file and its
> `AGENTS.md` pointer when Wave 2 lands.

---

## Wave 0 — complete

| # | Item | Landed |
|---|---|---|
| W0.1 | Mapper split resolved. Five wrong mappings deleted; `PL_GKV-7b` ported; `p0_normalise` deprecated and deleted | `e033262`, `w0/deprecate-p0normalise` |
| W0.2 | `py/render/qa/` removed — 35 MB, zero code references, `out.json` lineage | `ddc94e6` |
| W0.3 | `AGENTS.md` §P0 and spec §5 corrected; §P0.6 inverted; double-encoded UTF-8 repaired | `8377aa7` |
| W0.4 | CI gate + branch protection. **Enforcement proven by probe** — a direct push as admin was rejected `GH013` | `0cc87af` |
| W0.6 | Queue becomes a per-run log; tracked `refusal_register.csv` with enforcement test | `380aac1` |
| W0.8 | `.gitattributes`, LF pinned | `9628cf4` |
| W0.9 | `requirements.lock`, CI installs from it | `db23885` |
| W0.5 | Contract freeze: V11 relative+floor, V12 fail-closed, per-year Path B metadata | `dfa6418` |

**`contract/` is frozen.** A lane that believes it needs a change there stops and
reports. It does not edit and it does not raise a PR.

Open, non-blocking: **W0.7** artifact `_meta` provenance · **W0.10** the hardcoded
coverage figures in `ui/src/data/seidensticker.ts`.

---

## Two diagnoses that were wrong, recorded so nobody re-derives them

1. **"The runtime and build-side normalisers diverge on `[A-Z].` prefixes."** They
   do not. Probed on ten cases including every predicted mismatch: identical output.
2. **"The taxonomy lacks the balance-sheet positions the filing uses."** It does not.
   59 BS rows exist and `_hgb.lookup` resolves `C. Rechnungsabgrenzungsposten`,
   `Kassenbestand…`, and `Forderungen gegen Gesellschafter` to one candidate each.

Both were inferred from reading code and stale data rather than executing it. The
99-row "taxonomy backlog" that prompted them came from an append-only queue spanning
code states going back to before the mapper was wired — the same artifact class as
`out.json`. It has been deleted.

**The real coverage picture, from one run of current code on the FY2024 fixture:**
P&L good · Bilanz partial (KG equity missing) · **Kapitalflussrechnung absent
entirely** — 35 rows, zero resolve, no CF statement in the taxonomy at all.

---

## Rule coverage — the reframe

Three of nine blocking rules currently have nothing to check:

| Rule | Blocked by | Lane |
|---|---|---|
| V8 Aktiva = Passiva | Bilanz partially unmapped | G1 |
| V9 Negative equity | `Nicht durch Vermögenseinlagen gedeckte Verlustanteile` unmapped | G1 |
| V10 Subtotal tie-out | Rows discarded before the mapper | A |

The spec calls validation "the actual product." A third of it is inert. That is the
argument for lane priority, not label counts.

---

## Lanes

Ownership is disjoint. `contract/` is frozen.

| Lane | Branch | Owns | Witness |
|---|---|---|---|
| **A** | `lane/consolidate` | `extractor/consolidate.py`, its test | **V10 fires clean on the FY2024 fixture** once `if not label: continue` (~line 220) is removed. Rule already written at `validator.py:392` |
| **G1** | `lane/kg-equity` | `hgb_taxonomy.csv`, extractor aliases | **V9 fires on the FY2024 Konzernbilanz.** Six KG-equity positions; taxonomy models GmbH equity, fixture is a GmbH & Co. KG |
| **G2** | `lane/cashflow-taxonomy` | `hgb_taxonomy.csv` (CF section) | A CF statement type exists and the FY2024 Kapitalflussrechnung resolves. ~35 rows, currently zero |
| **C** | `lane/series` | **new** `py/series/` | FY2024 is stated in both the FY2024 and FY2025 filings — reconcile to the cent or raise a restatement flag. Assert on `std_id`, **never row index** |
| **D** | `lane/pathb` | `PathB_Input_Template.xlsx`, `py/acquire/pathb/` | Round-trip: Path A canonical → template → producer → identical `EntitySeries` |
| **F** | `lane/exporters` | `extractor/exporters.py` | `Umsatzerlöse` non-empty for every year in `ALL-GuV`. This is the **human review surface** — where an analyst checks the mapper — and revenue is currently blank on it |

**Lane B is spent.** V11 and V12 both landed in Wave 0.

**G1 and G2 both own `hgb_taxonomy.csv` — they cannot run in parallel.** G1 first: six
rows, unblocks two rules. G2 is a whole statement and can follow.

Merge order: `A → G1 → C → G2 → D → F`

---

## Before the fork — one defect worth fixing first

**26 of 90 queued rows are not HGB statements.** Segment tables (`Hemden`, `Blusen`,
`Lizenzerlöse`) and Lagebericht tables (`3.2 Vermögenslage`, `3.3 Finanzlage`) are
being handed to the HGB mapper and refused. `segments.py` owns the first; the second
is narrative.

So the queue **over-reports failure by roughly a third** while **under-reporting it by
the discarded subtotals**. Every lane is about to measure coverage against it. Fix
before the fork: `_column_actuals` should skip tables whose `effective_table_type` is
not an HGB statement.

---

## Standing rules — prepend to every agent prompt

```
1. Python is E:\Github\Ankura_PoV_Creator\.venv\Scripts\python.exe (absolute path).
   Your worktree has no venv. No network; do not pip install.
2. Read AGENTS.md first. It was corrected in Wave 0. Where it disagrees with an
   older doc, AGENTS.md wins.
3. You own ONLY the files listed. contract/ is FROZEN. If your task seems to need
   a change outside your set, STOP and report.
4. Never weaken, skip, or xfail an assertion to make a suite pass.
5. Write files BOM-free, absolute path, via [System.IO.File]::WriteAllText.
   PowerShell has no heredoc: @'...'@ literal, @"..."@ interpolating.
   pwsh is not installed; use powershell.
6. Quote any CSV field containing a comma. Ensure a trailing newline before
   appending.
7. NEVER commit to main; it is protected and a direct push is rejected.
8. Do not `git add .` or `git add -A`. Name every path. A broad add swept a stray
   file and silently reverted a landed fix.
9. IF A COMMAND FAILS: retry it once and report the actual error verbatim. Do NOT
   diagnose a repository-level or environment-level cause you have not reproduced,
   and do NOT change the command to work around it. Two agents in Wave 0 reported
   a "pre-existing" temp-directory defect that did not exist in three controls.
   The work was correct; the narration was false, and false narration is what
   reaches commit messages and handoffs.

COMPLETION PROTOCOL - a claim without all three is void.
  a. python -m pytest -q  -> final 5 lines VERBATIM
  b. git status --short   -> VERBATIM
  c. git diff --stat      -> VERBATIM
Paste them. Do not summarise. If you did not run them, say so.
```

---

## Open decisions

- **V12 note scope.** V12 flags per child, per year. A nine-year series with neither
  child confirmed produces 18 blocking flags and 18 footnotes. If unworkable at the
  first real render, the fix is note *scope* — one confirmation per child per filing —
  **not** loosening severity.
- **KG equity taxonomy rows** need proposing upstream, not hand-editing:
  `hgb_taxonomy.csv` is generated. Confirm the generation source exists before G1.
- **Associates** — four labels, one missing concept. Taxonomy proposal, currently
  `refuse`/`defer` in the register.
- **Minority interest** and **Gewinnrücklagen appropriation flows** — AGENTS.md
  backlog item 4, still open.
