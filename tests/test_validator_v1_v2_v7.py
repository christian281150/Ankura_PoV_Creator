"""Regression tests for V1 (presentation basis), V2 (mixed units), and V7
(unmapped charted label) -- confirmed firing correctly during P4 reconnaissance,
locked in here so a future change to _assigned_series or the V1/V2/V7 block
can't silently regress them.
"""
from __future__ import annotations

from validate.validator import validate_normalised


def test_v1_flags_revenue_axis_label_with_non_umsatzerloese_basis() -> None:
    result = validate_normalised(
        {"rows": []},
        charted_series=[{"id": "fin.revenue", "presentation_basis": "gesamtleistung"}],
        slot_assignments={"top_left": "fin.revenue"},
        axis_labels={"top_left": "Revenue"},
    )

    flag = next(flag for flag in result.flags if flag.rule == "V1")
    assert flag.severity == "blocking"
    assert flag.message == (
        "series in top_left is labelled 'Revenue' but presentation_basis is "
        "'gesamtleistung', not 'umsatzerloese'."
    )


def test_v1_accepts_revenue_axis_label_with_umsatzerloese_basis() -> None:
    result = validate_normalised(
        {"rows": []},
        charted_series=[{"id": "fin.revenue", "presentation_basis": "umsatzerloese"}],
        slot_assignments={"top_left": "fin.revenue"},
        axis_labels={"top_left": "Revenue"},
    )

    assert not [flag for flag in result.flags if flag.rule == "V1"]


def test_v2_flags_a_charted_series_mixing_units() -> None:
    result = validate_normalised(
        {"rows": []},
        charted_series=[{"id": "fin.metric", "units": ["EUR", "TEUR"]}],
        slot_assignments={"top_left": "fin.metric"},
    )

    flag = next(flag for flag in result.flags if flag.rule == "V2")
    assert flag.severity == "blocking"
    assert flag.message == "series mixes units: EUR, TEUR."


def test_v2_accepts_a_charted_series_with_a_single_unit() -> None:
    result = validate_normalised(
        {"rows": []},
        charted_series=[{"id": "fin.metric", "units": ["EUR"]}],
        slot_assignments={"top_left": "fin.metric"},
    )

    assert not [flag for flag in result.flags if flag.rule == "V2"]


def test_v7_flags_a_charted_series_with_no_std_id() -> None:
    result = validate_normalised(
        {"rows": []},
        charted_series=[{"id": "fin.sonstiges", "raw_label": "Sonstiges"}],
        slot_assignments={"top_left": "fin.sonstiges"},
    )

    flag = next(flag for flag in result.flags if flag.rule == "V7")
    assert flag.severity == "blocking"
    assert flag.message == "Charted series Sonstiges uses unmapped label 'Sonstiges'."


def test_v7_accepts_a_charted_series_with_a_resolved_std_id() -> None:
    result = validate_normalised(
        {"rows": []},
        charted_series=[{"id": "fin.rev", "raw_label": "Umsatzerloese", "std_id": "PL_GKV-1"}],
        slot_assignments={"top_left": "fin.rev"},
    )

    assert not [flag for flag in result.flags if flag.rule == "V7"]
