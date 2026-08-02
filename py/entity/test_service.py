from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from entity.fetch import FixtureEntityFetch
from entity.models import EntityRecord, FilingRecord, RegisterId, RegisterType, ResolutionError, WarningSeverity
from entity.service import EntityResolutionService
from entity.store import JsonEntityStore


class EntityResolutionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = self._service_from_fixture("seidensticker.json")

    @staticmethod
    def _service_from_fixture(name: str) -> EntityResolutionService:
        fixture = json.loads((Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8"))
        records = [EntityRecord.model_validate(record) for record in fixture["records"]]
        lookups = {
            query: [RegisterId.model_validate(register) for register in registers]
            for query, registers in fixture["lookups"].items()
        }
        return EntityResolutionService(FixtureEntityFetch(records, lookups))

    def test_impressum_url_resolves_to_terminal_hra_group(self) -> None:
        result = self.service.resolve("seidensticker.com")

        self.assertEqual(result.target.register.court, "Bielefeld")
        self.assertEqual(result.target.register.register_type, RegisterType.HRA)
        self.assertEqual(result.target.register.number, "8217")
        self.assertEqual(result.discovered.legal_name, "TK Store-Management GmbH")
        self.assertEqual(result.discovered.register.number, "39109")
        self.assertIn("TK Store-Management GmbH", [entity.legal_name for entity in result.subsidiaries])
        self.assertTrue(any(warning.code == "IMPRESSUM_ENTITY_NOT_GROUP" for warning in result.warnings))
        self.assertTrue(result.requires_confirmation)

    def test_rejects_unknown_lookup(self) -> None:
        with self.assertRaises(ResolutionError):
            self.service.resolve("unknown.example")

    def test_refuses_name_with_two_register_candidates(self) -> None:
        ambiguous = self._service_from_fixture("ambiguous_name.json")
        with self.assertRaises(ResolutionError):
            ambiguous.resolve("example gmbh")

    def test_natural_person_shareholder_produces_no_parent(self) -> None:
        result = self._service_from_fixture("natural_person_parentless.json").resolve("familienbetrieb")
        self.assertEqual(result.target.register, result.discovered.register)
        self.assertEqual(len(result.upward_path), 1)

    def test_hrb_consolidated_filer_under_hra_parent_is_hard_flag(self) -> None:
        result = self._service_from_fixture("hrb_consolidated_filer_under_hra.json").resolve("wrong.example")
        flags = [warning for warning in result.warnings if warning.severity is WarningSeverity.HARD]
        self.assertIn("CONSOLIDATED_FILER_PARENT_MISMATCH", [warning.code for warning in flags])

    def test_store_preserves_renamed_entity_history_and_filing_lateness(self) -> None:
        original = self.service.resolve("textilkontor walter seidensticker gmbh & co. kg").target
        refreshed = EntityRecord.model_validate(
            {
                **original.model_dump(),
                "legal_name": "Textilkontor Seidensticker GmbH & Co. KG",
                "filings": [
                    FilingRecord(
                        fiscal_year_end=date(2025, 4, 30),
                        published_at=date(2026, 3, 15),
                        statutory_deadline=date(2026, 2, 28),
                        source="fixture",
                    )
                ],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            store = JsonEntityStore(Path(directory) / "entities.json")
            store.upsert(original)
            saved = store.upsert(refreshed)

        self.assertIn(original.legal_name, saved.historical_names)
        self.assertEqual(saved.filings[0].days_late, 15)


if __name__ == "__main__":
    unittest.main()
