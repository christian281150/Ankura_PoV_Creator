"""Fetch boundary for register and targeted website evidence.

Production can implement this protocol with a no-CAPTCHA registry source.  The
resolver itself makes no network calls, and tests use ``FixtureEntityFetch``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import EntityRecord, RegisterId


class EntityFetch(Protocol):
    def lookup(self, query: str) -> list[RegisterId]:
        """Return register-backed candidates for an exact input lookup."""

    def get(self, register: RegisterId) -> EntityRecord | None:
        """Return the concrete registry record, or None if unavailable."""

    def children_of(self, register: RegisterId) -> Iterable[EntityRecord]:
        """Return known direct subsidiaries for a resolved parent."""


class FixtureEntityFetch:
    """In-memory deterministic fetcher suitable for fixture and contract tests."""

    def __init__(self, records: Iterable[EntityRecord], lookups: dict[str, list[RegisterId]]) -> None:
        self._records = {record.register: record for record in records}
        self._lookups = {self._normalise(query): values for query, values in lookups.items()}

    def lookup(self, query: str) -> list[RegisterId]:
        return list(self._lookups.get(self._normalise(query), []))

    def get(self, register: RegisterId) -> EntityRecord | None:
        return self._records.get(register)

    def children_of(self, register: RegisterId) -> Iterable[EntityRecord]:
        return [record for record in self._records.values() if record.parent_register == register]

    @staticmethod
    def _normalise(query: str) -> str:
        return query.strip().lower().rstrip("/")
