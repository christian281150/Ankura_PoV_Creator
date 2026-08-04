"""Tests for py/coverage/probe.py (P6): the coverage probe.

Before this module existed, contract.models.CoverageDimension had zero
producers anywhere in the codebase (confirmed by grep) even though the
frozen Profile.coverage field expects a list of them. These tests exercise
the probe standalone, independent of assemble_profile and of render --
see tests/test_assemble_profile.py for the wiring-level checks that its
output actually reaches Profile.coverage.
"""
from __future__ import annotations

import pytest

from contract.models import CoverageDimension
from coverage.probe import compute_coverage_dimensions


def test_one_dimension_per_block_using_its_own_title_and_coverage() -> None:
    blocks = [
        {"id": "fin.revenue_series", "title": "Revenue in €m", "coverage": 1.0},
        {"id": "bo.business_overview_gap", "title": "Business Overview", "coverage": 0.0},
    ]
    dimensions = compute_coverage_dimensions(blocks)
    assert dimensions == [
        CoverageDimension(label="Revenue in €m", score=1.0),
        CoverageDimension(label="Business Overview", score=0.0),
    ]


def test_preserves_block_order() -> None:
    blocks = [
        {"id": "a", "title": "A", "coverage": 0.2},
        {"id": "b", "title": "B", "coverage": 0.8},
        {"id": "c", "title": "C", "coverage": 0.5},
    ]
    assert [dimension.label for dimension in compute_coverage_dimensions(blocks)] == ["A", "B", "C"]


def test_empty_block_list_yields_no_dimensions() -> None:
    assert compute_coverage_dimensions([]) == []


def test_raises_on_a_block_with_no_title() -> None:
    with pytest.raises(ValueError, match="no title"):
        compute_coverage_dimensions([{"id": "x", "coverage": 0.5}])


def test_raises_on_a_block_with_no_coverage_score() -> None:
    with pytest.raises(ValueError, match="no coverage score"):
        compute_coverage_dimensions([{"id": "x", "title": "X"}])


def test_rejects_a_score_outside_the_frozen_contracts_zero_to_one_bound() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError, from the frozen contract model itself
        compute_coverage_dimensions([{"id": "x", "title": "X", "coverage": 1.5}])
