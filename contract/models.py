"""
Pydantic mirror of contract/profile.ts. Field names are snake_case.
Both sides of the pipeline validate against this. Keep in sync by hand until
the CI regeneration check exists.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

SlotId = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
SLOT_ORDER: list[SlotId] = ["top_left", "top_right", "bottom_left", "bottom_right"]

SizeClass = Literal["klein", "mittelgross", "gross"]
PresentationBasis = Literal["umsatzerloese","bruttoumsatzerloese", "nettoumsatzerloese", "gesamtleistung", "rohergebnis", "betriebsleistung", "n/a"]
Confidence = Literal["high", "medium", "low"]
RuleId = Literal["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10","V11"]
Severity = Literal["blocking", "note_required", "advisory"]
EarningsBasis = Literal["reported", "adjusted"]

BlockKind = Literal[
    "bullets",
    "chart.column_line",
    "chart.stacked_column",
    "table",
    "map",
    "image_grid",
    "timeline",
]


class Register(BaseModel):
    court: str
    type: Literal["HRA", "HRB"]
    number: str


class Provenance(BaseModel):
    doc: str
    sheet: str
    row: int
    page: int | None = None
    std_id: str | None = None


class Impostor(BaseModel):
    name: str
    reason: str


class Entity(BaseModel):
    legal_name: str
    register: Register
    legal_form: str
    fiscal_year_end: str
    size_class: SizeClass
    files_konzernabschluss: bool
    years_available: list[int]
    confirmed_by: str | None = None
    impostors: list[Impostor] = Field(default_factory=list)


class Flag(BaseModel):
    rule: RuleId
    severity: Severity
    message: str
    note: str | None = None


class SeriesPoint(BaseModel):
    fy: int
    value: float


class ContentBlock(BaseModel):
    id: str
    title: str
    kind: BlockKind
    eligible_slots: list[SlotId]
    earnings_basis: EarningsBasis | None = None
    coverage: float = Field(ge=0, le=1)
    confidence: Confidence
    source: str
    presentation_basis: PresentationBasis
    unavailable_reason: str | None = None
    flags: list[Flag] = Field(default_factory=list)
    footnotes_auto: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    series: list[SeriesPoint] | None = None


class CoverageDimension(BaseModel):
    label: str
    score: float = Field(ge=0, le=1)


class Profile(BaseModel):
    entity: Entity
    blocks: list[ContentBlock]
    canonical_layout: dict[str, str]
    coverage: list[CoverageDimension]

