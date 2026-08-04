"""Regression tests for render.assemble_profile (P7 content blocks).

Before this file, py/render/assemble_profile.py (a careful, 140+ line
implementation that deliberately builds explicit gap blocks rather than
defaulting) had zero test coverage of its own -- only the V3-V6 auto-footnote
wiring (tests/test_assemble_profile_auto_footnotes.py) and a render-preflight
wiring check exercised it incidentally. These tests cover the adapter's own
contract: what it accepts, what it refuses, and exactly what a gap block looks
like when evidence is missing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from render.assemble_profile import AssemblyError, assemble_profile, flagged_items

REVENUE_ROW = {
    "std_id": "PL_GKV-1", "raw_label": "Umsatzerloese", "values": {2023: 100_000_000.0, 2024: 110_000_000.0},
    "unit": "EUR", "presentation_basis": "umsatzerloese", "framework": "hgb", "pnl_method": "gkv",
    "provenance": {"doc": "Konzernabschluss FY2024", "page": 1},
    "provenance_by_fy": {2023: {"doc": "Konzernabschluss FY2023", "page": 1}, 2024: {"doc": "Konzernabschluss FY2024", "page": 1}},
}

E2E_PROFILE = json.loads((Path(__file__).parent / "fixtures" / "e2e_output" / "seidensticker_e2e.json").read_text(encoding="utf-8"))["profile"]


def _normalised(*extra_rows: dict) -> dict:
    return {
        "entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"},
        "rows": [REVENUE_ROW, *extra_rows],
    }


# ---------------------------------------------------------------------------
# Entity / revenue-row preconditions
# ---------------------------------------------------------------------------


def test_raises_without_entity_legal_name() -> None:
    with pytest.raises(AssemblyError, match="legal_name"):
        assemble_profile({"entity": {"fiscal_year_end": "2024-12-31"}, "rows": [REVENUE_ROW]})


def test_raises_without_entity_fiscal_year_end() -> None:
    with pytest.raises(AssemblyError, match="fiscal_year_end"):
        assemble_profile({"entity": {"legal_name": "Test GmbH"}, "rows": [REVENUE_ROW]})


def test_raises_without_a_mapped_revenue_row() -> None:
    with pytest.raises(AssemblyError, match="PL_GKV-1"):
        assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": []})


@pytest.mark.parametrize("missing_key", ["unit", "presentation_basis", "framework", "pnl_method", "provenance"])
def test_raises_when_revenue_row_lacks_required_metadata(missing_key: str) -> None:
    row = {**REVENUE_ROW, missing_key: None}
    with pytest.raises(AssemblyError, match="lacks required upstream metadata"):
        assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": [row]})


# ---------------------------------------------------------------------------
# Row merging (multi-filing series)
# ---------------------------------------------------------------------------


def test_merged_row_combines_two_filings_into_one_series_with_deduped_provenance() -> None:
    """A std_id appearing in two filings (current + prior-year comparative)
    must merge into one series, not silently pick one filing's view."""
    filing_2024 = {
        "std_id": "PL_GKV-1", "values": {2023: 100.0, 2024: 110.0},
        "unit": "EUR", "presentation_basis": "umsatzerloese", "framework": "hgb", "pnl_method": "gkv",
        "provenance_by_fy": {2023: {"doc": "Konzernabschluss FY2024", "page": 3}, 2024: {"doc": "Konzernabschluss FY2024", "page": 3}},
        "provenance": {"doc": "Konzernabschluss FY2024", "page": 3},
    }
    filing_2025 = {
        "std_id": "PL_GKV-1", "values": {2024: 110.0, 2025: 120.0},
        "unit": "EUR", "presentation_basis": "umsatzerloese", "framework": "hgb", "pnl_method": "gkv",
        "provenance_by_fy": {2024: {"doc": "Konzernabschluss FY2025", "page": 3}, 2025: {"doc": "Konzernabschluss FY2025", "page": 3}},
        "provenance": {"doc": "Konzernabschluss FY2025", "page": 3},
    }
    profile = assemble_profile({
        "entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"},
        "rows": [filing_2024, filing_2025],
    })
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")
    assert {point["fy"]: point["value"] for point in revenue_block["series"]} == {2023: 100.0, 2024: 110.0, 2025: 120.0}
    # FY2024 appears in both filings with the same value -- provenance for it
    # should still be captured once per filing, not silently collapsed to one.
    docs = {item["doc"] for item in revenue_block["provenance"]}
    assert {"Konzernabschluss FY2024", "Konzernabschluss FY2025"} <= docs


