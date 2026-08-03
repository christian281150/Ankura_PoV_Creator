"""Merge N per-filing canonical exports into one EntitySeries.

Each input filing is one call's worth of
``extractor.consolidate.build_multi_year_tables()`` output (a list of
multi-year statement tables, already itself spanning that filing's own
current + comparative fiscal years). This module reconciles the *overlap*
across filings: the same fiscal year commonly appears as the current year in
one filing and as a prior-year comparative in a later one.

Reconciliation is keyed exclusively on ``std_id`` -- never row index or
position, since row order is a PDF-layout artefact and carries no accounting
meaning across two different filings' extractions.

Two filings agreeing on a figure is the unremarkable case: it collapses to
one ``LineItemObservation`` and needs no sign-off. Two filings disagreeing on
the same (std_id, fiscal year) is a restatement, and this module never picks
a winner -- both observations are kept, ``resolution`` stays ``None``, and an
explicit human decision (which the contract models as
``LineItemConflictResolution``, with a stated reason and decider) is left for
a later, separate review step. Inventing a resolution here would be exactly
the "confidently wrong output" the project's prime directive forbids.

Known gap, not handled here: if two filings disagree not just on a value but
on the accounting basis itself (e.g. one states a fiscal year under GKV, the
other under UKV) the point's framework/pnl_method/etc. are taken from
whichever observation is primary (see ``_representative``) and the
conflicting source's own basis is silently not surfaced as a *second* kind of
conflict. Neither proving-ground filing exercises this, so no handling is
built for it -- flag it if a real filing pair ever does this.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from contract.models import (
    EntitySeries,
    FilingSeriesProvenance,
    FiscalYearEnd,
    LineItemObservation,
    LineItemPoint,
    LineItemSeries,
)

_CENT = Decimal("0.01")


def _filing_current_fy(filing_tables: list[dict[str, Any]]) -> int:
    """The fiscal year this filing itself discloses as the current year.

    Taken as the max year across all of the filing's own multi-year tables,
    rather than passed in by the caller: every statement type in one filing
    covers the same current/comparative pair, so this is derivable from the
    data itself without an extra parameter that could drift out of sync.
    """
    years = [year for table in filing_tables if table.get("multi_year") for year in table.get("years", ())]
    if not years:
        raise ValueError("filing has no multi-year tables to determine its current fiscal year")
    return max(years)


def _method_flag(pnl_method: str | None) -> str | None:
    return pnl_method.upper() if pnl_method in ("gkv", "ukv") else None


def _representative(group: list[dict[str, Any]]) -> dict[str, Any]:
    """The entry to source an observation's provenance and metadata from.

    Prefer the entry from a filing where this fiscal year was the current
    year over one where it was only a comparative -- the current-year
    disclosure is the primary statement for that year, not a restatement of
    it.
    """
    return next((entry for entry in group if entry["is_primary"]), group[0])


def _build_point(fy: int, entries: list[dict[str, Any]]) -> LineItemPoint:
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        key = str(entry["value"].quantize(_CENT))
        groups.setdefault(key, []).append(entry)

    representatives = [_representative(group) for group in groups.values()]
    representatives.sort(key=lambda entry: not entry["is_primary"])  # primary-sourced first
    disputed = len(representatives) > 1

    observations = [
        LineItemObservation(
            value=rep["value"],
            provenance=FilingSeriesProvenance(kind="filing", document=rep["document"], page=rep["page"] or 1),
            restated=disputed and not rep["is_primary"],
        )
        for rep in representatives
    ]

    meta_source = _representative(representatives)
    return LineItemPoint(
        fy=fy,
        unit="EUR",
        currency="EUR",
        framework=meta_source["framework"],
        pnl_method=meta_source["pnl_method"],
        presentation_basis=meta_source["presentation_basis"] or "n/a",
        scope_flag="consolidated",
        method_flag=_method_flag(meta_source["pnl_method"]),
        observations=observations,
        resolution=None,
    )


def build_entity_series(
    entity_id: str,
    fiscal_year_end: FiscalYearEnd,
    filings: list[list[dict[str, Any]]],
) -> EntitySeries:
    """Reconcile N filings' canonical exports into one EntitySeries.

    ``filings`` order does not matter -- each cell's current-vs-comparative
    status is read from its own source filing (``_filing_current_fy``), not
    inferred from the order filings are passed in.
    """
    collected: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for filing_tables in filings:
        current_fy = _filing_current_fy(filing_tables)
        for table in filing_tables:
            if not table.get("multi_year"):
                continue
            years = table["years"]
            framework = table.get("framework")
            pnl_method = table.get("pnl_method")
            for meta, row in zip(table["row_metadata"], table["rows"][1:]):
                std_id = meta.get("std_id")
                if std_id is None:
                    continue  # anonymous subtotals (see consolidate.py) stay internal to one filing
                provenance_by_fy = meta.get("provenance_by_fy") or {}
                for index, fy in enumerate(years):
                    cell = row[index + 1]
                    if cell == "" or cell is None:
                        continue
                    provenance = provenance_by_fy.get(fy) or {}
                    collected.setdefault((std_id, fy), []).append({
                        "value": Decimal(str(cell)),
                        "is_primary": fy == current_fy,
                        "document": provenance.get("doc") or table.get("doc_label") or table.get("heading") or "unknown",
                        "page": provenance.get("page") or table.get("page_start"),
                        "framework": framework,
                        "pnl_method": pnl_method,
                        "presentation_basis": meta.get("presentation_basis"),
                    })

    by_std_id: dict[str, list[LineItemPoint]] = {}
    for (std_id, fy), entries in collected.items():
        by_std_id.setdefault(std_id, []).append(_build_point(fy, entries))

    line_items = [
        LineItemSeries(std_id=std_id, points=sorted(points, key=lambda point: point.fy))
        for std_id, points in sorted(by_std_id.items())
    ]

    return EntitySeries(
        entity_id=entity_id,
        source_kind="filings",
        fiscal_year_end=fiscal_year_end,
        fiscal_years=sorted({fy for _std_id, fy in collected}),
        line_items=line_items,
    )
