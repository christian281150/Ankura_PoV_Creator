"""Local persistence: table overrides, row-merges, feedback bundles, and the
per-company library (save/restore + index)."""

import hashlib
import threading
from pathlib import Path
from typing import Optional

from ._core import _TYPE_INT_MAP, _TYPE_LABEL, _canonical_row_key, PROJECT_ROOT

# Anchor on the repo root (one level above this package) so the data/ paths
# resolve exactly as they did when this lived in ur_extractor.py at the root.
_ROW_MERGES_PATH = PROJECT_ROOT / "data" / "row_merges.csv"
_ROW_MERGES_COLS = ["company_normalized", "member_key", "target_key",
                    "display_label", "timestamp", "note"]


def load_row_merges(company_normalized: str = "",
                    path: "Optional[Path]" = None) -> dict:
    """Return {member_canonical_key: target_canonical_key} for a company.

    A merge collapses a differently-named row (member) into a kept row (target)
    so they share one consolidated line across years.
    """
    import csv as _csv
    p = Path(path) if path else _ROW_MERGES_PATH
    out: dict = {}
    if not p.exists():
        return out
    try:
        with open(p, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                if company_normalized and row.get("company_normalized", "") != company_normalized:
                    continue
                member = row.get("member_key", "")
                target = row.get("target_key", "")
                if member and target:
                    out[member] = target
    except Exception:
        pass
    # Collapse transitive chains (a→b, b→c  ⇒  a→c) so grouping is stable.
    def _resolve(k, _seen=None):
        """Follow a merge chain (a→b→c) to its final target, guarding against cycles."""
        _seen = _seen or set()
        while k in out and out[k] != k and out[k] not in _seen:
            _seen.add(k)
            k = out[k]
        return k
    return {m: _resolve(t) for m, t in out.items()}


def save_row_merge(company_normalized: str, member_label: str,
                   target_label: str, display_label: str = "",
                   note: str = "merged_via_gui",
                   path: "Optional[Path]" = None) -> bool:
    """Persist one row-merge (member → target) keyed by canonical row keys."""
    import csv as _csv, datetime as _dt
    p = Path(path) if path else _ROW_MERGES_PATH
    member_key = _canonical_row_key(member_label)
    target_key = _canonical_row_key(target_label)
    if not member_key or not target_key or member_key == target_key:
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        write_header = not p.exists()
        with open(p, "a", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=_ROW_MERGES_COLS, extrasaction="ignore")
            if write_header:
                w.writeheader()
            w.writerow({
                "company_normalized": company_normalized,
                "member_key":         member_key,
                "target_key":         target_key,
                "display_label":      display_label or target_label,
                "timestamp":          _dt.datetime.now().isoformat(timespec="seconds"),
                "note":               note,
            })
        return True
    except Exception:
        return False


def clear_row_merges(company_normalized: str, label: str = "",
                     path: "Optional[Path]" = None) -> bool:
    """Remove row-merge rows for a company.

    With no *label*, clears all merges for the company. With a *label*, removes
    every merge in which that row participates — whether it was the member or
    the kept target — so unmerging the kept row dissolves the whole group.
    Returns True only if at least one row was removed (or label-less clear ran).
    """
    import csv as _csv
    p = Path(path) if path else _ROW_MERGES_PATH
    if not p.exists():
        return False
    key = _canonical_row_key(label) if label else ""
    try:
        with open(p, newline="", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        kept = [r for r in rows
                if not (r.get("company_normalized", "") == company_normalized
                        and (not key
                             or r.get("member_key", "") == key
                             or r.get("target_key", "") == key))]
        if len(kept) == len(rows):
            return False
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=_ROW_MERGES_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(kept)
        return True
    except Exception:
        return False
_OVERRIDES_PATH = PROJECT_ROOT / "data" / "table_overrides.csv"
_OVERRIDES_COLS = [
    "company_normalized", "filing_id", "table_heading_normalized",
    "override_type", "override_include_in_overview", "timestamp", "note",
]


def _normalize_for_override_key(text: str, max_len: int = 80) -> str:
    """Normalise a company/heading string into a stable, filesystem-safe key
    (lowercase, drop punctuation except umlauts, spaces → underscores).
    """
    import re
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9äöüß\s]", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:max_len]


def override_filing_id(t: dict) -> str:
    """Stable per-filing component of a table-override key.

    Both the save path (GUI) and the apply path (apply_table_overrides) MUST
    derive this identically or overrides will never re-match on re-extraction.
    """
    return _normalize_for_override_key(
        f"{t.get('doc_type','')}_{t.get('doc_label','')}")


def make_override_record(t: dict, company_normalized: str,
                         type_label: str, include_in_overview: bool,
                         note: str = "user_override") -> dict:
    """Build a table_overrides.csv record for table *t* using the canonical key."""
    import datetime as _dt
    return {
        "company_normalized":           company_normalized,
        "filing_id":                    override_filing_id(t),
        "table_heading_normalized":     _normalize_for_override_key(t.get("heading") or ""),
        "override_type":                type_label,
        "override_include_in_overview": str(bool(include_in_overview)).lower(),
        "timestamp":                    _dt.datetime.now().isoformat(timespec="seconds"),
        "note":                         note,
    }


def load_table_overrides(path: "Optional[Path]" = None) -> dict:
    """Load table_overrides.csv into a lookup dict keyed by (co_norm, filing_id, heading_norm)."""
    import csv as _csv
    p = Path(path) if path else _OVERRIDES_PATH
    result: dict = {}
    if not p.exists():
        return result
    try:
        with open(p, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                key = (
                    row.get("company_normalized", ""),
                    row.get("filing_id", ""),
                    row.get("table_heading_normalized", ""),
                )
                result[key] = row
    except Exception:
        pass
    return result


def save_table_override(record: dict, path: "Optional[Path]" = None) -> bool:
    """Append one override record to table_overrides.csv. Returns True on success."""
    import csv as _csv, datetime as _dt
    p = Path(path) if path else _OVERRIDES_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        write_header = not p.exists()
        with open(p, "a", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=_OVERRIDES_COLS, extrasaction="ignore")
            if write_header:
                w.writeheader()
            w.writerow({
                "company_normalized":        record.get("company_normalized", ""),
                "filing_id":                 record.get("filing_id", ""),
                "table_heading_normalized":  record.get("table_heading_normalized", ""),
                "override_type":             record.get("override_type", "Other"),
                "override_include_in_overview": str(record.get("override_include_in_overview", True)).lower(),
                "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
                "note":      record.get("note", "user_override"),
            })
        return True
    except Exception:
        return False


def apply_table_overrides(tables: list, company_normalized: str,
                           overrides: dict) -> list:
    """
    Apply overrides from load_table_overrides() to a list of table records.
    Mutates t["type"] and t["_override_applied"] in-place.
    Returns the same list (for chaining).
    """
    if not overrides:
        return tables
    for t in tables:
        if t.get("multi_year"):
            continue
        filing_id  = override_filing_id(t)
        heading_n  = _normalize_for_override_key(t.get("heading") or "")
        key        = (company_normalized, filing_id, heading_n)
        override   = overrides.get(key)
        if override:
            new_type = _TYPE_INT_MAP.get(override.get("override_type", ""), None)
            if new_type is not None:
                old_type = t.get("type", 99)
                t["type"] = new_type
                t["_override_applied"] = True
                t["_override_old_type"] = old_type
                print(f"[override] {t.get('heading','')} → {_TYPE_LABEL.get(new_type,'?')}"
                      f" (was {_TYPE_LABEL.get(old_type,'?')})")
            # Include/exclude round-trips independently of any type change, so a
            # pure 'remove from overview' correction survives re-extraction.
            include = str(override.get("override_include_in_overview", "true")).lower()
            t["_include_in_overview"] = (include != "false")
    return tables


def write_feedback_bundle(table: dict, source_pdf_path,
                           override_info: dict,
                           feedback_dir: "Optional[Path]" = None) -> "tuple[bool, Path]":
    """
    Write a feedback bundle for a table reclassification event.
    Contents: MANIFEST.json, original_table.json, original_table.csv,
              source_excerpt.pdf (page-range ±1; falls back to path reference if pypdf unavailable).
    Returns (success, bundle_dir).  Never raises — caller must handle failure gracefully.
    """
    import json as _json, csv as _csv, datetime as _dt
    _fbdir = Path(feedback_dir) if feedback_dir else (
        Path.home() / "Downloads" / "UR_Extracts" / "feedback" / "resegmentations")
    try:
        ts          = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        co_id       = override_info.get("company_normalized", "unknown")[:20]
        bundle_dir  = _fbdir / f"{ts}_{co_id}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # ── MANIFEST ──────────────────────────────────────────────────────
        manifest = {
            "version":   "1.0",
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "company":            override_info.get("company", ""),
            "company_normalized": co_id,
            "filing_id":          override_info.get("filing_id", ""),
            "table_heading":      table.get("heading", ""),
            "table_heading_normalized": override_info.get("table_heading_normalized", ""),
            "old_type":  override_info.get("old_type_label", ""),
            "new_type":  override_info.get("override_type", ""),
            "include_in_overview": override_info.get("override_include_in_overview", True),
            "source_pdf_path": str(source_pdf_path) if source_pdf_path else "",
            "page_start":      table.get("page_start", ""),
            "page_end":        table.get("page_end", ""),
            "row_count":       len(table.get("rows", [])),
            "excerpt_written": False,
            "note":            override_info.get("note", "user_override"),
        }

        # ── original_table.json ───────────────────────────────────────────
        (bundle_dir / "original_table.json").write_text(
            _json.dumps({"heading": table.get("heading"),
                         "rows": table.get("rows", [])},
                        ensure_ascii=False, indent=2),
            encoding="utf-8")

        # ── original_table.csv ────────────────────────────────────────────
        rows = table.get("rows", [])
        with open(bundle_dir / "original_table.csv", "w",
                  newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            for row in rows:
                w.writerow(row)

        # ── source_excerpt.pdf ────────────────────────────────────────────
        pdf_path = Path(source_pdf_path) if source_pdf_path else None
        if pdf_path and pdf_path.exists():
            try:
                ps   = max(0, int(table.get("page_start", 1)) - 2)
                pe   = int(table.get("page_end",   ps + 1)) + 1
                try:
                    from pypdf import PdfWriter, PdfReader as _PR
                except ImportError:
                    try:
                        from PyPDF2 import PdfWriter, PdfReader as _PR  # type: ignore
                    except ImportError:
                        PdfWriter = _PR = None  # type: ignore
                if PdfWriter and _PR:
                    reader = _PR(str(pdf_path))
                    writer = PdfWriter()
                    for pi in range(ps, min(pe, len(reader.pages))):
                        writer.add_page(reader.pages[pi])
                    with open(bundle_dir / "source_excerpt.pdf", "wb") as f:
                        writer.write(f)
                    manifest["excerpt_written"] = True
                else:
                    manifest["excerpt_fallback"] = "pypdf/PyPDF2 not installed; see source_pdf_path in MANIFEST"
            except Exception as _exc:
                manifest["excerpt_error"] = str(_exc)

        (bundle_dir / "MANIFEST.json").write_text(
            _json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return True, bundle_dir

    except Exception:
        return False, Path(_fbdir)


def _app_base_dir() -> Path:
    """Folder the app 'lives' in: the executable's folder when frozen
    (PyInstaller exe), else the source directory."""
    import sys as _sys
    if getattr(_sys, "frozen", False):
        return Path(_sys.executable).resolve().parent
    return PROJECT_ROOT


def library_dir() -> Path:
    """The library folder, created on demand, next to the exe/source."""
    d = _app_base_dir() / "library"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d
_LIBRARY_SKIP_NAMES = {"", "(searching…)", "(searching...)", "(unnamed)"}
_LIBRARY_INDEX_NAME = "index.json"
_LIBRARY_INDEX_LOCK = threading.Lock()


def _library_filename(name: str) -> str:
    """Library filename for a company name.

    A short hash of the *full* name disambiguates distinct companies that
    normalise to the same key (e.g. same name in two cities), so one never
    silently overwrites another's snapshot. The same name always maps to the
    same file, so re-doing a company updates its entry in place.
    """
    safe = _normalize_for_override_key(name or "company", max_len=50) or "company"
    digest = hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:8]
    return f"{safe}__{digest}.json"


def _company_library_target(company: dict, lib_dir: "Optional[Path]" = None):
    """Return (path, name) for a saveable company, or None if it should be
    skipped (no/placeholder name)."""
    name = (company.get("name") or "").strip()
    if not name or name.lower() in _LIBRARY_SKIP_NAMES:
        return None
    d = Path(lib_dir) if lib_dir else library_dir()
    return d / _library_filename(name), name


def prepare_library_save(company: dict, lib_dir: "Optional[Path]" = None):
    """Snapshot a company for an off-thread write.

    Returns (path, json_text, index_meta) or None to skip. MUST be called on the
    thread that owns *company*: it reads the live dict here (one consistent
    json.dumps) so the returned text can be written safely from any thread.
    """
    import json as _json, datetime as _dt
    target = _company_library_target(company, lib_dir)
    if target is None:
        return None
    path, name = target
    saved_at = _dt.datetime.now().isoformat(timespec="seconds")
    payload = {"schema": 1, "saved_at": saved_at, "name": name, "company": company}
    try:
        text = _json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        return None
    meta = {
        "name":      name,
        "saved_at":  saved_at,
        "n_filings": len(company.get("doc_sections") or []),
        "n_tables":  len([t for t in (company.get("all_tables") or [])
                          if not t.get("multi_year")]),
    }
    return path, text, meta


def write_library_file(path, text: str, meta: "Optional[dict]" = None) -> bool:
    """Write a prepared payload atomically and refresh the index entry. Safe to
    call off the UI thread (operates only on the snapshot string). Never raises."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        tmp.replace(path)
        if meta is not None:
            _update_library_index(path.parent, path.name, meta)
        return True
    except Exception:
        return False


def save_company_to_library(company: dict, lib_dir: "Optional[Path]" = None) -> "Optional[Path]":
    """Synchronous save (used by tests / non-GUI callers). Returns path or None."""
    prep = prepare_library_save(company, lib_dir)
    if prep is None:
        return None
    path, text, meta = prep
    return path if write_library_file(path, text, meta) else None


def _library_index_path(d: Path) -> Path:
    """Path of the lightweight library index file inside a library directory."""
    return Path(d) / _LIBRARY_INDEX_NAME


def _load_library_index(d: Path) -> dict:
    """Load library/index.json ({filename: meta}); empty dict if absent/corrupt."""
    import json as _json
    p = _library_index_path(d)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            idx = _json.load(f)
        return idx if isinstance(idx, dict) else {}
    except Exception:
        return {}


def _write_library_index(d: Path, idx: dict) -> None:
    """Atomically write the library index. Best-effort (never raises)."""
    import json as _json
    p = _library_index_path(d)
    try:
        tmp = p.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(idx, f, ensure_ascii=False)
        tmp.replace(p)
    except Exception:
        pass


def _update_library_index(d: Path, filename: str, meta: dict) -> None:
    """Insert/replace one file's index entry under the index lock."""
    with _LIBRARY_INDEX_LOCK:
        idx = _load_library_index(d)
        idx[filename] = meta
        _write_library_index(d, idx)


def _scan_library_file(p: Path) -> "Optional[dict]":
    """Parse one snapshot to (re)build its index meta. Used only as a fallback."""
    import json as _json
    try:
        with open(p, encoding="utf-8") as f:
            data = _json.load(f)
        co = data.get("company", {}) or {}
        return {
            "name":      data.get("name") or co.get("name") or p.stem,
            "saved_at":  data.get("saved_at", ""),
            "n_filings": len(co.get("doc_sections") or []),
            "n_tables":  len([t for t in (co.get("all_tables") or [])
                              if not t.get("multi_year")]),
        }
    except Exception:
        return None


def list_library_entries(lib_dir: "Optional[Path]" = None) -> list:
    """Return library entries sorted alphabetically by name:
    [{name, path, saved_at, n_filings, n_tables}, ...].

    Reads the lightweight index instead of parsing every snapshot. Missing index
    rows are backfilled once (first run / legacy files); stale rows are pruned.
    """
    d = Path(lib_dir) if lib_dir else library_dir()
    out = []
    if not d.exists():
        return out
    with _LIBRARY_INDEX_LOCK:
        idx = _load_library_index(d)
        files = {p.name: p for p in d.glob("*.json") if p.name != _LIBRARY_INDEX_NAME}
        changed = False
        for fname, p in files.items():
            meta = idx.get(fname)
            if not meta:
                meta = _scan_library_file(p)
                if meta is None:
                    continue
                idx[fname] = meta
                changed = True
            out.append({
                "name":      meta.get("name") or p.stem,
                "path":      p,
                "saved_at":  meta.get("saved_at", ""),
                "n_filings": meta.get("n_filings", 0),
                "n_tables":  meta.get("n_tables", 0),
            })
        for fname in [k for k in idx if k not in files]:
            del idx[fname]
            changed = True
        if changed:
            _write_library_index(d, idx)
    out.sort(key=lambda e: (e["name"] or "").lower())
    return out


def load_library_company(path: "Path") -> "Optional[dict]":
    """Load a company-session dict from a library JSON file. Never raises."""
    import json as _json
    try:
        with open(Path(path), encoding="utf-8") as f:
            data = _json.load(f)
        co = data.get("company")
        return co if isinstance(co, dict) else None
    except Exception:
        return None


def delete_library_entry(path: "Path") -> bool:
    """Delete a library snapshot file and prune its index entry. Never raises."""
    try:
        p = Path(path)
        p.unlink()
        with _LIBRARY_INDEX_LOCK:
            idx = _load_library_index(p.parent)
            if p.name in idx:
                del idx[p.name]
                _write_library_index(p.parent, idx)
        return True
    except Exception:
        return False
