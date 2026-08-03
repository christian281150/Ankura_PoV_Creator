"""Regression tests for Lane C: py/series reconciles overlapping filing years.

Proving ground: the real FY2024 Seidensticker fixture plus a clearly-labeled
SYNTHETIC FY2025 fixture (tests/fixtures/synthetic_fy2025_seidensticker.json --
hand-built, never a real extraction; see its own "note" field and
docs/final-push-lanes.md). The synthetic fixture deliberately agrees with the
real FY2024 filing on Umsatzerloese and sonstige betriebliche Ertraege, and
deliberately disagrees on Bestandsveraenderung, so both reconciliation paths
are exercised against one pair of fixtures rather than two separate ad hoc
setups.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from contract.models import EntitySeries, FiscalYearEnd
from extractor.consolidate import build_multi_year_tables
from series.reconcile import build_entity_series

FY2024_FIXTURE = Path(__file__).parent / "fixtures" / "seidensticker_extracted_tables.json"
FY2025_SYNTHETIC_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_fy2025_seidensticker.json"

ENTITY_ID = "HRA-8217-AG-Bielefeld"


def _load(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _series() -> EntitySeries:
    fy2024 = build_multi_year_tables(_load(FY2024_FIXTURE))
    fy2025 = build_multi_year_tables(_load(FY2025_SYNTHETIC_FIXTURE))
    return build_entity_series(ENTITY_ID, FiscalYearEnd(month=4, day=30), [fy2024, fy2025])


def _points(series: EntitySeries, std_id: str) -> dict[int, Any]:
    line_item = next(li for li in series.line_items if li.std_id == std_id)
    return {point.fy: point for point in line_item.points}


def test_fiscal_years_span_every_filing() -> None:
    series = _series()
    assert series.fiscal_years == [2023, 2024, 2025]


def test_agreeing_comparative_collapses_to_one_unremarkable_observation() -> None:
    """Umsatzerloese FY2024: stated identically by both filings.

    Two independent sources agreeing on a figure is the ordinary case -- one
    observation, not restated, nothing left to resolve.
    """
    points = _points(_series(), "PL_GKV-1")
    fy2024 = points[2024]
    assert len(fy2024.observations) == 1
    assert fy2024.observations[0].value == Decimal("103152036.57")
    assert fy2024.observations[0].restated is False
    assert fy2024.resolution is None


def test_disagreeing_comparative_is_kept_as_an_unresolved_restatement() -> None:
    """Bestandsveraenderung FY2024: the two filings genuinely disagree.

    Both observations must survive -- this module never discards one to pick
    a winner. The FY2024 filing's own current-year figure is not restated;
    the synthetic FY2025 filing's comparative of the same year is.
    """
    points = _points(_series(), "PL_GKV-2")
    fy2024 = points[2024]
    assert len(fy2024.observations) == 2
    assert fy2024.resolution is None, "a restatement must never be auto-resolved"

    by_value = {obs.value: obs for obs in fy2024.observations}
    assert by_value[Decimal("-8833400.55")].restated is False
    assert by_value[Decimal("-8833400.55")].provenance.document == "Konzernabschluss 2024"
    assert by_value[Decimal("-8800000.00")].restated is True
    assert by_value[Decimal("-8800000.00")].provenance.document == "Konzernabschluss FY2025 (SYNTHETIC)"


def test_a_year_disclosed_by_only_one_filing_is_not_treated_as_restated() -> None:
    """FY2023 (comparative-only, present in the FY2024 filing alone) and
    FY2025 (current-year-only, present in the synthetic filing alone) each
    have a single source -- neither is a restatement, since there is nothing
    to disagree with.
    """
    points = _points(_series(), "PL_GKV-1")
    assert len(points[2023].observations) == 1
    assert points[2023].observations[0].restated is False
    assert len(points[2025].observations) == 1
    assert points[2025].observations[0].restated is False


def test_entity_series_round_trips_through_the_frozen_contract() -> None:
    series = _series()
    round_tripped = EntitySeries.model_validate_json(series.model_dump_json())
    assert round_tripped == series


def test_synthetic_disclaimer_table_never_enters_the_series() -> None:
    """The fixture's own leading disclaimer table must never surface as data."""
    series = _series()
    std_ids = {li.std_id for li in series.line_items}
    assert not any("SYNTHETIC" in std_id.upper() for std_id in std_ids)
