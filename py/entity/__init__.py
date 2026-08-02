"""Register-first, offline entity resolution for company profiles."""

from .fetch import EntityFetch, FixtureEntityFetch
from .models import (
    EntityRecord,
    RegisterId,
    ResolutionError,
    ResolutionResult,
    ResolutionWarning,
    ShareholderEntry,
)
from .service import EntityResolutionService
from .store import JsonEntityStore

__all__ = [
    "EntityFetch",
    "EntityRecord",
    "EntityResolutionService",
    "FixtureEntityFetch",
    "RegisterId",
    "JsonEntityStore",
    "ResolutionError",
    "ResolutionResult",
    "ResolutionWarning",
    "ShareholderEntry",
]
