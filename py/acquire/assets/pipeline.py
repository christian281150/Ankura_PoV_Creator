"""Offline image ingestion, perceptual de-duplication and normalisation."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from PIL import Image, ImageOps

from .models import AssetManifest, AssetProvenance, ProductImageAsset

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class AssetPipelineError(RuntimeError):
    """Raised when local source assets cannot be safely processed."""


@dataclass(frozen=True)
class _IngestedImage:
    path: Path
    content_hash: str
    perceptual_hash: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _average_hash(image: Image.Image) -> int:
    sample = ImageOps.grayscale(image).resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(sample.get_flattened_data())
    average = sum(pixels) / len(pixels)
    return sum((1 << index) for index, value in enumerate(pixels) if value >= average)


def _hash_hex(value: int) -> str:
    return f"{value:016x}"


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _knock_out_separable_background(image: Image.Image) -> Image.Image:
    """Make an edge-connected near-white background transparent, if it is separable.

    Connectedness prevents interior garment highlights from being removed.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    queue: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()
    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(height):
        queue.extend(((0, y), (width - 1, y)))
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        red, green, blue, alpha = pixels[x, y]
        if alpha == 0 or min(red, green, blue) < 242 or max(red, green, blue) - min(red, green, blue) > 12:
            continue
        pixels[x, y] = (red, green, blue, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                queue.append((nx, ny))
    return rgba


def _normalise(image: Image.Image, resolution_floor: int) -> Image.Image:
    square = ImageOps.fit(image, (max(image.size), max(image.size)), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    if square.width < resolution_floor:
        square = square.resize((resolution_floor, resolution_floor), Image.Resampling.LANCZOS)
    return _knock_out_separable_background(square)


class AssetPipeline:
    def __init__(self, resolution_floor: int = 512, perceptual_hash_distance: int = 0) -> None:
        if resolution_floor < 1 or perceptual_hash_distance < 0:
            raise ValueError("resolution_floor must be positive and perceptual_hash_distance non-negative")
        self.resolution_floor = resolution_floor
        self.perceptual_hash_distance = perceptual_hash_distance

    def build(self, source_dir: Path, cache_dir: Path, *, source_url: str | None = None,
              retrieval_date: date | None = None) -> AssetManifest:
        if not source_dir.is_dir():
            raise AssetPipelineError(f"source directory is missing: {source_dir}")
        files = sorted(path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)
        if not files:
            raise AssetPipelineError(f"source directory has no supported image files: {source_dir}")
        retrieval_date = retrieval_date or datetime.now(UTC).date()
        ingested: list[_IngestedImage] = []
        for path in files:
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    perceptual_hash = _average_hash(image)
            except (OSError, ValueError) as exc:
                raise AssetPipelineError(f"invalid image asset: {path}") from exc
            ingested.append(_IngestedImage(path, _sha256(path), perceptual_hash))

        cache_dir.mkdir(parents=True, exist_ok=True)
        retained: list[tuple[_IngestedImage, list[Path]]] = []
        for candidate in ingested:
            identical = next((item for item in retained if item[0].content_hash == candidate.content_hash), None)
            near_match = next((item for item in retained if _hamming(item[0].perceptual_hash, candidate.perceptual_hash) <= self.perceptual_hash_distance), None)
            if identical or near_match:
                (identical or near_match)[1].append(candidate.path)
            else:
                retained.append((candidate, []))

        assets: list[ProductImageAsset] = []
        for canonical, duplicates in retained:
            asset_id = f"asset_{canonical.content_hash[:16]}"
            image_path = cache_dir / f"{asset_id}.png"
            with Image.open(canonical.path) as image:
                normalised = _normalise(image, self.resolution_floor)
                width, height = normalised.size
                normalised.save(image_path, format="PNG", optimize=True)
            asset = ProductImageAsset(
                id=asset_id,
                cache_path=image_path.name,
                width=width,
                height=height,
                perceptual_hash=_hash_hex(canonical.perceptual_hash),
                provenance=AssetProvenance(source_path=canonical.path.name, source_url=source_url,
                    retrieval_date=retrieval_date, content_hash_sha256=canonical.content_hash),
                duplicate_source_paths=[path.name for path in duplicates],
            )
            sidecar = cache_dir / f"{asset_id}.json"
            sidecar.write_text(json.dumps(asset.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            assets.append(asset)
        manifest = AssetManifest(assets=assets)
        (cache_dir / "manifest.json").write_text(json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return manifest


def build_asset_cache(source_dir: Path, cache_dir: Path, **kwargs: object) -> AssetManifest:
    return AssetPipeline().build(source_dir, cache_dir, **kwargs)
