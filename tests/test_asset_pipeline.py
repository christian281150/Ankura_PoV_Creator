from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from acquire.assets.pipeline import AssetPipeline, AssetPipelineError
from PIL import Image

ROOT = Path(__file__).parents[1]


RAW = ROOT / "tests" / "fixtures" / "assets_raw"


def test_fixture_images_are_cached_deduplicated_and_square(tmp_path: Path) -> None:
    manifest = AssetPipeline(resolution_floor=512).build(
        RAW, tmp_path, source_url="https://example.invalid/assets", retrieval_date=date(2026, 8, 2))

    assert len(list(RAW.iterdir())) == 18
    assert len(manifest.assets) == 14
    assert all(asset.width == asset.height >= 512 for asset in manifest.assets)
    assert all((tmp_path / asset.cache_path).is_file() for asset in manifest.assets)
    assert any(len(asset.duplicate_source_paths) >= 2 for asset in manifest.assets)
    duplicate = next(asset for asset in manifest.assets if len(asset.duplicate_source_paths) >= 2)
    assert duplicate.provenance.source_path.endswith(".jpg.jpeg")
    assert all(path.endswith(".jpeg") for path in duplicate.duplicate_source_paths)

    saved = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0"
    assert saved["assets"][0]["id"].startswith("asset_")
    for asset in manifest.assets:
        with Image.open(tmp_path / asset.cache_path) as image:
            assert image.format == "PNG"
            assert image.size == (asset.width, asset.height)
        assert (tmp_path / f"{asset.id}.json").is_file()


def test_missing_or_empty_source_directory_fails_safely(tmp_path: Path) -> None:
    pipeline = AssetPipeline()
    try:
        pipeline.build(tmp_path / "missing", tmp_path / "cache")
    except AssetPipelineError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("missing source must fail")
