"""Canonical, auditable multi-year consolidation for extracted filings."""

from __future__ import annotations

import csv
import re
from collections import OrderedDict
from math import isclose
from pathlib import Path
from typing import Any, Optional

from ._core import PROJECT_ROOT, _HGB_AVAILABLE, _hgb, _parse_num_cell
from .extract import effective_table_type


_LEADING_ITEM = re.compile(r"^\s*(?:[a-z]\)|[IVXLM]+[.)]|\d+[a-z]?[.)])\s*")
_DAVON_NOTE = re.compile(r"^\s*-\s*davon\b", re.I)
_UNIT_RE = re.compile(r"(?:t(?:eur|euro|sd\.?)|t(?:€|â‚¬))", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_QUEUE_PATH = PROJECT_ROOT / "reviews" / "unmapped_queue.csv"
_ALIASES_PATH = PROJECT_ROOT / "aliases" / "client_aliases.csv"
_UNSAFE_AGGREGATE_KEYS = {"materialaufwand", "personalaufwand", "abschreibungen"}
_SUBTOTAL_EXTENSIONS = {
    "gesamtleistung": ("PL_GKV-GESAMTLEISTUNG", "Gesamtleistung"),
    "rohergebnis": ("PL_GKV-ROHERGEBNIS", "Rohergebnis"),
    "konzernbilanzverlust": ("PL_GKV-BILANZVERLUST", "Konzernbilanzverlust"),
}


def _display_label_key(label: str) -> str:
    """Remove only statement numbering before the mapper's exact lookup."""
    label = _LEADING_ITEM.sub("", str(label or "").strip())
    return re.sub(r"\s*\((?:gkv|ukv)\)\s*$", "", label, flags=re.I)


def _is_davon_note(label: str) -> bool:
    """Return whether a disclosure-only ``davon`` note must be excluded."""
    return bool(_DAVON_NOTE.match(str(label or "")))


def _load_exact_aliases(aliases_path: Optional[str | Path] = None) -> dict[str, str]:
    """Load generic then optional external reviewed aliases, exactly."""
    if not _HGB_AVAILABLE:
        return {}
    aliases: dict[str, str] = {}
    paths = [_ALIASES_PATH]
    if aliases_path:
        paths.append(Path(aliases_path))
    for path in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                label, std_id = row.get("client_label", ""), row.get("std_id", "")
                record = _hgb.by_id(std_id)
                normalized_key = row.get("normalized_key", "")
                key = normalized_key or (_hgb.normalize(_display_label_key(label)) if label else "")
                if key and record and record.get("row_type") in {"line", "subtotal"}:
                    aliases[key] = std_id
    return aliases


def _map_actual(label: str, aliases: dict[str, str], framework: str,
                pnl_method: str) -> tuple[Optional[dict], str, list[str]]:
    """Resolve one HGB actual exactly, subject to framework and method guards."""
    if not _HGB_AVAILABLE:
        return None, "none", []
    if _is_davon_note(label):
        return None, "excluded_davon_note", []
    if framework == "unknown":
        return None, "framework_undetermined", []
    if framework != "hgb":
        # The catalogue is HGB-only. Familiar German wording is not evidence
        # that an IFRS presentation has an HGB canonical meaning.
        return None, "unsupported_framework", []
    clean = _display_label_key(label)
    # The generated taxonomy currently maps these GKV aggregate headings to
    # their first child line. That is not an accounting-safe canonicalisation.
    # Keep the actual visible in the review queue until a parent taxonomy row
    # is generated upstream.
    if _hgb.normalize(clean) in _UNSAFE_AGGREGATE_KEYS:
        return None, "unsafe_aggregate_heading", []
    extension = _SUBTOTAL_EXTENSIONS.get(_hgb.normalize(clean))
    if extension:
        std_id, canonical_de = extension
        if pnl_method != "gkv":
            return None, "pnl_method_undetermined" if pnl_method == "unknown" else "pnl_method_mismatch", []
        return {"std_id": std_id, "canonical_de": canonical_de, "canonical_en": "",
                "row_type": "subtotal", "statement": "PL_GKV"}, "extension_exact", []
    alias = aliases.get(_hgb.normalize(clean))
    if alias:
        record = _hgb.by_id(alias)
        if record and record.get("statement") in {"PL_GKV", "PL_UKV"}:
            expected = "gkv" if record["statement"] == "PL_GKV" else "ukv"
            if pnl_method != expected:
                return None, "pnl_method_undetermined" if pnl_method == "unknown" else "pnl_method_mismatch", []
        return record, "client_alias_exact", []
    lookup = _hgb.lookup(clean)
    candidates = lookup.get("candidates", [])
    if len(candidates) != 1:
        return None, lookup.get("match_type", "none"), [c.get("std_id", "") for c in candidates]
    record = candidates[0]
    if record.get("row_type") not in {"line", "subtotal"}:
        return None, "non_line", [record.get("std_id", "")]
    if record.get("statement") in {"PL_GKV", "PL_UKV"}:
        expected = "gkv" if record["statement"] == "PL_GKV" else "ukv"
        if pnl_method != expected:
            return None, "pnl_method_undetermined" if pnl_method == "unknown" else "pnl_method_mismatch", [record.get("std_id", "")]
    return record, lookup.get("match_type", "none"), []


def _queue_unmapped(entries: list[dict[str, Any]], path: Optional[str | Path] = None) -> None:
    """Rewrite one run's distinct unresolved labels to the review queue.

    Deduplication is meant to collapse the SAME unresolved label recurring
    across years/tables into one review item. A blank ``raw_label`` (an
    unverified positional subtotal -- see ``_column_actuals``) has no such
    identity: two blank rows from two different tables are two different
    unresolved facts, not one repeated label, and must not collapse into a
    single queue entry. Fall back to a table+row identifier in that case so
    dedup never conflates them.
    """
    queue_path = Path(path) if path is not None else _QUEUE_PATH
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("raw_label", "normalized_key", "match_type", "candidates",
              "doc_label", "heading", "page_start", "row")
    seen: set[str] = set()
    with queue_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for entry in entries:
            key = (entry.get("normalized_key", "") or entry["raw_label"]
                   or f"{entry.get('heading', '')}#{entry.get('row', '')}")
            if key not in seen:
                writer.writerow({name: entry.get(name, "") for name in fields})
                seen.add(key)


def _unit_multiplier(table: dict) -> float:
    """Detect a filing table's presentation unit; canonical output is EUR."""
    probe = " ".join(str(cell or "") for row in (table.get("rows") or [])[:10] for cell in row)
    probe += " " + str(table.get("heading", ""))
    return 1_000.0 if _UNIT_RE.search(probe) else 1.0


def _parse_eur(value: Any, multiplier: float) -> Optional[float]:
    """Parse German numeric cells including ``+ 1.914.645,32`` into EUR."""
    if isinstance(value, (int, float)):
        return float(value) * multiplier
    text = str(value or "").strip()
    if not text or text in ("-", "–", "—"):
        return None
    bracket_negative = text.startswith("(") and text.endswith(")")
    if bracket_negative:
        text = text[1:-1].strip()
    text = re.sub(r"^\+\s*", "", text)
    parsed = _parse_num_cell(text, thousand_sep=".", decimal_sep=",")
    if parsed is None:
        return None
    return (-abs(parsed) if bracket_negative else parsed) * multiplier


def _year_from_header(value: Any) -> Optional[int]:
    years = _YEAR_RE.findall(str(value or ""))
    # Fiscal-period headers contain both start and end years (for example
    # ``2024/2025``); canonical fiscal years are keyed by the end year.
    return max(map(int, years)) if years else None


def _year_blocks(rows: list[list[Any]]) -> tuple[int, list[tuple[int, int, int]]]:
    """Find all fiscal-year column blocks, including detail/subtotal pairs."""
    for ri, row in enumerate(rows[:10]):
        hits = [(ci, _year_from_header(cell)) for ci, cell in enumerate(row) if ci and _year_from_header(cell)]
        if not hits:
            continue
        # The trailing "PDF Page" provenance column is not a value column: every
        # row in these tables carries a page number there, and a genuinely blank
        # last year's value would otherwise silently pick it up as a phantom actual.
        last_col = len(row) - 1
        if str(row[last_col] or "").strip().lower() == "pdf page":
            last_col -= 1
        blocks: list[tuple[int, int, int]] = []
        for pos, (start, year) in enumerate(hits):
            end = hits[pos + 1][0] - 1 if pos + 1 < len(hits) else last_col
            if blocks and blocks[-1][0] == year and start <= blocks[-1][2] + 1:
                blocks[-1] = (year, blocks[-1][1], end)
            else:
                blocks.append((year, start, end))
        return ri, blocks
    return -1, []


_TOP_LEVEL_HEADER = re.compile(r"^\d+[.)]\s*\S")


def _values_match(window: list[tuple[str, dict[int, tuple[float, int]]]],
                  target: dict[int, tuple[float, int]]) -> bool:
    """Whether every disclosed year on ``target`` ties exactly to the window's sum."""
    if not window or not target:
        return False
    for year, (value, _priority) in target.items():
        parts = [values[year][0] for _std_id, values in window if year in values]
        if len(parts) != len(window) or abs(sum(parts) - value) > 0.01:
            return False
    return True


def _column_actuals(table: dict, aliases: dict[str, str], queued: list[dict[str, Any]]) -> dict[int, OrderedDict[str, dict]]:
    """Return ``year -> std_id -> actual`` using left-to-right block coalescing.

    A blank first cell is not necessarily decorative: German GKV/UKV filings
    print several subtotals (Gesamtleistung, a cost category's own total,
    Finanzergebnis, ...) with no caption of their own. Such a row is only ever
    retained if its disclosed value(s) tie exactly to a specific, identifiable
    run of already-resolved component lines -- never on faith. Two windows are
    tried, most specific first: the lines since the nearest open, unmapped
    top-level heading (e.g. "4. Materialaufwand" decomposing into a)/b) lines),
    then the lines since the last confirmed subtotal. A row that matches
    neither is queued, not dropped and not guessed.
    """
    rows = table.get("rows") or []
    header_row, blocks = _year_blocks(rows)
    if header_row < 0:
        return {}
    multiplier = _unit_multiplier(table)
    result: dict[int, OrderedDict[str, dict]] = {}
    collisions: dict[int, set[str]] = {}
    accumulator: list[tuple[str, dict[int, tuple[float, int]]]] = []
    open_group_label: Optional[str] = None
    group_start: int = 0

    def _store(group_key: str, label: str, record: dict, row_number: int,
               values: dict[int, tuple[float, int]]) -> None:
        for year, (value, year_priority) in values.items():
            by_id = result.setdefault(year, OrderedDict())
            if group_key in collisions.setdefault(year, set()):
                continue
            current = by_id.get(group_key)
            if current and current["raw_label"] != label:
                # A collision is unsafe: do not silently retain whichever happened first.
                for collision in (current, {"raw_label": label, "row": row_number}):
                    queued.append({
                        "raw_label": collision["raw_label"], "normalized_key": group_key,
                        "match_type": "std_id_collision", "candidates": group_key,
                        "doc_label": table.get("doc_label", ""), "heading": table.get("heading", ""),
                        "page_start": table.get("page_start", ""), "row": collision["row"],
                    })
                by_id.pop(group_key, None)
                collisions[year].add(group_key)
                continue
            if group_key not in by_id:
                by_id[group_key] = {"raw_label": label, "value": value, "row": row_number,
                                    "record": record, "source_unit": "TEUR" if multiplier == 1_000 else "EUR",
                                    "year_priority": year_priority,
                                    "doc_label": table.get("doc_label", ""),
                                    "heading": table.get("heading", ""),
                                    "page_start": table.get("page_start"),
                                    "table_index": table.get("index")}

    for row_number, row in enumerate(rows[header_row + 1:], start=header_row + 1):
        label = str(row[0] or "").strip() if row else ""
        if _is_davon_note(label):
            continue
        values: dict[int, tuple[float, int]] = {}
        for block_index, (year, start, end) in enumerate(blocks):
            for ci in range(start, min(end + 1, len(row))):
                parsed = _parse_eur(row[ci], multiplier)
                if parsed is not None:
                    values[year] = (parsed, 0 if block_index == 0 else 1)
                    break

        if not label:
            if not values:
                continue
            narrow = accumulator[group_start:]
            if open_group_label and _values_match(narrow, values):
                record = {"std_id": None, "canonical_de": open_group_label, "canonical_en": "",
                          "row_type": "subtotal", "statement": table.get("framework") or "",
                          "components": {std_id: 1 for std_id, _ in narrow}}
                _store(f"__subtotal_row{row_number}", open_group_label, record, row_number, values)
                open_group_label = None
                continue
            if _values_match(accumulator, values):
                record = {"std_id": None, "canonical_de": "", "canonical_en": "",
                          "row_type": "subtotal", "statement": table.get("framework") or "",
                          "components": {std_id: 1 for std_id, _ in accumulator}}
                _store(f"__subtotal_row{row_number}", "", record, row_number, values)
                accumulator = []
                group_start = 0
                open_group_label = None
                continue
            queued.append({
                "raw_label": "", "normalized_key": "",
                "match_type": "unlabelled_no_verified_subtotal", "candidates": "",
                "doc_label": table.get("doc_label", ""), "heading": table.get("heading", ""),
                "page_start": table.get("page_start", ""), "row": row_number,
            })
            continue

        if not values:
            # A top-level heading with no value of its own decomposes into
            # lettered sub-items below; remember it so a later unlabelled
            # subtotal can be attributed back to it. A heading that never
            # reaches _map_actual can't collide with _UNSAFE_AGGREGATE_KEYS,
            # so this is orthogonal to that guard.
            if _TOP_LEVEL_HEADER.match(label):
                open_group_label = label
                group_start = len(accumulator)
            continue

        if _TOP_LEVEL_HEADER.match(label):
            # A fully-valued top-level line (no decomposition) closes out any
            # stale open heading from a filing shape this fixture doesn't have.
            open_group_label = None

        framework = str(table.get("framework") or "unknown").lower()
        pnl_method = str(table.get("pnl_method") or "unknown").lower()
        record, match_type, candidates = _map_actual(label, aliases, framework, pnl_method)
        if record is None:
            queued.append({
                "raw_label": label,
                "normalized_key": _hgb.normalize(_display_label_key(label)) if _HGB_AVAILABLE else "",
                "match_type": match_type, "candidates": ";".join(candidates),
                "doc_label": table.get("doc_label", ""), "heading": table.get("heading", ""),
                "page_start": table.get("page_start", ""), "row": row_number,
            })
            continue
        std_id = record["std_id"]
        accumulator.append((std_id, values))
        _store(std_id, label, record, row_number, values)
    return result


def build_multi_year_tables(tables: list, row_merges: "Optional[dict]" = None,
                            aliases_path: Optional[str | Path] = None,
                            queue_path: Optional[str | Path] = None) -> list:
    """Build line-only, EUR-normalised canonical exports keyed by ``std_id``.

    ``row_merges`` is retained for API compatibility but deliberately ignored:
    manual label merges are not an acceptable substitute for an exact taxonomy
    match in the canonical export.
    """
    del row_merges
    source = [t for t in tables if not t.get("multi_year") and t.get("_include_in_overview", True) is not False]
    groups: dict[tuple[int, str, str], list[dict]] = {}
    for table in source:
        table_type = effective_table_type(table)
        if table_type != 99:
            framework = str(table.get("framework") or "unknown").lower()
            pnl_method = str(table.get("pnl_method") or "unknown").lower()
            groups.setdefault((table_type, framework, pnl_method), []).append(table)

    aliases = _load_exact_aliases(aliases_path)
    queued: list[dict[str, Any]] = []
    names = {0: "Bilanz", 1: "GuV", 2: "Kapitalflussrechnung"}
    result: list[dict] = []
    for (table_type, framework, pnl_method), group in sorted(groups.items()):
        yearly: dict[int, OrderedDict[str, dict]] = {}
        yearly_collisions: dict[int, set[str]] = {}
        for table in group:
            for year, actuals in _column_actuals(table, aliases, queued).items():
                target = yearly.setdefault(year, OrderedDict())
                for std_id, actual in actuals.items():
                    if std_id in yearly_collisions.setdefault(year, set()):
                        continue
                    if std_id not in target:
                        target[std_id] = actual
                    elif actual["year_priority"] < target[std_id]["year_priority"]:
                        target[std_id] = actual
                    elif actual["year_priority"] > target[std_id]["year_priority"]:
                        continue
                    elif target[std_id]["raw_label"] != actual["raw_label"]:
                        if (target[std_id].get("table_index") != actual.get("table_index")
                                and isclose(target[std_id]["value"], actual["value"], abs_tol=0.01)):
                            # Same std_id, same value, from two distinct source
                            # tables in this group -- e.g. a GmbH & Co. KG's
                            # "loss not covered by capital contributions" is
                            # disclosed on both Aktiva and Passiva with the
                            # identical figure. That is a confirmed mirror of
                            # one fact, not an ambiguous collision: two rows
                            # from the SAME table disagreeing on a std_id would
                            # still fall through and queue below. Keep the
                            # first one seen.
                            continue
                        # Two source rows in the same statement-year may not
                        # compete for one canonical actual. Queue both and
                        # leave the figure blank pending review.
                        prior = target.pop(std_id)
                        yearly_collisions[year].add(std_id)
                        for collision in (prior, actual):
                            queued.append({
                                "raw_label": collision["raw_label"], "normalized_key": std_id,
                                "match_type": "std_id_collision", "candidates": std_id,
                                "doc_label": collision["doc_label"], "heading": collision["heading"],
                                "page_start": collision["page_start"] or "", "row": collision["row"],
                            })
        yearly = {year: actuals for year, actuals in yearly.items() if actuals}
        if len(yearly) < 2:
            continue
        years = sorted(yearly, reverse=True)
        ordered_ids: OrderedDict[str, None] = OrderedDict()
        for year in years:
            ordered_ids.update({std_id: None for std_id in yearly[year]})
        rows: list[list[Any]] = [["Description"] + [str(year) for year in years]]
        source_labels: list[dict[int, str]] = []
        metadata: list[dict[str, Any]] = []
        for std_id in ordered_ids:
            first = next(yearly[year][std_id] for year in years if std_id in yearly[year])
            row = [first["raw_label"]]
            labels: dict[int, str] = {}
            provenance: dict[int, dict[str, Any]] = {}
            for year in years:
                actual = yearly[year].get(std_id)
                row.append(actual["value"] if actual else "")
                labels[year] = actual["raw_label"] if actual else ""
                if actual:
                    provenance[year] = {"doc": actual["doc_label"] or "Konzernabschluss " + str(year),
                                        "sheet": actual["heading"],
                                        "row": actual["row"], "page": actual["page_start"]}
            rows.append(row)
            source_labels.append(labels)
            metadata.append({"std_id": first["record"].get("std_id"), "raw_labels": labels,
                             "row_type": first["record"]["row_type"],
                             "components": first["record"].get("components"),
                             "unit": "EUR", "presentation_basis": "umsatzerloese" if std_id in ("PL_GKV-1", "PL_UKV-1") else None,
                             "provenance": next(iter(provenance.values()), {}),
                             "provenance_by_fy": provenance})
        result.append({"index": -(table_type + 1), "heading": f"ALL — {names.get(table_type, f'Type{table_type}')}",
                       "doc_label": "", "type": table_type, "multi_year": True, "years": years,
                       "page_start": 0, "page_end": 0, "row_count": len(rows) - 1, "rows": rows,
                       "row_source_labels": source_labels, "row_metadata": metadata, "unit": "EUR",
                       "framework": framework, "pnl_method": pnl_method,
                       "framework_evidence": group[0].get("framework_evidence"),
                       "pnl_method_evidence": group[0].get("pnl_method_evidence")})
    _queue_unmapped(queued, queue_path)
    return result
