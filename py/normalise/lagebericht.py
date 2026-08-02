"""Extract stated, reviewable facts from classifier-approved Lagebericht prose.

This module deliberately does not calculate operating performance from other
figures.  It records only what management states in the source text and keeps
the original sentence when a triggered disclosure has no safely attributable
amount.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


Unit = Literal["EUR"]
SourceUnit = Literal["EUR", "TEUR"]
Direction = Literal["income", "expense", "unknown"]

_FY = re.compile(r"FY\s*(20\d{2})", re.I)
_YEAR = re.compile(r"\b(20\d{2})\b")
_NUMBER = re.compile(r"(?<!\w)(?:[+\-−–]\s*)?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?(?!\w)")
_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.20\d{2}\b|\b(?:zum|ab|seit)\s+\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+20\d{2}\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_OPERATING = re.compile(r"\b(?:betriebs|geschäfts|operatives?)ergebnis\b|jahresergebnis\s*\([^)]*(?:finanzergebnis|steuern)", re.I)
_ONE_OFF = re.compile(r"nicht\s*operativ|sondereffekt|periodenfremd|einmal(?:aufwendungen?|ertr[aä]ge|effekt)", re.I)
_MOVEMENT = re.compile(r"umsatz(?:erlöse)?|erlöse|kosten|aufwand|materialaufwand|personalaufwand", re.I)
_CAUSE = re.compile(r"aufgrund|bedingt\s+durch|wegen|zurückzuführen|resultier", re.I)
_SEGMENT = re.compile(r"segment|sparte|bereich|division|geschäftsfeld|marke", re.I)
_GOING_CONCERN = re.compile(r"fortführungsprognose|fortf(?:ü|ue)hrung|going concern|bilanzielle\s+unterdeckung", re.I)
_FINANCING = re.compile(r"finanzierungs(?:vereinbarung|vertrag)|kreditvereinbarung|stundungsvereinbarung|waiver|covenant", re.I)
_SCOPE = re.compile(r"konsolidierungskreis|erstkonsolid|entkonsolid|aus\s+dem\s+konsolidierungskreis|in\s+den\s+konsolidierungskreis", re.I)


class LageberichtProvenance(BaseModel):
    doc: str
    sheet: str
    row: int
    page: int | None = None


class StatedOperatingResult(BaseModel):
    fiscal_year: int
    value: float | None
    prior_year_value: float | None = None
    unit: Unit | None = None
    source_unit: SourceUnit | None = None
    statement: str
    provenance: LageberichtProvenance


class OneOffAmount(BaseModel):
    fiscal_year: int
    value: float | None
    unit: Unit | None = None
    source_unit: SourceUnit | None = None
    direction: Direction
    description: str
    pnl_line: str | None = None
    sentence: str
    provenance: LageberichtProvenance


class MovementExplanation(BaseModel):
    fiscal_year: int
    metric: Literal["revenue", "cost", "unknown"]
    segment_or_division: str | None = None
    sentence: str
    provenance: LageberichtProvenance


class GoingConcernDisclosure(BaseModel):
    fiscal_year: int
    kind: Literal["fortfuehrungsprognose", "bilanzielle_unterdeckung", "financing_agreement"]
    value: float | None = None
    unit: Unit | None = None
    source_unit: SourceUnit | None = None
    dates: tuple[str, ...] = ()
    sentence: str
    provenance: LageberichtProvenance


class ScopeChange(BaseModel):
    fiscal_year: int
    entity: str | None = None
    change: Literal["entered", "left", "mentioned"]
    dates: tuple[str, ...] = ()
    sentence: str
    provenance: LageberichtProvenance


class LageberichtExtraction(BaseModel):
    operating_results: list[StatedOperatingResult] = Field(default_factory=list)
    one_offs: list[OneOffAmount] = Field(default_factory=list)
    movement_explanations: list[MovementExplanation] = Field(default_factory=list)
    going_concern: list[GoingConcernDisclosure] = Field(default_factory=list)
    scope_changes: list[ScopeChange] = Field(default_factory=list)


def _text(value: Any) -> str:
    return str(value or "").replace("\xa0", " ").strip()


def _fiscal_year(sheet: str) -> int | None:
    match = _FY.search(sheet)
    return int(match.group(1)) if match else None


def _source_unit(text: str) -> SourceUnit | None:
    normalised = text.lower().replace("â‚¬", "€")
    if any(token in normalised for token in ("t€", "teur", "teuro", "t euro", "tâ€š")):
        return "TEUR"
    if "€" in normalised or "eur" in normalised or "euro" in normalised:
        return "EUR"
    return None


def _number(value: str) -> float:
    text = value.replace(" ", "").replace("−", "-").replace("–", "-")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1 or re.fullmatch(r"[+\-]?\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    return float(text)


def _amounts(sentence: str, source_unit: SourceUnit | None) -> list[float]:
    """Return amounts only where the source establishes a unit."""
    if source_unit is None:
        return []
    scale = 1_000.0 if source_unit == "TEUR" else 1.0
    without_dates = _DATE.sub("", sentence)
    return [_number(match.group(0)) * scale for match in _NUMBER.finditer(without_dates)]


def _metric(sentence: str) -> Literal["revenue", "cost", "unknown"]:
    lowered = sentence.lower()
    if "umsatz" in lowered or "erlös" in lowered or "erloes" in lowered:
        return "revenue"
    if any(term in lowered for term in ("kosten", "aufwand", "material", "personal")):
        return "cost"
    return "unknown"


def _direction(sentence: str) -> Direction:
    lowered = sentence.lower()
    if re.search(r"(?:t€|teur|eur|€)?\s*[−–-]\s*\d", lowered):
        return "expense"
    if any(term in lowered for term in ("aufwendungen", "belastung", "verlust", "kosten")):
        return "expense"
    if any(term in lowered for term in ("erträge", "ertraege", "gewinn", "entlastung")):
        return "income"
    return "unknown"


def _pnl_line(sentence: str) -> str | None:
    patterns = (
        (r"sonstig\w*\s+betrieblich\w*\s+ertr[aä]g", "sonstige betriebliche Erträge"),
        (r"sonstig\w*\s+betrieblich\w*\s+aufwendung", "sonstige betriebliche Aufwendungen"),
        (r"materialaufwand", "Materialaufwand"),
        (r"personalaufwand", "Personalaufwand"),
        (r"finanzergebnis", "Finanzergebnis"),
    )
    for pattern, line in patterns:
        if re.search(pattern, sentence, re.I):
            return line
    return None


def _entity(sentence: str) -> str | None:
    match = re.search(r"([A-ZÄÖÜ][\wÄÖÜäöüß&.\- ]{2,}?(?:GmbH|AG|KG|SE|Ltd\.))", sentence)
    if match is None:
        return None
    return re.sub(r"^(?:Die|Der|Das)\s+", "", match.group(1).strip())


def _segment_or_division(sentence: str) -> str | None:
    match = re.search(r"\b(?:segment|sparte|bereich|division|geschäftsfeld|marke)\s+['\"„]?(.+?)(?=\s+(?:ging|stieg|sank|fiel|reduzierte|wuchs|entwickelte)\b|[,.;:()])", sentence, re.I)
    return match.group(1).strip(" '\"„“") if match else None


def _provenance(sheet: str, row: int) -> LageberichtProvenance:
    return LageberichtProvenance(doc=sheet.split("_", 1)[0], sheet=sheet, row=row)


def parse_lagebericht_sheet(worksheet: Any) -> LageberichtExtraction:
    """Parse one approved Lagebericht worksheet, retaining ambiguity verbatim."""
    result = LageberichtExtraction()
    fiscal_year = _fiscal_year(worksheet.title)
    if fiscal_year is None:
        return result
    rows = [(index, " ".join(_text(cell) for cell in row if _text(cell))) for index, row in enumerate(worksheet.iter_rows(values_only=True), 1)]
    sheet_unit = _source_unit(" ".join(text for _, text in rows))
    for row_number, cell_text in rows:
        if not cell_text:
            continue
        for sentence in (part.strip() for part in _SENTENCE.split(cell_text) if part.strip()):
            unit = _source_unit(sentence) or sheet_unit
            amounts = _amounts(sentence, unit)
            amount_unit = unit if amounts else None
            provenance = _provenance(worksheet.title, row_number)
            if _OPERATING.search(sentence):
                result.operating_results.append(StatedOperatingResult(
                    fiscal_year=fiscal_year, value=amounts[0] if amounts else None,
                    prior_year_value=amounts[1] if len(amounts) > 1 else None,
                    unit="EUR" if amount_unit else None, source_unit=amount_unit, statement=sentence, provenance=provenance,
                ))
            if _ONE_OFF.search(sentence):
                result.one_offs.append(OneOffAmount(
                    fiscal_year=fiscal_year, value=amounts[0] if amounts else None,
                    unit="EUR" if amount_unit else None, source_unit=amount_unit, direction=_direction(sentence),
                    description=sentence, pnl_line=_pnl_line(sentence), sentence=sentence, provenance=provenance,
                ))
            if _MOVEMENT.search(sentence) and _CAUSE.search(sentence) and _SEGMENT.search(sentence):
                result.movement_explanations.append(MovementExplanation(
                    fiscal_year=fiscal_year, metric=_metric(sentence), sentence=sentence,
                    segment_or_division=_segment_or_division(sentence), provenance=provenance,
                ))
            kinds: list[Literal["fortfuehrungsprognose", "bilanzielle_unterdeckung", "financing_agreement"]] = []
            if _GOING_CONCERN.search(sentence) and not re.search(r"bilanzielle\s+unterdeckung", sentence, re.I):
                kinds.append("fortfuehrungsprognose")
            if re.search(r"bilanzielle\s+unterdeckung", sentence, re.I):
                kinds.append("bilanzielle_unterdeckung")
            if _FINANCING.search(sentence):
                kinds.append("financing_agreement")
            for kind in kinds:
                result.going_concern.append(GoingConcernDisclosure(
                    fiscal_year=fiscal_year, kind=kind, value=amounts[0] if amounts else None,
                    unit="EUR" if amount_unit else None, source_unit=amount_unit, dates=tuple(_DATE.findall(sentence)),
                    sentence=sentence, provenance=provenance,
                ))
            if _SCOPE.search(sentence):
                lowered = sentence.lower()
                change: Literal["entered", "left", "mentioned"] = (
                    "left" if any(term in lowered for term in ("entkonsolid", "aus dem konsolidierungskreis"))
                    else "entered" if any(term in lowered for term in ("erstkonsolid", "in den konsolidierungskreis")) else "mentioned"
                )
                result.scope_changes.append(ScopeChange(
                    fiscal_year=fiscal_year, entity=_entity(sentence), change=change,
                    dates=tuple(_DATE.findall(sentence)), sentence=sentence, provenance=provenance,
                ))
    return result


def extract_lagebericht(workbook: Any, classifications: dict[str, str]) -> LageberichtExtraction:
    """Extract facts from sheets explicitly classified as Lagebericht sections."""
    result = LageberichtExtraction()
    permitted = {"lagebericht_vermoegenslage", "lagebericht_finanzlage"}
    for sheet_name, kind in classifications.items():
        if kind not in permitted:
            continue
        parsed = parse_lagebericht_sheet(workbook[sheet_name])
        result.operating_results.extend(parsed.operating_results)
        result.one_offs.extend(parsed.one_offs)
        result.movement_explanations.extend(parsed.movement_explanations)
        result.going_concern.extend(parsed.going_concern)
        result.scope_changes.extend(parsed.scope_changes)
    return result