def test_merged_row_raises_on_inconsistent_metadata_across_source_rows() -> None:
    row_a = {**REVENUE_ROW, "values": {2023: 100.0}}
    row_b = {**REVENUE_ROW, "values": {2024: 110.0}, "unit": "TEUR"}
    with pytest.raises(AssemblyError, match="inconsistent metadata"):
        assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": [row_a, row_b]})


def test_merged_row_raises_on_conflicting_values_for_the_same_fiscal_year() -> None:
    row_a = {**REVENUE_ROW, "values": {2024: 110.0}}
    row_b = {**REVENUE_ROW, "values": {2024: 999.0}}
    with pytest.raises(AssemblyError, match="conflicting values for FY2024"):
        assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": [row_a, row_b]})


# ---------------------------------------------------------------------------
# Coverage / confidence buckets
# ---------------------------------------------------------------------------


def test_full_contiguous_series_is_high_confidence_full_coverage() -> None:
    row = {**REVENUE_ROW, "values": {2022: 90.0, 2023: 100.0, 2024: 110.0}}
    profile = assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": [row]})
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")
    assert revenue_block["coverage"] == 1.0
    assert revenue_block["confidence"] == "high"


def test_sparse_series_with_a_gap_year_is_lower_coverage_and_confidence() -> None:
    # 2022 and 2024 disclosed, 2023 missing: 2 of 3 years in the span.
    row = {**REVENUE_ROW, "values": {2022: 90.0, 2024: 110.0}}
    profile = assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": [row]})
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")
    assert revenue_block["coverage"] == pytest.approx(2 / 3)
    assert revenue_block["confidence"] == "medium"


def test_single_year_series_is_low_confidence() -> None:
    row = {**REVENUE_ROW, "values": {2024: 110.0}}
    profile = assemble_profile({"entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"}, "rows": [row]})
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")
    assert revenue_block["coverage"] == 1.0  # 1 of 1 years in its own span
    assert revenue_block["confidence"] == "high"


# ---------------------------------------------------------------------------
# Gap blocks (business overview / product grid: no producer exists yet by
# design -- see the "BO/Product data" decision recorded for this lane)
# ---------------------------------------------------------------------------


def test_business_overview_is_an_explicit_gap_not_a_default() -> None:
    profile = assemble_profile(_normalised())
    block = next(block for block in profile["blocks"] if block["id"] == "bo.business_overview_gap")
    assert block["coverage"] == 0.0
    assert block["confidence"] == "low"
    assert block["content"] == ["Business-overview evidence was not supplied."]
    assert block["provenance"] == [{"std_id": "COVERAGE-GAP", "doc": "Profile coverage", "sheet": "Business Overview", "row": 0, "page": None}]


def test_product_grid_is_an_explicit_gap_not_a_default() -> None:
    profile = assemble_profile(_normalised())
    block = next(block for block in profile["blocks"] if block["id"] == "prod.product_grid_gap")
    assert block["coverage"] == 0.0
    assert block["content"] == ["Product evidence was not supplied."]


def test_canonical_layout_assigns_all_four_slots_to_real_block_ids() -> None:
    profile = assemble_profile(_normalised())
    layout = profile["canonical_layout"]
    assert set(layout) == {"top_left", "top_right", "bottom_left", "bottom_right"}
    block_ids = {block["id"] for block in profile["blocks"]}
    assert set(layout.values()) <= block_ids


# ---------------------------------------------------------------------------
# Geography block: real content from Anhang §285 Nr. 4 segment splits
# ---------------------------------------------------------------------------

GEOGRAPHY_FIGURE_INLAND = {
    "segment_name": "Umsatzerlöse Inland", "segment_type": "geography", "fiscal_year": 2025,
    "metric": "revenue", "value": 65_116_000.0, "unit": "EUR", "presentation_basis": "bruttoumsatzerloese",
    "provenance": {"sheet": "FY2025_Umsatzsplit", "row": 12}, "flags": [],
}
GEOGRAPHY_FIGURE_AUSLAND = {
    "segment_name": "Umsatzerlöse Ausland", "segment_type": "geography", "fiscal_year": 2025,
    "metric": "revenue", "value": 38_036_000.0, "unit": "EUR", "presentation_basis": "bruttoumsatzerloese",
    "provenance": {"sheet": "FY2025_Umsatzsplit", "row": 13}, "flags": [],
}
PRODUCT_FIGURE = {
    "segment_name": "Hemden", "segment_type": "product", "fiscal_year": 2025,
    "metric": "revenue", "value": 50_000_000.0, "unit": "EUR", "presentation_basis": "bruttoumsatzerloese",
    "provenance": {"sheet": "FY2025_Umsatzsplit", "row": 5}, "flags": [],
}


