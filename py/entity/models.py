"""Pydantic boundary models for entity resolution.

Resolution identities are always register identities.  Names and URLs only
select records returned by a register/web fetcher; they are never identities.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class RegisterType(str, Enum):
    HRA = "HRA"
    HRB = "HRB"


class WarningSeverity(str, Enum):
    ADVISORY = "advisory"
    HARD = "hard"


class RegisterId(BaseModel):
    """The only durable identifier accepted by downstream acquisition."""

    model_config = ConfigDict(frozen=True)

    court: str = Field(min_length=1)
    register_type: RegisterType
    number: str = Field(min_length=1)

    @field_validator("court", "number", mode="before")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @property
    def display(self) -> str:
        return f"{self.register_type.value} {self.number}, AG {self.court}"


class OfficerChange(BaseModel):
    effective_date: date
    officers_added: list[str] = Field(default_factory=list)
    officers_removed: list[str] = Field(default_factory=list)
    source: str


class ScopeChange(BaseModel):
    effective_date: date
    entity: str
    change: str
    source: str


class FilingRecord(BaseModel):
    fiscal_year_end: date
    published_at: date
    statutory_deadline: date | None = None
    source: str

    @property
    def days_late(self) -> int | None:
        if self.statutory_deadline is None:
            return None
        return max(0, (self.published_at - self.statutory_deadline).days)


class ShareholderKind(str, Enum):
    COMPANY = "company"
    NATURAL_PERSON = "natural_person"
    UNKNOWN = "unknown"


class ShareholderEntry(BaseModel):
    """One raw entry from a Gesellschafterliste, with page-level provenance."""

    shareholder_name: str = Field(min_length=1)
    kind: ShareholderKind
    shareholder_register: RegisterId | None = None
    ownership_percent: float | None = Field(default=None, ge=0, le=100)
    source_doc: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def company_entries_need_a_register_identity(self) -> "ShareholderEntry":
        if self.kind is ShareholderKind.COMPANY and self.shareholder_register is None:
            raise ValueError("a company shareholder must carry a register identity")
        if self.kind is ShareholderKind.NATURAL_PERSON and self.shareholder_register is not None:
            raise ValueError("a natural-person shareholder cannot carry a register identity")
        return self


class EntityRecord(BaseModel):
    """A register-backed record supplied by the fetch layer."""

    registry: RegisterId = Field(
        validation_alias=AliasChoices("register", "registry"),
        serialization_alias="register",
    )
    legal_name: str = Field(min_length=1)
    legal_form: str = Field(min_length=1)
    seat: str | None = None
    shareholder_entries: list[ShareholderEntry] = Field(default_factory=list)
    files_konzernabschluss: bool = False
    aliases: list[str] = Field(default_factory=list)
    historical_names: list[str] = Field(default_factory=list)
    predecessor_parents: list[RegisterId] = Field(default_factory=list)
    shareholder_list_changes: list[date] = Field(default_factory=list)
    officer_changes: list[OfficerChange] = Field(default_factory=list)
    scope_changes: list[ScopeChange] = Field(default_factory=list)
    filings: list[FilingRecord] = Field(default_factory=list)

    @property
    def register(self) -> RegisterId:
        """Compatibility view matching the cross-layer JSON contract."""
        return self.registry


class ResolutionWarning(BaseModel):
    code: str
    severity: WarningSeverity
    message: str
    entity: RegisterId | None = None


class ResolutionResult(BaseModel):
    """Human-gated resolution result.  ``target`` is always the top parent."""

    query: str
    discovered: EntityRecord
    target: EntityRecord
    terminal_parent: EntityRecord
    upward_path: list[RegisterId]
    subsidiaries: list[EntityRecord] = Field(default_factory=list)
    warnings: list[ResolutionWarning] = Field(default_factory=list)
    requires_confirmation: bool = True
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_hard_flags(self) -> bool:
        return any(warning.severity is WarningSeverity.HARD for warning in self.warnings)


class ResolutionError(RuntimeError):
    """Raised when an input cannot be resolved safely to one register identity."""
