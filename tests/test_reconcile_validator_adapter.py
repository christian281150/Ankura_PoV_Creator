"""Regression tests for entity_series_to_rows: the adapter that lets V3/V4
actually receive scope_by_fy/method_by_fy-shaped data. Before this, nothing
in the pipeline produced that year-keyed shape -- LineItemPoint already
carries scope_flag/method_flag, but only per-point, never collected into the
dict form validate_normalised reads.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from contract.models import (
    EntitySeries,
    FilingSeriesProvenance,
    FiscalYearEnd,
    LineItemConflictResolution,
    LineItemObservation,
    LineItemPoint,
    LineItemSeries,
)
from extractor.consolidate import build_multi_year_tables
from series.reconcile import build_entity_series, entity_series_to_rows
from validate.validator import validate_normalised

FY2024_FIXTURE = Path(__file__).parent / "fixtures" / "seidensticker_extracted_tables.json"
FY2025_SYNTHETIC_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_fy2025_seidensticker.json"


def _observation(value: str, restated: bool = False) -> LineItemObservation:
    return LineItemObservation(
        value=Decimal(value),
        provenance=FilingSeriesProvenance(kind="filing", document="Konzernabschluss FY2024", page=1),
        restated=restated,
    )


def _point(fy: int, pnl_method: str, observations: list[LineItemObservation], resolution: LineItemConflictResolution | None = None) -> LineItemPoint:
    return LineItemPoint(
        fy=fy, unit="EUR", currency="EUR", framework="hgb", pnl_method=pnl_method,
        presentation_basis="umsatzerloese", scope_flag="consolidated", method_flag=pnl_method.upper(),
        observations=observations, resolution=resolution,
    )


def test_method_change_between_years_survives_into_method_by_fy() -> None:
    series = EntitySeries(
        entity_id="test-entity", source_kind="filings", fiscal_year_end=FiscalYearEnd(month=4, day=30),
        fiscal_years=[2023, 2024],
        line_items=[LineItemSeries(std_id="PL_GKV-1", points=[
            _point(2023, "ukv", [_observation("100.00")]),
            _point(2024, "gkv", [_observation("110.00")]),
        ])],
    )

    rows = entity_series_to_rows(series)
    assert rows == [{
        "std_id": "PL_GKV-1",
        "values": {2023: 100.0, 2024: 110.0},
        "scope_by_fy": {2023: "consolidated", 2024: "consolidated"},
        "method_by_fy": {2023: "UKV", 2024: "GKV"},
    }]

    result = validate_normalised({"rows": rows})
    flag = next(flag for flag in result.flags if flag.rule == "V4")
    assert flag.note == "Explain the GKV/UKV method change and comparability impact."


def test_an_unresolved_conflicting_year_is_left_out_of_the_row_rather_than_guessed() -> None:
    series = EntitySeries(
        entity_id="test-entity", source_kind="filings", fiscal_year_end=FiscalYearEnd(month=4, day=30),
        fiscal_years=[2023, 2024],
        line_items=[LineItemSeries(std_id="PL_GKV-2", points=[
            _point(2023, "gkv", [_observation("50.00")]),
            _point(2024, "gkv", [_observation("-8833400.55", restated=False), _observation("-8800000.00", restated=True)]),
        ])],
    )

    rows = entity_series_to_rows(series)
    row = next(row for row in rows if row["std_id"] == "PL_GKV-2")
    assert row["values"] == {2023: 50.0}, "the disputed FY2024 year must not appear with a guessed value"


def test_a_resolved_conflict_uses_the_chosen_observation() -> None:
    resolution = LineItemConflictResolution(chosen_observation_index=1, reason="Analyst confirmed the restated figure.", decided_by="C. Wolf")
    series = EntitySeries(
        entity_id="test-entity", source_kind="filings", fiscal_year_end=FiscalYearEnd(month=4, day=30),
        fiscal_years=[2024],
        line_items=[LineItemSeries(std_id="PL_GKV-2", points=[
            _point(2024, "gkv", [_observation("-8833400.55", restated=False), _observation("-8800000.00", restated=True)], resolution=resolution),
        ])],
    )

    rows = entity_series_to_rows(series)
    row = next(row for row in rows if row["std_id"] == "PL_GKV-2")
    assert row["values"] == {2024: -8800000.00}


def test_adapter_output_from_the_real_reconciled_fixture_pair_is_validator_ready() -> None:
    """End-to-end shape proof against the real Lane C fixture pair, not just
    a hand-built series -- confirms the adapter works on genuine
    build_entity_series output, including its one real unresolved
    restatement (PL_GKV-2 FY2024, see test_series_reconcile.py)."""
    fy2024 = build_multi_year_tables(json.loads(FY2024_FIXTURE.read_text(encoding="utf-8-sig")))
    fy2025 = build_multi_year_tables(json.loads(FY2025_SYNTHETIC_FIXTURE.read_text(encoding="utf-8-sig")))
    series = build_entity_series("HRA-8217-AG-Bielefeld", FiscalYearEnd(month=4, day=30), [fy2024, fy2025])

    rows = entity_series_to_rows(series)
    result = validate_normalised({"rows": rows})
    assert isinstance(result.flags, list)  # runs cleanly against real data; V3/V4 firing depends on real variation

    disputed_row = next(row for row in rows if row["std_id"] == "PL_GKV-2")
    assert 2024 not in disputed_row["values"], "the real unresolved restatement must not leak a guessed value"