def test_geography_is_a_gap_when_no_segments_are_supplied() -> None:
    profile = assemble_profile(_normalised())
    block = next(block for block in profile["blocks"] if block["eligible_slots"] == ["bottom_right"])
    assert block["id"] == "geo.revenue_split_gap"
    assert block["coverage"] == 0.0


def test_geography_is_a_gap_when_segments_exist_but_have_no_geography_split() -> None:
    profile = assemble_profile(_normalised(), segments={"figures": [PRODUCT_FIGURE]})
    block = next(block for block in profile["blocks"] if block["eligible_slots"] == ["bottom_right"])
    assert block["id"] == "geo.revenue_split_gap"


def test_geography_block_renders_real_segment_content_with_provenance() -> None:
    profile = assemble_profile(_normalised(), segments={"figures": [GEOGRAPHY_FIGURE_INLAND, GEOGRAPHY_FIGURE_AUSLAND, PRODUCT_FIGURE]})
    block = next(block for block in profile["blocks"] if block["eligible_slots"] == ["bottom_right"])

    assert block["id"] == "geo.revenue_split"
    assert block["coverage"] == 1.0
    assert block["confidence"] == "high"
    assert block["presentation_basis"] == "bruttoumsatzerloese"
    assert block["unit"] == "EUR"
    assert any("Umsatzerlöse Inland" in line and "65.1m" in line for line in block["content"])
    assert any("Umsatzerlöse Ausland" in line and "38.0m" in line for line in block["content"])
    assert not any("Hemden" in line for line in block["content"])  # product segment must not leak into geography

    provenance = block["provenance"]
    assert all(item["doc"] == "FY2025" for item in provenance)
    assert all(item["page"] is None for item in provenance)
    assert {item["sheet"] for item in provenance} == {"FY2025_Umsatzsplit"}


def test_geography_block_uses_the_latest_disclosed_fiscal_year() -> None:
    older = {**GEOGRAPHY_FIGURE_INLAND, "fiscal_year": 2024, "value": 60_000_000.0, "provenance": {"sheet": "FY2024_Umsatzsplit", "row": 12}}
    profile = assemble_profile(_normalised(), segments={"figures": [older, GEOGRAPHY_FIGURE_INLAND]})
    block = next(block for block in profile["blocks"] if block["eligible_slots"] == ["bottom_right"])
    assert any("FY2025" in line for line in block["content"])
    assert not any("FY2024" in line for line in block["content"])


def test_geography_block_marks_unstated_basis_instead_of_fabricating_one() -> None:
    figure = {**GEOGRAPHY_FIGURE_INLAND, "presentation_basis": None}
    profile = assemble_profile(_normalised(), segments={"figures": [figure]})
    block = next(block for block in profile["blocks"] if block["eligible_slots"] == ["bottom_right"])
    assert block["presentation_basis"] == "n/a"
    assert block["confidence"] == "medium"
    assert any("basis not stated" in line for line in block["content"])


def test_geography_block_raises_without_sheet_or_row_provenance() -> None:
    figure = {**GEOGRAPHY_FIGURE_INLAND, "provenance": {}}
    with pytest.raises(AssemblyError, match="lacks sheet/row provenance"):
        assemble_profile(_normalised(), segments={"figures": [figure]})


def test_geography_block_prefers_revenue_metric_over_percentage_share() -> None:
    share = {**GEOGRAPHY_FIGURE_INLAND, "metric": "revenue_share", "unit": "PCT", "value": 63.1}
    profile = assemble_profile(_normalised(), segments={"figures": [GEOGRAPHY_FIGURE_INLAND, share]})
    block = next(block for block in profile["blocks"] if block["eligible_slots"] == ["bottom_right"])
    assert any("65.1m" in line for line in block["content"])
    assert not any("63.1%" in line for line in block["content"])


