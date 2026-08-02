"""Parse revenue-disclosure segment tables without inventing comparability.

The filing appendix uses both product/division (``Segmente``) and geographic
(``Absatzmaerkte``) splits.  They look similar, but are separate dimensions and
must remain so.  A table can also be expressed as percentages; those figures
are retained as percentages and never scaled into currency.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field


SegmentType = Literal["product", "geography"]
Unit = Literal["EUR", "PCT"]

_NUMBER = re.compile(r"^[+\-\s]*[\d.,]+\s*%?$")
_YEAR = re.compile(r"20\d{2}")
_ITEM_NUMBER = re.compile(r"^\s*(?:[A-Z]|[IVXLCDM]+|\d+)\s*[.)]\s*", re.I)
_PRODUCT_HEADING = re.compile(r"(?:^|\s)(?:a|i)\.\s*segmente?\b", re.I)
_GEOGRAPHY_HEADING = re.compile(r"(?:^|\s)(?:b|ii)\.\s*absatzm(?:a|ä)rkte\b", re.I)
_TOTAL = re.compile(r"(?:brutto|netto)umsatz", re.I)


class SegmentProvenance(BaseModel):
    sheet: str
    row: int


class SegmentFigure(BaseModel):
    """One disclosed segment value, normalised to EUR unless percentage-based."""

    segment_name: str
    segment_type: SegmentType
    fiscal_year: int
    metric: str
    value: float
    unit: Unit
    presentation_basis: str | None
    provenance: SegmentProvenance
    flags: tuple[str, ...] = ()


class SegmentReview(BaseModel):
    sheet: str
    reason: str


class SegmentExtraction(BaseModel):
    figures: list[SegmentFigure] = Field(default_factory=list)
    reviews: list[SegmentReview] = Field(default_factory=list)
    discontinuities: list[str] = Field(default_factory=list)


def _text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _text(value)
    if not text or not _NUMBER.fullmatch(text):
        return None
    text = text.replace("%", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _year(value: Any) -> int | None:
    years = [int(match) for match in _YEAR.findall(_text(value))]
    return max(years) if years else None


def _unit(rows: list[list[Any]], column: int) -> Unit | None:
    blob = " ".join(_text(row[column]) for row in rows[:12] if column < len(row)).lower()
    if "%" in blob or "prozent" in blob:
        return "PCT"
    if any(token in blob for token in ("t€", "tâ‚¬", "teur", "teuro", "tsd.")):
        return "EUR"
    # Extracted workbook cells may have lost the euro glyph, but EUR is still
    # explicit only when the header says EUR/Euro.  Otherwise request review.
    if "eur" in blob or "euro" in blob or "€" in blob:
        return "EUR"
    return None


def _year_columns(rows: list[list[Any]]) -> dict[int, tuple[int, Unit]]:
    """Find absolute-value columns; intentionally omit change-only columns."""
    columns: dict[int, tuple[int, Unit]] = {}
    for row_index, row in enumerate(rows[:12]):
        for column, cell in enumerate(row[1:], 1):
            year = _year(cell)
            if year is None:
                continue
            nearby = " ".join(_text(rows[index][column]) for index in range(row_index, min(row_index + 3, len(rows))) if column < len(rows[index])).lower()
            if "veränderung" in nearby or "veraenderung" in nearby or "zum vorjahr" in nearby:
                continue
            unit = _unit(rows, column)
            if unit is not None:
                columns[column] = (year, unit)
        if columns:
            return columns
    return columns


def _section_type(label: str) -> SegmentType | None:
    if _PRODUCT_HEADING.search(label):
        return "product"
    if _GEOGRAPHY_HEADING.search(label):
        return "geography"
    return None


def _basis(section_rows: list[tuple[int, list[Any]]], year_columns: dict[int, tuple[int, Unit]]) -> str | None:
    """Use a stated total only; headings such as 'Umsatzerloese' are insufficient."""
    labels = " ".join(_text(row[0]) for _, row in section_rows if row)
    gross = "bruttoumsatz" in labels.lower()
    net = "nettoumsatz" in labels.lower()
    if gross and net:
        # Component lines in this disclosure reconcile to gross revenue; the
        # net line is an adjustment total, not a third segment.
        return "bruttoumsatzerloese"
    if gross:
        return "bruttoumsatzerloese"
    if net:
        return "nettoumsatzerloese"
    return None


def parse_segment_sheet(worksheet: Any) -> SegmentExtraction:
    """Extract one classifier-approved ``anhang_umsatzsplit`` worksheet."""
    rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
    result = SegmentExtraction()
    year_columns = _year_columns(rows)
    if not year_columns:
        result.reviews.append(SegmentReview(sheet=worksheet.title, reason="no fiscal-year value columns with an explicit unit"))
        return result

    sections: list[tuple[SegmentType, list[tuple[int, list[Any]]]]] = []
    current_type: SegmentType | None = None
    current_rows: list[tuple[int, list[Any]]] = []
    for row_number, row in enumerate(rows, 1):
        label = _text(row[0]) if row else ""
        found_type = _section_type(label)
        if found_type is not None:
            if current_type is not None:
                sections.append((current_type, current_rows))
            current_type, current_rows = found_type, []
            continue
        if current_type is not None:
            current_rows.append((row_number, row))
    if current_type is not None:
        sections.append((current_type, current_rows))

    if not sections:
        result.reviews.append(SegmentReview(sheet=worksheet.title, reason="no product or geography segment heading"))
        return result

    seen_types: set[SegmentType] = set()
    for segment_type, section_rows in sections:
        # Some extractor splits repeat the section title for the separate
        # "Veränderung zum Vorjahr" mini-table.  That is not another vintage.
        if segment_type in seen_types:
            continue
        seen_types.add(segment_type)
        basis = _basis(section_rows, year_columns)
        if basis is None:
            result.reviews.append(SegmentReview(sheet=worksheet.title, reason=f"{segment_type} table has no explicit gross/net revenue basis"))
        for row_number, row in section_rows:
            label = _text(row[0]) if row else ""
            if not label or _TOTAL.search(label) or "erlösschmäler" in label.lower() or "erloesschmaeler" in label.lower():
                continue
            # Rows repeating units, change headers, or a second section marker
            # have no numeric segment values and naturally drop out here.
            name = _ITEM_NUMBER.sub("", label).strip()
            if not name:
                continue
            for column, (fiscal_year, unit) in year_columns.items():
                if column >= len(row):
                    continue
                value = _parse_number(row[column])
                if value is None:
                    continue
                metric = "revenue_share" if unit == "PCT" else "revenue"
                scale = 1.0 if unit == "PCT" else 1000.0 if _is_thousand_euro(rows, column) else 1.0
                flags: tuple[str, ...] = ("presentation_basis_unknown",) if basis is None else ()
                result.figures.append(SegmentFigure(
                    segment_name=name, segment_type=segment_type, fiscal_year=fiscal_year,
                    metric=metric, value=value * scale, unit=unit, presentation_basis=basis,
                    provenance=SegmentProvenance(sheet=worksheet.title, row=row_number), flags=flags,
                ))
    return result


def _is_thousand_euro(rows: list[list[Any]], column: int) -> bool:
    blob = " ".join(_text(row[column]) for row in rows[:12] if column < len(row)).lower()
    return any(token in blob for token in ("t€", "tâ‚¬", "teur", "teuro", "tsd."))


def _prefer(candidate: SegmentFigure, incumbent: SegmentFigure) -> bool:
    """Prefer the table filed for the value's own fiscal year, then newest doc."""
    candidate_doc_year = _year(candidate.provenance.sheet)
    incumbent_doc_year = _year(incumbent.provenance.sheet)
    return (candidate_doc_year == candidate.fiscal_year, candidate_doc_year or 0) > (incumbent_doc_year == incumbent.fiscal_year, incumbent_doc_year or 0)


