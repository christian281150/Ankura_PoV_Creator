"""Pydantic models forming the asset-cache contract."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class AssetProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    source_url: str | None = None
    retrieval_date: date
    content_hash_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProductImageAsset(BaseModel):
    """One canonical cached image.  IDs are SHA-256-derived and stable."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^asset_[0-9a-f]{16}$")
    cache_path: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    format: str = "PNG"
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")
    provenance: AssetProvenance
    duplicate_source_paths: list[str] = Field(default_factory=list)


class AssetManifest(BaseModel):
    """Render-facing list keyed by stable image ID; intentionally unclassified."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    assets: list[ProductImageAsset]


MANIFEST_SCHEMA_PATH = Path(__file__).with_name("manifest.schema.json")
