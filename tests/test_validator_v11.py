import json
from pathlib import Path

import pytest

from normalise.lagebericht import LageberichtExtraction, LageberichtProvenance, OneOffAmount
from render.renderer import RenderError, _validate_assignments
from validate.validator import RULE_HANDLERS, validate_normalised


FY24_ONE_OFF = OneOffAmount(
    fiscal_year=2024,
    value=6_236_000,
    unit="EUR",
    source_unit="TEUR",
    direction="income",
    description="Termination of a sale-and-lease-back generated sonstige betriebliche Erträge.",
    pnl_line="sonstige betriebliche Erträge",
    sentence="Termination of a sale-and-lease-back generated T€ 6.236 sonstige betriebliche Erträge.",
    provenance=LageberichtProvenance(doc="Konzernabschluss FY2024", sheet="FY2024_Lagebericht", row=18),
)


def _reported_ebitda(*, footnotes_auto: list[str] | None = None) -> dict[str, object]:
    return {
        "id": "fin.ebitda", "title": "EBITDA", "earnings_basis": "reported",
        "footnotes_auto": footnotes_auto or [],
    }


def test_v11_blocks_reported_fy24_ebitda_without_material_one_off_footnote() -> None:
    result = validate_normalised(
        {"rows": []}, charted_series=[_reported_ebitda()], slot_assignments={"top_right": "fin.ebitda"},
        lagebericht=LageberichtExtraction(one_offs=[FY24_ONE_OFF]),
    )

    flag = next(flag for flag in result.flags if flag.rule == "V11")
    assert flag.severity == "blocking"
    assert flag.note == (
        "FY2024 reported EBITDA includes a €6.2m stated one-off (income): "
        "Termination of a sale-and-lease-back generated sonstige betriebliche Erträge."
    )


def test_v11_accepts_reported_fy24_ebitda_with_required_one_off_footnote() -> None:
    footnote = (
        "FY2024 reported EBITDA includes a €6.2m stated one-off (income): "
        "Termination of a sale-and-lease-back generated sonstige betriebliche Erträge."
    )
    result = validate_normalised(
        {"rows": []}, charted_series=[_reported_ebitda(footnotes_auto=[footnote])],
        slot_assignments={"top_right": "fin.ebitda"},
        lagebericht=LageberichtExtraction(one_offs=[FY24_ONE_OFF]),
    )

    assert not [flag for flag in result.flags if flag.rule == "V11"]


def test_v11_relative_materiality_does_not_treat_eur_2m_as_material_on_eur_500m_revenue() -> None:
    one_off = FY24_ONE_OFF.model_copy(update={"value": 2_000_000})
    result = validate_normalised(
        {"rows": [{"std_id": "PL_GKV-1", "values": {2024: 500_000_000}}]},
        charted_series=[_reported_ebitda()], slot_assignments={"top_right": "fin.ebitda"},
        lagebericht=LageberichtExtraction(one_offs=[one_off]),
    )

    assert not [flag for flag in result.flags if flag.rule == "V11"]


def test_renderer_fails_closed_when_reported_fy24_ebitda_omits_required_footnote() -> None:
    profile = {
        "blocks": [
            {"id": "fin.ebitda", "title": "EBITDA", "earnings_basis": "reported"},
            *[
                {"id": f"block.{slot}", "title": "Other", "earnings_basis": None}
                for slot in ("top_left", "bottom_left", "bottom_right")
            ],
        ],
        "one_offs": [FY24_ONE_OFF.model_dump()],
    }
    assignments = {
        "top_right": "fin.ebitda",
        "top_left": "block.top_left",
        "bottom_left": "block.bottom_left",
        "bottom_right": "block.bottom_right",
    }

    with pytest.raises(RenderError, match="unresolved V11"):
        _validate_assignments(profile, assignments)


def test_every_blocking_contract_rule_has_a_handler_or_is_explicitly_unimplemented() -> None:
    rules = json.loads((Path(__file__).parents[1] / "contract" / "rules.json").read_text(encoding="utf-8"))
    missing = [
        rule_id for rule_id, rule in rules.items()
        if rule["severity"] == "blocking" and rule_id not in RULE_HANDLERS and rule.get("implemented") is not False
    ]

    assert not missing
