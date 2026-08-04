"""P6 -- coverage probe.

Spec section 8 describes the coverage probe as a per-dimension bar-chart-style
summary that runs ahead of slot assignment and drives the GUI's ranked lists.
Before this module, nothing in the codebase constructed
``contract.models.CoverageDimension`` (zero producers, confirmed by grep) --
the frozen ``Profile.coverage`` field existed on paper only.

This probe deliberately adds no new judgment about data quality. Each
dimension's score is exactly the ``coverage`` figure the corresponding content
block already computed honestly in ``render.assemble_profile`` (1.0 for a
fully disclosed multi-year series, 0.0 for an explicit gap block). Recomputing
or reweighting that number here would be a second, possibly divergent opinion
about the same evidence; relabelling it into the frozen per-dimension shape is
enough, and keeps this step testable independent of render.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from contract.models import CoverageDimension


def compute_coverage_dimensions(blocks: Iterable[Mapping[str, Any]]) -> list[CoverageDimension]:
    """One ``CoverageDimension`` per content block, in block order.

    ``label`` is the block's own title, so it reads the same on the coverage
    matrix as it does on the slot-assignment screen. A block missing
    ``title``/``coverage`` is a producer bug upstream, not something this
    probe should paper over with a default.
    """
    dimensions: list[CoverageDimension] = []
    for block in blocks:
        title = block.get("title")
        coverage = block.get("coverage")
        if not title:
            raise ValueError(f"Block {block.get('id')!r} has no title for a coverage dimension label.")
        if coverage is None:
            raise ValueError(f"Block {block.get('id')!r} has no coverage score.")
        dimensions.append(CoverageDimension(label=str(title), score=float(coverage)))
    return dimensions
