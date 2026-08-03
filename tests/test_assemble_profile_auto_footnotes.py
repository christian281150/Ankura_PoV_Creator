"""Regression tests for assemble_profile.auto_footnote_flags: the missing
link between validate_normalised() and assemble_profile()'s existing
validation_flags parameter.

Before this, nothing computed validate_normalised() output before calling
assemble_profile(), so AGENTS.md's stated design ("Notes written against
V3-V6 become slide footnotes automatically") had no real path to it --
assemble_profile's own docstring is explicit that it never computes flags
itself, so the caller (its own CLI main(), the only real non-test caller)
must.
"""
from __future__ import annotations

from render.assemble_profile import assemble_profile, auto_footnote_flags

REVENUE_ROW = {
    "std_id": "PL_GKV-1", "raw_label": "Umsatzerloese", "values": {2023: 100_000_000.0, 2024: 110_000_000.0},
    "unit": "EUR", "presentation_basis": "umsatzerloese", "framework": "hgb", "pnl_method": "gkv",
    "provenance": {"doc": "Konzernabschluss FY2024", "page": 1},
    "provenance_by_fy": {2023: {"doc": "Konzernabschluss FY2023", "page": 1}, 2024: {"doc": "Konzernabschluss FY2024", "page": 1}},
}


def _normalised(*extra_rows: dict) -> dict:
    return {
        "entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"},
        "rows": [REVENUE_ROW, *extra_rows],
    }


def test_auto_footnote_flags_is_empty_when_nothing_fires() -> None:
    assert auto_footnote_flags(_normalised()) == []


def test_auto_footnote_flags_surfaces_a_real_v6_cost_ratio_break() -> None:
    cost_row = {"std_id": "PL_GKV-5", "raw_label": "Materialaufwand", "values": {2023: 40_000_000.0, 2024: 50_000_000.0}}
    flags = auto_footnote_flags(_normalised(cost_row))

    flag = next(flag for flag in flags if flag["rule"] == "V6")
    assert flag["note"] == "Explain the cost-ratio trend break."


def test_auto_footnote_flags_excludes_rules_outside_v3_to_v6() -> None:
    """V9 (negative equity) has a real, correctly-firing signal here but no
    note and isn't in the auto-footnote set -- it must not leak into the
    revenue block's footnotes just because it fired in the same validation
    pass."""
    negeq_row = {"std_id": "BS-P-NEGEQ", "raw_label": "Verlustanteile der Kommanditisten", "values": {2024: 500.0}}
    flags = auto_footnote_flags(_normalised(negeq_row))

    assert not any(flag["rule"] == "V9" for flag in flags)


def test_the_v6_note_reaches_the_revenue_block_as_a_real_footnote() -> None:
    """End-to-end proof: auto_footnote_flags feeding assemble_profile's
    existing validation_flags parameter actually produces a footnote on the
    rendered block, not just a flag sitting unused somewhere."""
    cost_row = {"std_id": "PL_GKV-5", "raw_label": "Materialaufwand", "values": {2023: 40_000_000.0, 2024: 50_000_000.0}}
    normalised = _normalised(cost_row)

    profile = assemble_profile(normalised, None, auto_footnote_flags(normalised))
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")

    assert "Explain the cost-ratio trend break." in revenue_block["footnotes_auto"]
