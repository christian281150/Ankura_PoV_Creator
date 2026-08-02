"""Command-line entry point for the auditable profile renderer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports both ``python -m render.render_profile`` and direct execution.
    from .renderer import RenderError, render_profile
except ImportError:  # pragma: no cover - exercised by the command-line path
    from renderer import RenderError, render_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a company profile into the Ankura master.")
    parser.add_argument("profile", type=Path, help="Profile JSON path")
    parser.add_argument("output", type=Path, help="Output .pptx path")
    parser.add_argument("--template", type=Path, help="Ankura master .pptx path")
    arguments = parser.parse_args()
    if arguments.profile.resolve() == arguments.output.with_suffix(".json").resolve():
        parser.error("Output .pptx basename would overwrite the input profile JSON companion.")
    try:
        profile = json.loads(arguments.profile.read_text(encoding="utf-8"))
        render_profile(profile, arguments.output, template=arguments.template)
    except (OSError, json.JSONDecodeError, RenderError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
