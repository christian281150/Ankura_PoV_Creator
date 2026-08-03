"""Wire the sheet classifier into its already-built consumers.

sheet_classifier.classify_workbook(), lagebericht.extract_lagebericht(), and
segments.extract_segments() were committed together (eca2e1e, this repo's
earliest history) and were clearly designed to compose: extract_lagebericht
and extract_segments both take a ``classifications: dict[str, str]``
parameter whose keys (sheet name) and values (one of
sheet_classifier.SHEET_TYPES) match classify_workbook's own output exactly --
confirmed directly, not assumed: extract_lagebericht's own permitted set is
``{"lagebericht_vermoegenslage", "lagebericht_finanzlage"}``, byte-for-byte
sheet_classifier's category names. Nothing ever called them together. This
module is that missing call.

Five of the eleven classifier categories (anlagenspiegel, eigenkapitalspiegel,
fristigkeiten, anhang_konsolidierungskreis, and workbook-native
bilanz/guv/kapitalflussrechnung) have no matching parser yet -- building one
is a separate, larger piece of work, out of scope here. Sheets in those
categories are classified (visible via ``classifications``) but not further
extracted; nothing pretends otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from normalise.lagebericht import LageberichtExtraction, extract_lagebericht
from normalise.segments import SegmentExtraction, extract_segments
from normalise.sheet_classifier import classify_workbook


@dataclass
class WorkbookEvidence:
    """Everything classify_workbook's already-built consumers can extract
    from one workbook, plus the classification itself and its unknown rate --
    reported, per P1's own acceptance criterion, never silently dropped."""

    classifications: dict[str, str]
    unknown_sheets: list[str]
    unknown_rate: float
    lagebericht: LageberichtExtraction
    segments: SegmentExtraction


def extract_workbook_evidence(workbook: Any) -> WorkbookEvidence:
    """Classify every sheet once, then route classified sheets to their
    matching parser."""
    classifications = classify_workbook(workbook)
    unknown_sheets = sorted(name for name, kind in classifications.items() if kind == "unknown")
    unknown_rate = len(unknown_sheets) / len(classifications) if classifications else 0.0
    return WorkbookEvidence(
        classifications=classifications,
        unknown_sheets=unknown_sheets,
        unknown_rate=unknown_rate,
        lagebericht=extract_lagebericht(workbook, classifications),
        segments=extract_segments(workbook, classifications),
    )
