"""Multi-year consolidation: join a company's per-year tables into one grid
per statement type."""

import re
from typing import Optional

from ._core import _canonical_row_key, _parse_num_cell
from .extract import effective_table_type


def build_multi_year_tables(tables: list, row_merges: "Optional[dict]" = None) -> list:
    """
    Synthesise multi-year summary tables from a set of annual financial tables.

    One summary table is returned per statement type (Bilanz=0, GuV=1, KFR=2)
    whenever 2+ tables of the same type are present in *tables*.

    The returned dicts have the same shape as tables from extract_tables_from_pdf
    and can be previewed in the GUI and exported via export_to_excel.

    Year extraction supports multiple column-header formats:
      • "31.12.2024"  (German short date)
      • "31. Dezember 2024" / "31 Dezember 2024"  (written-out month)
      • Any header cell containing exactly one 4-digit year (2000-2099)
    Column 1 (current year) always takes priority over column 2 (prior year)
    when both would map to the same calendar year.

    Non-numeric source values (e.g. "n.a.", "–") are replaced with "" so they
    do not corrupt the consolidated view.
    """

    def _year_from_col_header(text: str) -> Optional[int]:
        """Extract year from a single column header cell — no doc_label fallback.
        Used per-column so that notes tables with non-date headers (e.g.
        'Verbindlichkeiten') are not assigned a year via the doc_label."""
        s = str(text or "")
        m = re.search(r"31\.12\.(\d{4})", s)
        if m:
            return int(m.group(1))
        m = re.search(r"31\.?\s*(?:dezember|december)\s*(\d{4})", s, re.IGNORECASE)
        if m:
            return int(m.group(1))
        years = re.findall(r"\b(20\d{2}|19\d{2})\b", s)
        if len(years) == 1:
            return int(years[0])
        return None

    # Row identity uses the shared module-level normaliser, then applies any
    # user row-merges (member key → kept target key) so two differently-named
    # rows the user declared equivalent collapse onto one consolidated line.
    _merges = row_merges or {}

    def _canonical_key(desc: str) -> str:
        """Row-identity key: the shared canonical normaliser plus any user row-merges."""
        k = _canonical_row_key(desc)
        return _merges.get(k, k)

    def _col_data(trows: list, ci: int) -> dict:
        """Extract {canonical_key: (raw_desc, value)} for one column of a table.

        Skips empty descriptions; the first (most-recent) entry per key wins.
        """
        out: dict = {}
        for row in trows[1:]:
            if not row:
                continue
            desc = str(row[0] or "").strip()
            norm = _canonical_key(desc)
            if norm and ci < len(row):
                if norm not in out:   # first (col-1 / most-recent) entry wins
                    out[norm] = (desc, str(row[ci] or "").strip())
        return out

    def _is_valid_val(v: str) -> bool:
        """True if a cell is a parseable number or an accepted blank/dash placeholder."""
        v = v.strip()
        if not v or v in ("-", "—", "–"):
            return True
        return _parse_num_cell(v, thousand_sep=".", decimal_sep=",") is not None

    # Exclude synthetic multi-year tables and any table the user has explicitly
    # removed from the overview (_include_in_overview is False). The latter is
    # what makes the consolidation user-adjustable: deselect a table and it no
    # longer feeds the merge.
    source = [t for t in tables
              if not t.get("multi_year")
              and t.get("_include_in_overview", True) is not False]
    groups: dict = {}
    for t in source:
        tp = effective_table_type(t)
        if tp != 99:
            groups.setdefault(tp, []).append(t)

    _NAMES = {0: "Bilanz", 1: "GuV", 2: "Kapitalflussrechnung"}
    _NOTES_RE = re.compile(r'\b(angaben|erläuterung|anmerkung)\b', re.I)
    result = []

    for tp, tlist in sorted(groups.items()):
        if len(tlist) < 2:
            continue
        type_name = _NAMES.get(tp, f"Type{tp}")

        year_data: dict = {}        # yr -> {row_key: (desc, value)}
        year_prio: dict = {}        # yr -> {row_key: prio}  (lower = more authoritative)
        table_for_year: dict = {}

        def _merge_year_col(yr: int, col: dict, prio: int, t_idx: int):
            """Union one table-column's rows into year *yr*, so a balance sheet
            split across two tables (Aktiva on one, Passiva on another) joins
            into a single year column instead of one overwriting the other.
            On a genuine duplicate row, the more authoritative source (lower
            prio: current-year date column > prior-year column > doc_label
            fallback) wins."""
            yd = year_data.setdefault(yr, {})
            yp = year_prio.setdefault(yr, {})
            for key, val in col.items():
                if key not in yd or prio < yp[key]:
                    yd[key] = val
                    yp[key] = prio
            table_for_year.setdefault(yr, t_idx)

        for t_idx, t in enumerate(tlist):
            trows = t.get("rows") or []
            if not trows:
                continue
            lbl = t.get("doc_label", "")
            # The date columns are usually in row 0, but section-titled balance
            # sheets put a heading there (e.g. ['Aktiva','','']) and the dates on
            # the next row. Scan the first few rows for the one carrying years.
            header = trows[0]
            for hrow in trows[:3]:
                if any(_year_from_col_header(str(c or "")) is not None
                       for c in hrow[1:3]):
                    header = hrow
                    break
            got_year = False
            for ci in range(1, min(len(header), 3)):
                yr = _year_from_col_header(str(header[ci] or ""))
                if yr is None:
                    continue
                got_year = True
                _merge_year_col(yr, _col_data(trows, ci),
                                prio=(0 if ci == 1 else 1), t_idx=t_idx)
            # Fallback: if no column had a date header, use doc_label for ci=1 only
            # (handles single-column tables; skips notes tables with non-date headers).
            # NB: no leading \b — a year glued to letters like "FY2017" must match.
            if not got_year and len(header) > 1:
                m_lbl = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", lbl)
                if m_lbl:
                    yr = int(m_lbl.group())
                    _merge_year_col(yr, _col_data(trows, 1), prio=2, t_idx=t_idx)

        if len(year_data) < 2:
            continue

        years = sorted(year_data.keys(), reverse=True)

        # For row-label ordering, prefer the main statement over notes/Angaben tables.
        main_idxs = [i for i, t_ in enumerate(tlist)
                     if not _NOTES_RE.search(t_.get("heading") or "")]
        candidates = main_idxs if main_idxs else list(range(len(tlist)))
        # Among candidates, prefer the one covering the most recent year
        recent_idx = table_for_year.get(years[0])
        best_idx = recent_idx if (recent_idx in candidates) else candidates[0]

        # Row ordering = full outer-join union of every contributing table.
        # Seed the order from the "best" (main, most-recent) statement so the
        # primary statement drives the layout, then append any label that only
        # appears in another year's table — never silently drop a row that one
        # filing reports and another doesn't.
        mr_rows = tlist[min(best_idx, len(tlist) - 1)].get("rows") or []
        ordered: list = []
        pos: dict = {}        # eff_key -> index in ordered
        genuine: set = set()  # eff_keys whose display label came from the kept (target) row

        def _consider(desc: str):
            """Register a row label, honouring row-merges. Position is fixed by
            first appearance, but the *display* label prefers the kept target row
            (base==eff) so a user-chosen merge name wins over a member's name."""
            desc = str(desc or "").strip()
            if not desc:
                return
            base = _canonical_row_key(desc)
            eff = _merges.get(base, base)
            if not eff:
                return
            is_target = (base == eff)
            if eff not in pos:
                pos[eff] = len(ordered)
                ordered.append([eff, desc])
                if is_target:
                    genuine.add(eff)
            elif is_target and eff not in genuine:
                # The kept target row showed up after a member — adopt its label.
                ordered[pos[eff]][1] = desc
                genuine.add(eff)

        for row in mr_rows[1:]:
            if row:
                _consider(row[0])

        # Union-in labels unique to other years (most-recent year first).
        # year_data[yr] preserves each table's own row order via _col_data.
        for yr in years:
            for _eff, (raw_desc, _val) in year_data.get(yr, {}).items():
                _consider(raw_desc)

        ordered = [(k, d) for k, d in ordered]

        if not ordered:
            continue

        header_row = ["Description"] + [str(y) for y in years]
        data_rows: list = []
        source_label_rows: list = []  # parallel to data_rows: [{yr: raw_label_str}, ...]
        for norm, raw_desc in ordered:
            row_vals = [raw_desc]
            labels_by_yr: dict = {}
            for yr in years:
                entry = year_data.get(yr, {}).get(norm)
                if entry:
                    val = entry[1]
                    labels_by_yr[yr] = entry[0]   # raw source label used in that year's table
                    row_vals.append(val if _is_valid_val(val) else "")
                else:
                    labels_by_yr[yr] = ""
                    row_vals.append("")
            data_rows.append(row_vals)
            source_label_rows.append(labels_by_yr)

        result.append({
            "index":             -(tp + 1),
            "heading":           f"ALL — {type_name}",
            "doc_label":         "",
            "type":              tp,
            "multi_year":        True,
            "years":             years,
            "page_start":        0,
            "page_end":          0,
            "row_count":         len(data_rows),
            "rows":              [header_row] + data_rows,
            "row_source_labels": source_label_rows,
        })

    return result
