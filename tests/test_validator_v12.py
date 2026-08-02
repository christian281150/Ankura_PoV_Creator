from validate.validator import validate_normalised, validate_v12


REQUIRED_NOTE = "Confirm PL_GKV-7b is absent from Konzernabschluss FY2024, or map it."


def _ebitda(*, footnotes_auto: list[str] | None = None) -> dict[str, object]:
    return {
        "id": "fin.ebitda",
        "title": "EBITDA",
        "earnings_basis": "reported",
        "values": {2024: 10_000_000},
        "footnotes_auto": footnotes_auto or [],
    }


def _filing_with_unmapped_7b() -> dict[str, object]:
    return {
        "rows": [
            {
                "std_id": "PL_GKV-7a",
                "values": {2024: -2_000_000},
                "provenance_by_fy": {2024: {"doc": "Konzernabschluss FY2024", "sheet": "GuV", "row": 12}},
            },
            {"std_id": None, "raw_label": "Abschreibungen auf Vermögensgegenstände des Umlaufvermögens", "values": {2024: -500_000}},
        ],
    }


def test_v12_fails_closed_when_7b_is_unmapped_in_a_filing_reporting_both_children() -> None:
    result = validate_normalised(
        _filing_with_unmapped_7b(), charted_series=[_ebitda()], slot_assignments={"top_right": "fin.ebitda"},
    )

    flag = next(flag for flag in result.flags if flag.rule == "V12" and "PL_GKV-7b" in flag.message)
    assert flag.severity == "blocking"
    assert flag.note == REQUIRED_NOTE


def test_v12_required_note_resolves_the_flag_and_remains_a_footnote() -> None:
    series = _ebitda(footnotes_auto=[REQUIRED_NOTE])
    result = validate_normalised(
        _filing_with_unmapped_7b(), charted_series=[series], slot_assignments={"top_right": "fin.ebitda"},
    )

    assert not [flag for flag in result.flags if flag.rule == "V12"]
    assert REQUIRED_NOTE in series["footnotes_auto"]


def test_v12_treats_absent_and_unmapped_children_identically() -> None:
    """The whole point of V12: canonical output cannot distinguish a child that
    is absent from the filing from one that is present but unmapped. Both must
    flag, with the same message and note. A regression that treats absence as
    "confirmed absent" would still pass the other two tests in this file."""
    series = {"id": "fin.ebitda", "title": "EBITDA", "earnings_basis": "reported",
              "values": {2024: 10_000_000}, "footnotes_auto": []}
    slots = {"top_right": "fin.ebitda"}
    absent = {"rows": [{"std_id": "PL_GKV-7a", "values": {2024: -2_000_000}}]}
    unmapped = {"rows": [
        {"std_id": "PL_GKV-7a", "values": {2024: -2_000_000}},
        {"std_id": None, "raw_label": "Abschreibungen Umlaufvermoegen", "values": {2024: -500_000}},
    ]}
    a = [f for f in validate_v12(absent, [dict(series)], slots) if "PL_GKV-7b" in f.message]
    u = [f for f in validate_v12(unmapped, [dict(series)], slots) if "PL_GKV-7b" in f.message]
    assert len(a) == 1 and len(u) == 1
    assert a[0].message == u[0].message
    assert a[0].note == u[0].note


def test_v12_treats_absent_and_unmapped_children_identically() -> None:
    """The whole point of V12: canonical output cannot distinguish a child that
    is absent from the filing from one that is present but unmapped. Both must
    flag, with the same message and note. A regression that treats absence as
    "confirmed absent" would still pass the other two tests in this file."""
    series = {"id": "fin.ebitda", "title": "EBITDA", "earnings_basis": "reported",
              "values": {2024: 10_000_000}, "footnotes_auto": []}
    slots = {"top_right": "fin.ebitda"}
    absent = {"rows": [{"std_id": "PL_GKV-7a", "values": {2024: -2_000_000}}]}
    unmapped = {"rows": [
        {"std_id": "PL_GKV-7a", "values": {2024: -2_000_000}},
        {"std_id": None, "raw_label": "Abschreibungen Umlaufvermoegen", "values": {2024: -500_000}},
    ]}
    a = [f for f in validate_v12(absent, [dict(series)], slots) if "PL_GKV-7b" in f.message]
    u = [f for f in validate_v12(unmapped, [dict(series)], slots) if "PL_GKV-7b" in f.message]
    assert len(a) == 1 and len(u) == 1
    assert a[0].message == u[0].message
    assert a[0].note == u[0].note


def test_v12_treats_absent_and_unmapped_children_identically() -> None:
    """The whole point of V12: canonical output cannot distinguish a child that
    is absent from the filing from one that is present but unmapped. Both must
    flag, with the same message and note. A regression that treats absence as
    "confirmed absent" would still pass the other two tests in this file."""
    series = {"id": "fin.ebitda", "title": "EBITDA", "earnings_basis": "reported",
              "values": {2024: 10_000_000}, "footnotes_auto": []}
    slots = {"top_right": "fin.ebitda"}
    absent = {"rows": [{"std_id": "PL_GKV-7a", "values": {2024: -2_000_000}}]}
    unmapped = {"rows": [
        {"std_id": "PL_GKV-7a", "values": {2024: -2_000_000}},
        {"std_id": None, "raw_label": "Abschreibungen Umlaufvermoegen", "values": {2024: -500_000}},
    ]}
    a = [f for f in validate_v12(absent, [dict(series)], slots) if "PL_GKV-7b" in f.message]
    u = [f for f in validate_v12(unmapped, [dict(series)], slots) if "PL_GKV-7b" in f.message]
    assert len(a) == 1 and len(u) == 1
    assert a[0].message == u[0].message
    assert a[0].note == u[0].note