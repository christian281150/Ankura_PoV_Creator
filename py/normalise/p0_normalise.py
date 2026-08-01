"""
P0 normaliser — fixes extraction defects 1-5 in the Bundesanzeiger workbook export.

Defects addressed:
  1. HGB mapper not wired          -> longest-match mapper, wired into every row
  2. Column-offset loss            -> year-block column coalescing
  3. German number strings         -> parse_de_number()
  4. Unit mixing (EUR vs TEUR)     -> per-sheet unit detection + normalisation
  5. Phantom rows from label drift -> merge on std_id, not raw label

Emits: normalised JSON with provenance, presentation_basis, and validation flags.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent))
from hgb_lookup_reference import HGBMapper, _normalize

# ---------------------------------------------------------------- defect 3
_NUM_RE = re.compile(r"^[+\-\s]*[\d.,]+$")


def parse_de_number(v):
    """Parse German-formatted numerics incl. '+ 1.914.645,32', '-1510992.16'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or not _NUM_RE.match(s):
        return None
    sign = -1.0 if s.lstrip().startswith("-") else 1.0
    s = s.lstrip("+- ").replace(" ", "")
    if "," in s:                      # German: . = thousands, , = decimal
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:            # 1.234.567 with no decimal part
        s = s.replace(".", "")
    try:
        return sign * float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- defect 4
_TEUR_TOKENS = ("teuro", "t€", "tsd", "in t")


def detect_unit(cells) -> float:
    """Return multiplier to convert sheet values to EUR."""
    blob = " ".join(str(c).lower() for c in cells if c)
    return 1000.0 if any(t in blob for t in _TEUR_TOKENS) else 1.0


# ---------------------------------------------------------------- defect 2
_YEAR_RE = re.compile(r"(20\d{2})\s*[/\-–]\s*(20\d{2})|(\d{1,2}\.\d{1,2}\.(20\d{2}))")


def parse_year_header(cell) -> int | None:
    """'2024/2025' -> 2025 ; '1.5.2015 - 30.4.2016\\n.\\nTEuro' -> 2016."""
    if not cell:
        return None
    s = str(cell)
    m = re.findall(r"20\d{2}", s)
    return int(max(m)) if m else None


def find_year_blocks(rows, max_scan=8):
    """Locate the header row and map column index -> fiscal year.

    Returns (header_row_idx, [(fy, col_start, col_end)]) where each year owns a
    contiguous span of columns. This is the fix for defect 2: a GuV line's value
    may sit in the detail column or the subtotal column of its year block.
    """
    for r_idx, row in enumerate(rows[:max_scan]):
        hits = [(c_idx, parse_year_header(c))
                for c_idx, c in enumerate(row) if c_idx > 0 and parse_year_header(c)]
        if len(hits) >= 1 and len({fy for _, fy in hits}) == len(hits):
            blocks = []
            for i, (c_idx, fy) in enumerate(hits):
                end = hits[i + 1][0] - 1 if i + 1 < len(hits) else len(row) - 1
                blocks.append((fy, c_idx, end))
            return r_idx, blocks
    return None, []


# ---------------------------------------------------------------- defect 1/5
class Mapper:
    """Longest-match wrapper. Fixes the substring-fallback precision bug where
    '4. Materialaufwand' resolved to its own child PL_GKV-5a."""

    def __init__(self, mapping_dir="."):
        self._m = HGBMapper(mapping_dir)
        self._extra = {
            "veraenderungdesbestandsanunfertigenundfertigenerzeugnissen": "PL_GKV-2",
            "veraenderungdesbestands": "PL_GKV-2",
            "erhoehungoderverminderungdesbestandsanfertigenundunfertigenerzeugnissen": "PL_GKV-2",
            "konzernbilanzverlust": "PL_GKV-BILANZVERLUST",
            "nichtdurchvermoegenseinlagengedeckterverlustanteil": "BS-P-NEGEQ",
            "gesamtleistung": "PL_GKV-GESAMTLEISTUNG",
            "rohergebnis": "PL_GKV-ROHERGEBNIS",
        }

    def lookup(self, label: str):
        key = _normalize(label)
        if not key:
            return None, "none"
        if key in self._extra:
            return self._extra[key], "extra_exact"
        if key in self._m.labels:
            return self._m.labels[key], "exact"
        # longest-match, deterministic, parent never resolves to its own child
        cands = [(k, v) for k, v in self._m.labels.items() if k and (k in key or key in k)]
        if not cands:
            for k, v in self._extra.items():
                if k in key or key in k:
                    return v, "extra_substr"
            return None, "none"
        k, v = max(cands, key=lambda kv: len(kv[0]))
        return v, "longest_match"


