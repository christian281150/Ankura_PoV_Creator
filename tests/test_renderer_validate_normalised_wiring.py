"""Regression tests proving validate_normalised (V1-V10, V12) is actually
wired into the render preflight, not just callable from tests.

Before this, _validate_assignments only ever ran validate_v11 -- every other
rule in validate.validator had no real caller anywhere in the pipeline. These
tests build a profile through the real assemble_profile() (so ``rows`` is
carried forward exactly as production code produces it) and confirm
_validate_assignments both passes a clean profile and actually raises when a
rule is violated, using real data flowing through the real adapter -- not a
hand-rolled mock of the wiring.
"""
from __future__ import annotations

import pytest

from render.assemble_profile import assemble_profile
from render.renderer import RenderError, _validate_assignments


def _normalised(extra_rows: list[dict] | None = None) -> dict:
    return {
        "entity": {"legal_name": "Test GmbH", "fiscal_year_end": "2024-12-31"},
        "rows": [
            {
                "std_id": "PL_GKV-1", "values": {2023: 100.0, 2024: 110.0},
                "unit": "EUR", "presentation_basis": "umsatzerloese",
                "framework": "hgb", "pnl_method": "gkv",
                "provenance": {"doc": "Konzernabschluss FY2024", "page": 1},
                "provenance_by_fy": {
                    2023: {"doc": "Konzernabschluss FY2023", "page": 1},
                    2024: {"doc": "Konzernabschluss FY2024", "page": 1},
                },
            },
            *(extra_rows or ()),
        ],
    }


def test_a_clean_profile_passes_the_wired_preflight_without_raising() -> None:
    profile = assemble_profile(_normalised())
    _validate_assignments(profile, profile["canonical_layout"])  # must not raise


def test_v8_fires_through_the_real_wiring_on_mismatched_aktiva_passiva_rows() -> None:
    """profile['rows'] carries the full normalise-stage row list forward --
    including rows assemble_profile itself never touches (BS-A/BS-P) -- so
    V8 can see them at render-preflight time."""
    profile = assemble_profile(_normalised(extra_rows=[
        {"std_id": "BS-A", "values": {2024: 100.0}},
        {"std_id": "BS-P", "values": {2024: 90.0}},
    ]))

    with pytest.raises(RenderError, match="unresolved validation flags"):
        _validate_assignments(profile, profile["canonical_layout"])


def test_v2_fires_through_the_real_wiring_on_a_block_mixing_units() -> None:
    profile = assemble_profile(_normalised())
    revenue_block = next(block for block in profile["blocks"] if block["id"] == "fin.revenue_series")
    revenue_block["units"] = ["EUR", "TEUR"]

    with pytest.raises(RenderError, match="unresolved validation flags"):
        _validate_assignments(profile, profile["canonical_layout"])
