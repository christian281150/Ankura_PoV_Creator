# Profile renderer

Run from the repository root:

```powershell
.venv\Scripts\python.exe py\render\render_profile.py profile.json output\profile.pptx --template render\templates\ankura_master_reference.pptx
```

The input must contain the contract `entity`, `blocks`, and an explicit
four-slot `canonical_layout` (or `slot_assignments`). Every selected block must
have a unit, presentation basis, and provenance containing `std_id`, `doc`, and
`page` (which may be `null`). Blocking flags, unavailable blocks, missing chart
series, duplicate assignments, and Revenue on any basis other than
`umsatzerloese` stop rendering.

The renderer copies the supplied master, edits slide 6 only, and leaves the
hidden think-cell OLE object in place. Financial charts and their displayed
value/year labels are regenerated from the same series; old label shapes are
removed with the old chart. The resulting `.json` companion records the slide,
assignments, rendered provenance, footnotes, and sources.