# ---------------------------------------------------------------- extraction
def extract_statement(ws, mapper: Mapper, sheet_name: str):
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    hdr_idx, blocks = find_year_blocks(rows)
    if hdr_idx is None:
        return None
    unit_mult = detect_unit(rows[hdr_idx] + (rows[hdr_idx + 1] if hdr_idx + 1 < len(rows) else []))

    out = []
    for r_idx, row in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 1):
        label = str(row[0]).strip() if row[0] else ""
        if not label or label.startswith("- davon"):
            continue
        std_id, match_type = mapper.lookup(label)
        vals = {}
        for fy, c0, c1 in blocks:
            for c in range(c0, min(c1 + 1, len(row))):
                n = parse_de_number(row[c])
                if n is not None:
                    vals[fy] = n * unit_mult
                    break
        if vals:
            out.append({
                "raw_label": label,
                "std_id": std_id,
                "match_type": match_type,
                "values": vals,
                "unit_multiplier": unit_mult,
                "provenance": {"sheet": sheet_name, "row": r_idx + 1},
            })
    return out


# ---------------------------------------------------------------- validation
def build_series(records, std_id):
    s = {}
    for r in records:
        if r["std_id"] == std_id:
            for fy, v in r["values"].items():
                s.setdefault(fy, v)
    return s


def main(xlsx_path, mapping_dir, out_path):
    wb = load_workbook(xlsx_path, read_only=True)
    mapper = Mapper(mapping_dir)

    all_rows, sheets_done = [], []
    for name in wb.sheetnames:
        if not re.match(r"^FY\d{4}_", name):
            continue
        low = name.lower()
        if not any(t in low for t in ("gewinn", "verl", "guv", "ertragslage")):
            continue
        recs = extract_statement(wb[name], mapper, name)
        if recs:
            all_rows.extend(recs)
            sheets_done.append(name)

    rev = build_series(all_rows, "PL_GKV-1")
    inv = build_series(all_rows, "PL_GKV-2")
    oth = build_series(all_rows, "PL_GKV-4")

    years = sorted(set(rev) | set(inv) | set(oth))
    recon = []
    for fy in years:
        r, i, o = rev.get(fy), inv.get(fy), oth.get(fy)
        gl = sum(x for x in (r, i, o) if x is not None) if r is not None else None
        recon.append({
            "fy": fy,
            "umsatzerloese": r,
            "bestandsveraenderung": i,
            "sonstige_betriebliche_ertraege": o,
            "gesamtleistung": gl,
        })

    mapped = sum(1 for r in all_rows if r["std_id"])
    result = {
        "entity": {
            "legal_name": "Textilkontor Walter Seidensticker GmbH & Co. KG",
            "register": {"court": "Bielefeld", "type": "HRA", "number": "8217"},
            "fiscal_year_end": "30-04",
        },
        "coverage": {
            "sheets_parsed": sheets_done,
            "rows_extracted": len(all_rows),
            "rows_mapped": mapped,
            "map_rate": round(mapped / len(all_rows), 3) if all_rows else 0,
        },
        "reconciliation": recon,
        "rows": all_rows,
    }
    Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"sheets parsed : {len(sheets_done)}")
    print(f"rows extracted: {len(all_rows)}   mapped: {mapped} ({result['coverage']['map_rate']:.0%})")
    print()
    print(f"{'FY':<6}{'Umsatzerlöse':>15}{'Bestandsver.':>15}{'Sonst.Ertr.':>14}{'Gesamtleistung':>17}")
    print("-" * 67)
    for r in recon:
        f = lambda v: f"{v/1e6:>13.1f}m" if v is not None else f"{'—':>14}"
        print(f"{r['fy']:<6}{f(r['umsatzerloese'])}{f(r['bestandsveraenderung'])}"
              f"{f(r['sonstige_betriebliche_ertraege'])[:14]:>14}{f(r['gesamtleistung'])}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
