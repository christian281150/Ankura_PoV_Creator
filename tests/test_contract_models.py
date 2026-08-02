from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError
import pytest

from contract.models import EntitySeries


def filing_observation(value: str) -> dict[str, object]:
    return {
        "value": value,
        "provenance": {
            "kind": "filing",
            "document": "Konzernabschluss FY2025",
            "page": 7,
        },
        "restated": False,
    }


def test_entity_series_constructs_with_an_explicit_fiscal_year_end_and_conflict() -> None:
    series = EntitySeries.model_validate(
        {
            "entity_id": "HRA-8217-AG-Bielefeld",
            "source_kind": "filings",
            "fiscal_year_end": {"month": 4, "day": 30},
            "fiscal_years": [2024, 2025],
            "line_items": [
                {
                    "std_id": "PL_GKV-1",
                    "points": [
                        {
                            "fy": 2024,
                            "unit": "EUR",
                            "currency": "USD",
                            "framework": "hgb",
                            "pnl_method": "gkv",
                            "presentation_basis": "umsatzerloese",
                            "scope_flag": None,
                            "method_flag": "GKV",
                            "observations": [filing_observation("103200000.00")],
                            "resolution": None,
                        },
                        {
                            "fy": 2025,
                            "unit": "EUR",
                            "currency": "USD",
                            "framework": "hgb",
                            "pnl_method": "gkv",
                            "presentation_basis": "umsatzerloese",
                            "scope_flag": None,
                            "method_flag": "GKV",
                            "observations": [
                                filing_observation("111815106.14"),
                                {**filing_observation("111700000.00"), "restated": True},
                            ],
                            "resolution": {
                                "chosen_observation_index": 0,
                                "reason": "Current-year filed value selected after review.",
                                "decided_by": "analyst@example.com",
                            },
                        },
                    ],
                }
            ],
        }
    )

    assert series.fiscal_year_end.month == 4
    assert series.line_items[0].points[1].observations[0].value == Decimal("111815106.14")
    assert series.line_items[0].points[1].resolution is not None


def test_entity_series_round_trips_per_year_path_b_metadata() -> None:
    payload = {
        "entity_id": "user-workbook-example",
        "source_kind": "user_workbook",
        "fiscal_year_end": {"month": 12, "day": 31},
        "fiscal_years": [2015, 2016],
        "line_items": [{
            "std_id": "PL_GKV-1",
            "points": [
                {"fy": 2015, "unit": "TEUR", "currency": "EUR", "framework": "hgb", "pnl_method": "gkv", "presentation_basis": "umsatzerloese", "scope_flag": "consolidated", "method_flag": "GKV", "observations": [{"value": "100.00", "provenance": {"kind": "user_supplied"}, "restated": False}], "resolution": None},
                {"fy": 2016, "unit": "EUR", "currency": "EUR", "framework": "hgb", "pnl_method": "gkv", "presentation_basis": "umsatzerloese", "scope_flag": "consolidated", "method_flag": "GKV", "observations": [{"value": "101000.00", "provenance": {"kind": "user_supplied"}, "restated": False}], "resolution": None},
            ],
        }],
    }

    round_tripped = EntitySeries.model_validate_json(EntitySeries.model_validate(payload).model_dump_json())

    assert [point.unit for point in round_tripped.line_items[0].points] == ["TEUR", "EUR"]
    assert round_tripped.line_items[0].points[0].scope_flag == "consolidated"


def test_typescript_contract_has_the_same_per_year_path_b_fields() -> None:
    typescript = (Path(__file__).parents[1] / "contract" / "profile.ts").read_text(encoding="utf-8")
    point = typescript.split("export interface LineItemPoint {", 1)[1].split("\n}", 1)[0]
    observation = typescript.split("export interface LineItemObservation {", 1)[1].split("\n}", 1)[0]

    for field in ("unit: AmountUnit;", "currency: CurrencyCode;", "framework: Framework;", "pnlMethod: PnlMethod;", "presentationBasis: PresentationBasis;", "scopeFlag: string | null;", "methodFlag: string | null;"):
        assert field in point
    assert "presentationBasis" not in observation


@pytest.mark.parametrize(
    "payload",
    [
        {"entity_id": "HRA-8217-AG-Bielefeld"},
        {
            "entity_id": "HRA-8217-AG-Bielefeld",
            "source_kind": "filings",
            "fiscal_year_end": {"month": 4, "day": 30},
            "fiscal_years": [2025],
            "line_items": [
                {
                    "std_id": "PL_GKV-1",
                    "points": [{"fy": 2025, "observations": [{"value": "1.00"}]}],
                }
            ],
        },
        {
            "entity_id": "HRA-8217-AG-Bielefeld",
            "source_kind": "filings",
            "fiscal_year_end": {"month": 2, "day": 31},
            "fiscal_years": [2025],
            "line_items": [
                {
                    "std_id": "PL_GKV-1",
                    "points": [
                        {
                            "fy": 2025,
                            "unit": "EUR",
                            "currency": "USD",
                            "framework": "hgb",
                            "pnl_method": "gkv",
                            "presentation_basis": "umsatzerloese",
                            "scope_flag": None,
                            "method_flag": "GKV",
                            "observations": [filing_observation("1.00")],
                            "resolution": None,
                        }
                    ],
                }
            ],
        },
    ],
)
def test_entity_series_rejects_incomplete_or_invalid_records(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EntitySeries.model_validate(payload)
