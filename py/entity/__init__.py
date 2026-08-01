"""Register-first, offline entity resolution for company profiles."""

from .fetch import EntityFetch, FixtureEntityFetch
from .models import (
    EntityRecord,
    RegisterId,
    ResolutionError,
    ResolutionResult,
    ResolutionWarning,
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
]
