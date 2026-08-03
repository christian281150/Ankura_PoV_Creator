"""Regression tests for V3 (perimeter change), V4 (GKV/UKV method change), V5
(material YoY movement) and V6 (cost-ratio break) -- each confirmed firing
correctly during Step 2(c) reconnaissance against synthetic input shaped
exactly as validate_normalised expects.

These prove the rule logic itself is correct. They do NOT prove these rules
fire against real pipeline output -- see the P4 reconnaissance notes: V3/V4
need a ``scope_by_fy``/``method_by_fy`` dict on each row, which nothing in
consolidate.py or series/reconcile.py currently produces (reconcile.py sets a
single per-point ``scope_flag``/``method_flag``, not a year-keyed dict), so
in practice V3/V4 do not fire on real data today regardless of whether a
real perimeter or method change occurred.
"""
from __future__ import annotations

from validate.validator import validate_normalised


def test_v3_flags_a_consolidation_perimeter_change_between_consecutive_years() -> None:
    result = validate_normalised({"rows": [{
        "std_id": "PL_GKV-1", "raw_label": "Umsatzerloese",
        "values": {2023: 100.0, 2024: 110.0},
        "scope_by_fy": {2023: "standalone", 2024: "consolidated"},
    }]})

    flag = next(flag for flag in result.flags if flag.rule == "V3")
    assert flag.severity == "note_required"
    assert flag.note == "Explain the perimeter change and comparability impact."


def test_v3_accepts_an_unchanged_consolidation_perimeter() -> None:
    result = validate_normalised({"rows": [{
        "std_id": "PL_GKV-1", "raw_label": "Umsatzerloese",
        "values": {2023: 100.0, 2024: 110.0},
        "scope_by_fy": {2023: "consolidated", 2024: "consolidated"},
    }]})

    assert not [flag for flag in result.flags if flag.rule == "V3"]


def test_v4_flags_a_gkv_ukv_method_change_between_consecutive_years() -> None:
    result = validate_normalised({"rows": [{
        "std_id": "PL_GKV-1", "raw_label": "Umsatzerloese",
        "values": {2023: 100.0, 2024: 110.0},
        "method_by_fy": {2023: "ukv", 2024: "gkv"},
    }]})

    flag = next(flag for flag in result.flags if flag.rule == "V4")
    assert flag.severity == "note_required"
    assert flag.note == "Explain the GKV/UKV method change and comparability impact."


def test_v4_accepts_an_unchanged_method() -> None:
    result = validate_normalised({"rows": [{
        "std_id": "PL_GKV-1", "raw_label": "Umsatzerloese",
        "values": {2023: 100.0, 2024: 110.0},
        "method_by_fy": {2023: "gkv", 2024: "gkv"},
    }]})

    assert not [flag for flag in result.flags if flag.rule == "V4"]


def test_v5_flags_a_material_yoy_movement_on_a_slot_assigned_line() -> None:
    result = validate_normalised(
        {"rows": [{"std_id": "PL_GKV-5", "raw_label": "Materialaufwand",
                    "values": {2023: 10_000_000.0, 2024: 13_000_000.0}}]},
        charted_series=[{"id": "fin.material", "std_id": "PL_GKV-5", "raw_label": "Materialaufwand"}],
        slot_assignments={"top_left": "fin.material"},
    )

    flag = next(flag for flag in result.flags if flag.rule == "V5")
    assert flag.severity == "note_required"
    assert flag.message == "Materialaufwand: FY2024 changed +30.0% versus FY2023 (+3,000,000.00 EUR)."


def test_v5_accepts_a_below_threshold_movement() -> None:
    result = validate_normalised(
        {"rows": [{"std_id": "PL_GKV-5", "raw_label": "Materialaufwand",
                    "values": {2023: 10_000_000.0, 2024: 10_200_000.0}}]},
        charted_series=[{"id": "fin.material", "std_id": "PL_GKV-5", "raw_label": "Materialaufwand"}],
        slot_assignments={"top_left": "fin.material"},
    )

    assert not [flag for flag in result.flags if flag.rule == "V5"]


def test_v6_flags_a_cost_ratio_break_against_revenue() -> None:
    result = validate_normalised({"rows": [
        {"std_id": "PL_GKV-1", "raw_label": "Umsatzerloese", "values": {2023: 100_000_000.0, 2024: 100_000_000.0}},
        {"std_id": "PL_GKV-5", "raw_label": "Materialaufwand", "values": {2023: 40_000_000.0, 2024: 50_000_000.0}},
    ]})

    flag = next(flag for flag in result.flags if flag.rule == "V6")
    assert flag.severity == "note_required"
    assert flag.message == "Materialaufwand: cost ratio changed +10.0pp from FY2023 to FY2024."


def test_v6_accepts_a_below_threshold_ratio_change() -> None:
    result = validate_normalised({"rows": [
        {"std_id": "PL_GKV-1", "raw_label": "Umsatzerloese", "values": {2023: 100_000_000.0, 2024: 100_000_000.0}},
        {"std_id": "PL_GKV-5", "raw_label": "Materialaufwand", "values": {2023: 40_000_000.0, 2024: 41_000_000.0}},
    ]})

    assert not [flag for flag in result.flags if flag.rule == "V6"]
