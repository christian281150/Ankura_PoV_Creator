from decimal import Decimal

from pydantic import ValidationError
import pytest

from contract.models import EntitySeries


def filing_observation(value: str) -> dict[str, object]:
    return {
        "value": value,
        "unit": "USD",
        "presentation_basis": "umsatzerloese",
        "framework": "hgb",
        "pnl_method": "gkv",
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
                            "observations": [filing_observation("103200000.00")],
                            "resolution": None,
                        },
                        {
                            "fy": 2025,
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
