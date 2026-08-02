"""CLI for the strictly offline product-image pipeline."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

if __package__:
    from .pipeline import AssetPipeline, AssetPipelineError
else:  # Supports direct execution: python py/acquire/assets/__main__.py ...
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from acquire.assets.pipeline import AssetPipeline, AssetPipelineError


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline normalised product-image cache.")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("cache_dir", type=Path)
    parser.add_argument("--source-url")
    parser.add_argument("--retrieval-date", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--resolution-floor", type=int, default=512)
    args = parser.parse_args()
    try:
        manifest = AssetPipeline(resolution_floor=args.resolution_floor).build(
            args.source_dir, args.cache_dir, source_url=args.source_url, retrieval_date=args.retrieval_date)
    except AssetPipelineError as exc:
        parser.error(str(exc))
    print(f"Cached {len(manifest.assets)} canonical assets in {args.cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
