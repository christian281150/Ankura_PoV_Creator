"""
Pydantic mirror of contract/profile.ts. Field names are snake_case.
Both sides of the pipeline validate against this. Keep in sync by hand until
the CI regeneration check exists.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

SlotId = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
SLOT_ORDER: list[SlotId] = ["top_left", "top_right", "bottom_left", "bottom_right"]

SizeClass = Literal["klein", "mittelgross", "gross"]
PresentationBasis = Literal["umsatzerloese","bruttoumsatzerloese", "nettoumsatzerloese", "gesamtleistung", "rohergebnis", "betriebsleistung", "n/a"]
Confidence = Literal["high", "medium", "low"]
RuleId = Literal["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11", "V12"]
Severity = Literal["blocking", "note_required", "advisory"]
EarningsBasis = Literal["reported", "adjusted"]
Framework = Literal["hgb", "ifrs"]
PnlMethod = Literal["gkv", "ukv"]

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
    model_config = {"protected_namespaces": ()}
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


class FiscalYearEnd(BaseModel):
    """The annual closing date convention for every year in an EntitySeries."""

    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)

    @model_validator(mode="after")
    def validate_calendar_day(self) -> "FiscalYearEnd":
        try:
            date(2000, self.month, self.day)
        except ValueError as error:
            raise ValueError("fiscal_year_end must be a valid month/day pair") from error
        return self


# Explicit ISO 4217 codes currently supported by the canonical contract.
# Add a code deliberately when a new user-workbook currency is accepted.
CurrencyCode = Literal["EUR", "GBP", "USD"]
AmountUnit = Literal["EUR", "TEUR"]


class FilingSeriesProvenance(BaseModel):
    """A filing-backed observation must identify both its document and page."""

    kind: Literal["filing"]
    document: str = Field(min_length=1)
    page: int = Field(ge=1)


class UserSuppliedSeriesProvenance(BaseModel):
    """Explicit provenance marker for a value entered from a user workbook."""

    kind: Literal["user_supplied"]


SeriesProvenance = Annotated[
    FilingSeriesProvenance | UserSuppliedSeriesProvenance,
    Field(discriminator="kind"),
]


class LineItemObservation(BaseModel):
    """One complete, source-specific observation for a standardised line item.

    Per-year accounting metadata belongs to ``LineItemPoint`` rather than an
    observation so a Path B series can declare a change without treating it as
    a source conflict.
    """

    value: Decimal
    provenance: SeriesProvenance
    restated: bool


class LineItemConflictResolution(BaseModel):
    """An explicit decision selecting one retained observation from a conflict."""

    chosen_observation_index: int = Field(ge=0)
    reason: str = Field(min_length=1)
    decided_by: str = Field(min_length=1)


class LineItemPoint(BaseModel):
    """All observations for one line item in one fiscal year.

    ``fy`` is the fiscal-year end year: for Seidensticker, ``fy=2025`` means
    the year ended 30 April 2025, not calendar year 2025.

    A point with one observation is unambiguous. A point with two or more
    observations is an unresolved source conflict: each candidate is retained
    with its own provenance, so a producer cannot silently select a value for
    overlapping fiscal years. ``resolution`` is null until an authorised
    decision records the selected observation, rationale, and decision-maker;
    consumers must use that recorded decision rather than inventing a rule.
    """

    fy: int
    unit: AmountUnit
    currency: CurrencyCode
    framework: Framework
    pnl_method: PnlMethod
    presentation_basis: PresentationBasis
    scope_flag: str | None
    method_flag: str | None
    observations: list[LineItemObservation] = Field(min_length=1)
    resolution: LineItemConflictResolution | None

    @model_validator(mode="after")
    def validate_resolution(self) -> "LineItemPoint":
        if self.resolution is not None:
            if len(self.observations) < 2:
                raise ValueError("resolution is only valid for conflicting observations")
            if self.resolution.chosen_observation_index >= len(self.observations):
                raise ValueError("resolution must select an existing observation")
        return self


class LineItemSeries(BaseModel):
    std_id: str = Field(min_length=1)
    points: list[LineItemPoint] = Field(min_length=1)


class EntitySeries(BaseModel):
    """Canonical multi-year financial series, independent of its producer.

    Conflicts are represented by multiple complete ``observations`` in one
    ``LineItemPoint`` rather than a selected value. This preserves overlapping
    filing comparatives and user-workbook values until an explicit resolution.
    """

    entity_id: str = Field(min_length=1)
    source_kind: Literal["filings", "user_workbook", "mixed"]
    fiscal_year_end: FiscalYearEnd
    fiscal_years: list[int] = Field(min_length=1)
    line_items: list[LineItemSeries] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_series(self) -> "EntitySeries":
        if self.fiscal_years != sorted(self.fiscal_years) or len(set(self.fiscal_years)) != len(self.fiscal_years):
            raise ValueError("fiscal_years must be a unique ascending list")

        if len({line_item.std_id for line_item in self.line_items}) != len(self.line_items):
            raise ValueError("line_items must contain each std_id only once")

        provenance_kinds: set[str] = set()
        for line_item in self.line_items:
            point_years = [point.fy for point in line_item.points]
            if point_years != sorted(point_years) or len(set(point_years)) != len(point_years):
                raise ValueError(f"points for {line_item.std_id} must be a unique ascending list")
            if any(year not in self.fiscal_years for year in point_years):
                raise ValueError(f"points for {line_item.std_id} must use declared fiscal_years")
            provenance_kinds.update(
                observation.provenance.kind
                for point in line_item.points
                for observation in point.observations
            )

        expected_kinds = {
            "filings": {"filing"},
            "user_workbook": {"user_supplied"},
            "mixed": {"filing", "user_supplied"},
        }[self.source_kind]
        if provenance_kinds != expected_kinds:
            raise ValueError("source_kind must match the provenance kinds present")
        return self


class ContentBlock(BaseModel):
    id: str
    title: str
    kind: BlockKind
    eligible_slots: list[SlotId]
    earnings_basis: EarningsBasis | None = None
    coverage: float = Field(ge=0, le=1)
    confidence: Confidence
    source: str
    framework: Framework | None = None
    pnl_method: PnlMethod | None = None
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