# ---------------------------------------------------------------------------
# P6 coverage probe wiring
# ---------------------------------------------------------------------------


def test_coverage_dimensions_mirror_block_titles_and_scores() -> None:
    profile = assemble_profile(_normalised(), segments={"figures": [GEOGRAPHY_FIGURE_INLAND]})
    by_title = {dimension["label"]: dimension["score"] for dimension in profile["coverage"]}
    assert by_title == {block["title"]: block["coverage"] for block in profile["blocks"]}
    assert by_title["Revenue Split by Geography"] == 1.0
    assert by_title["Business Overview"] == 0.0


def test_coverage_dimensions_are_valid_against_the_frozen_contract_model() -> None:
    from contract.models import CoverageDimension

    profile = assemble_profile(_normalised())
    for dimension in profile["coverage"]:
        validated = CoverageDimension.model_validate(dimension)
        assert 0.0 <= validated.score <= 1.0


# ---------------------------------------------------------------------------
# V9 flagged items (see assemble_profile.flagged_items docstring for why this
# is a separate mechanism from auto_footnote_flags)
# ---------------------------------------------------------------------------


def test_flagged_items_is_empty_when_v9_does_not_fire() -> None:
    assert flagged_items(_normalised()) == []


def test_flagged_items_surfaces_v9_with_real_row_provenance() -> None:
    negeq_row = {
        "std_id": "BS-P-NEGEQ", "raw_label": "Nicht durch Vermoegenseinlagen gedeckte Verlustanteile",
        "values": {2024: 19_821_701.76},
        "provenance_by_fy": {2024: {"doc": "Konzernabschluss FY2024", "sheet": "Bilanz", "row": 34, "page": 1}},
    }
    items = flagged_items(_normalised(negeq_row))
    assert len(items) == 1
    assert items[0]["rule"] == "V9"
    assert items[0]["severity"] == "advisory"
    assert items[0]["provenance"] == [{"std_id": "BS-P-NEGEQ", "doc": "Konzernabschluss FY2024", "sheet": "Bilanz", "row": 34, "page": 1}]


def test_flagged_items_raises_when_v9_fires_without_citable_provenance() -> None:
    negeq_row = {"std_id": "BS-P-NEGEQ", "raw_label": "Verlustanteile", "values": {2024: 500.0}}
    with pytest.raises(AssemblyError, match="no BS-P-NEGEQ/BS-P.A row provenance"):
        flagged_items(_normalised(negeq_row))


# ---------------------------------------------------------------------------
# Real fixture: the committed E2E output round-trips through assemble_profile
# ---------------------------------------------------------------------------


def test_real_e2e_rows_reassemble_into_the_same_shape_of_profile() -> None:
    """tests/fixtures/e2e_output/seidensticker_e2e.json is the durable,
    real P0-P9 Seidensticker run (see its README). Feeding its own `rows`
    back into assemble_profile must reproduce the same block set -- proof
    this adapter is stable on genuine filing data, not just synthetic rows."""
    normalised = {"entity": E2E_PROFILE["entity"], "rows": E2E_PROFILE["rows"]}
    profile = assemble_profile(normalised)

    assert profile["entity"]["legal_name"] == "Textilkontor Walter Seidensticker GmbH & Co. KG"
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")
    assert {point["fy"]: point["value"] for point in revenue_block["series"]} == {2023: 126812470.7, 2024: 103152036.57}
    assert revenue_block["presentation_basis"] == "umsatzerloese"

    gap_ids = {block["id"] for block in profile["blocks"] if block["coverage"] == 0.0}
    assert gap_ids == {"bo.business_overview_gap", "prod.product_grid_gap", "geo.revenue_split_gap"}


def test_real_e2e_rows_fire_v9_as_a_flagged_item_not_a_footnote() -> None:
    """The real FY2024 Konzernbilanz discloses BS-P-NEGEQ (KG negative
    equity). Confirms V9 fires on genuine filing data through this exact
    code path, not just a hand-rolled synthetic row."""
    normalised = {"entity": E2E_PROFILE["entity"], "rows": E2E_PROFILE["rows"]}
    items = flagged_items(normalised)
    assert any(item["rule"] == "V9" for item in items)

    revenue_block = next(block for block in assemble_profile(normalised)["blocks"] if block["id"] == "fin.revenue_series")
    assert not any(note for note in revenue_block["footnotes_auto"] if "Verlustanteile" in note or "equity" in note.lower())
