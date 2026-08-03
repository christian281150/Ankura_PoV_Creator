"""Regression test for _queue_unmapped's dedup key.

Found while adding Lane G2 (cashflow taxonomy): dedup keyed on
`normalized_key or raw_label` collapses every blank-labeled queue entry
(unverified positional subtotals -- see consolidate.py's _column_actuals)
into a single row, because they all share raw_label="". Two blank rows from
two different tables are two different unresolved facts, not one repeated
label, and must not silently disappear from the review queue.
"""
from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from extractor.consolidate import _queue_unmapped


def _blank_entry(heading: str, row: int) -> dict[str, object]:
    return {
        "raw_label": "", "normalized_key": "", "match_type": "unlabelled_no_verified_subtotal",
        "candidates": "", "doc_label": "", "heading": heading, "page_start": 1, "row": row,
    }


def test_two_blank_rows_from_different_tables_both_survive_dedup() -> None:
    entries = [_blank_entry("Table A", 10), _blank_entry("Table B", 22)]
    with TemporaryDirectory() as tmp_dir:
        queue_path = Path(tmp_dir) / "queue.csv"
        _queue_unmapped(entries, queue_path)
        with queue_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    assert len(rows) == 2, "two distinct unresolved rows must not collapse into one"
    assert {(row["heading"], row["row"]) for row in rows} == {("Table A", "10"), ("Table B", "22")}


def test_the_same_named_label_repeated_still_dedups() -> None:
    """The dedup's actual purpose -- a genuinely repeated unresolved label
    (e.g. the same unmapped concept recurring across years) still collapses
    to one review item, unaffected by the blank-label fix."""
    entries = [
        {"raw_label": "Sonstiges", "normalized_key": "sonstiges", "match_type": "none", "candidates": "",
         "doc_label": "", "heading": "Table A", "page_start": 1, "row": 5},
        {"raw_label": "Sonstiges", "normalized_key": "sonstiges", "match_type": "none", "candidates": "",
         "doc_label": "", "heading": "Table B", "page_start": 1, "row": 9},
    ]
    with TemporaryDirectory() as tmp_dir:
        queue_path = Path(tmp_dir) / "queue.csv"
        _queue_unmapped(entries, queue_path)
        with queue_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    assert len(rows) == 1
