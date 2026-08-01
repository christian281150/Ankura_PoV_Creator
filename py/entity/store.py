"""Local persistence for register evidence between refreshes.

The store only persists concrete ``RegisterId``-keyed records.  On refresh it
preserves the observed historical evidence instead of replacing it silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import EntityRecord, RegisterId


class JsonEntityStore:
    """A small, dependency-free record store for the unattended register layer."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, register: RegisterId) -> EntityRecord | None:
        return self._records().get(register)

    def upsert(self, incoming: EntityRecord) -> EntityRecord:
        records = self._records()
        prior = records.get(incoming.register)
        merged = self._merge(prior, incoming) if prior is not None else incoming
        records[merged.register] = merged
        self._write(records.values())
        return merged

    def all(self) -> list[EntityRecord]:
        return list(self._records().values())

    def _records(self) -> dict[RegisterId, EntityRecord]:
        if not self._path.exists():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return {
            record.register: record
            for record in (EntityRecord.model_validate(item) for item in payload.get("records", []))
        }

    def _write(self, records: object) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "records": [record.model_dump(mode="json", by_alias=True) for record in records],
        }
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    @staticmethod
    def _merge(prior: EntityRecord, incoming: EntityRecord) -> EntityRecord:
        historical_names = set(prior.historical_names) | set(incoming.historical_names)
        if prior.legal_name != incoming.legal_name:
            historical_names.add(prior.legal_name)
        return incoming.model_copy(
            update={
                "aliases": sorted(set(prior.aliases) | set(incoming.aliases)),
                "historical_names": sorted(historical_names),
                "predecessor_parents": JsonEntityStore._unique_models(
                    [*prior.predecessor_parents, *incoming.predecessor_parents]
                ),
                "shareholder_list_changes": sorted(
                    set(prior.shareholder_list_changes) | set(incoming.shareholder_list_changes)
                ),
                "officer_changes": JsonEntityStore._unique_models([*prior.officer_changes, *incoming.officer_changes]),
                "scope_changes": JsonEntityStore._unique_models([*prior.scope_changes, *incoming.scope_changes]),
                "filings": JsonEntityStore._unique_models([*prior.filings, *incoming.filings]),
            }
        )

    @staticmethod
    def _unique_models(items: list[object]) -> list[object]:
        unique: dict[str, object] = {}
        for item in items:
            key = item.model_dump_json()  # all callers pass Pydantic models
            unique[key] = item
        return list(unique.values())