def _deduplicate(figures: Iterable[SegmentFigure], reviews: list[SegmentReview]) -> list[SegmentFigure]:
    unique: dict[tuple[str, SegmentType, int, str], SegmentFigure] = {}
    conflicted: set[tuple[str, SegmentType, int, str]] = set()
    for figure in figures:
        key = (figure.segment_name.casefold(), figure.segment_type, figure.fiscal_year, figure.metric)
        current = unique.get(key)
        if current is None:
            unique[key] = figure
        elif current.value != figure.value or current.unit != figure.unit or current.presentation_basis != figure.presentation_basis:
            conflicted.add(key)
            reviews.append(SegmentReview(
                sheet=figure.provenance.sheet,
                reason=f"conflicting duplicate disclosure for {figure.segment_name} FY{figure.fiscal_year}",
            ))
        elif _prefer(figure, current):
            unique[key] = figure
    for key in conflicted:
        unique.pop(key, None)
    return sorted(unique.values(), key=lambda value: (value.segment_type, value.segment_name.casefold(), value.fiscal_year))


def _discontinuities(figures: Iterable[SegmentFigure]) -> list[str]:
    years_by_segment: dict[tuple[SegmentType, str, str], set[int]] = defaultdict(set)
    for figure in figures:
        years_by_segment[(figure.segment_type, figure.segment_name, figure.metric)].add(figure.fiscal_year)
    findings: list[str] = []
    for (segment_type, name, metric), years in sorted(years_by_segment.items()):
        for year in range(min(years), max(years)):
            if year not in years:
                findings.append(f"{segment_type}:{name}:{metric} not disclosed for FY{year}; no continuity assumed")
    return findings


def extract_segments(workbook: Any, classifications: dict[str, str]) -> SegmentExtraction:
    """Build the segment × fiscal-year × metric structure from tagged sheets."""
    result = SegmentExtraction()
    for sheet_name, kind in classifications.items():
        if kind != "anhang_umsatzsplit":
            continue
        parsed = parse_segment_sheet(workbook[sheet_name])
        result.figures.extend(parsed.figures)
        result.reviews.extend(parsed.reviews)
    result.figures = _deduplicate(result.figures, result.reviews)
    result.discontinuities = _discontinuities(result.figures)
    return result


def write_segment_review_queue(reviews: Iterable[SegmentReview], path: Path) -> int:
    """Persist reviewable tables explicitly; callers opt in to this side effect."""
    entries = list(reviews)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=("sheet", "reason"))
        writer.writeheader()
        writer.writerows(entry.model_dump() for entry in entries)
    return len(entries)
