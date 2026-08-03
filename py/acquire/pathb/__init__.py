"""Path B: user-supplied financials for non-German targets with no
Bundesanzeiger filing. See AGENTS.md, "Path B -- user-supplied financials".
"""
from .producer import PathBValidationError, produce_entity_series
from .template import write_blank_template, write_filled_template

__all__ = [
    "PathBValidationError",
    "produce_entity_series",
    "write_blank_template",
    "write_filled_template",
]
