"""Package command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .consolidate import build_multi_year_tables


def _consolidate(args: argparse.Namespace) -> None:
    """Write a canonical export from an extracted-table payload."""
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    tables = payload["tables"] if isinstance(payload, dict) else payload
    result = build_multi_year_tables(tables, aliases_path=args.aliases)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unternehmensregister extractor commands.")
    subcommands = parser.add_subparsers(dest="command")
    consolidate = subcommands.add_parser("consolidate", help="build canonical multi-year tables")
    consolidate.add_argument("input", type=Path, help="JSON list of extracted tables, or {tables: [...]}")
    consolidate.add_argument("output", type=Path, help="Canonical JSON output")
    consolidate.add_argument("--aliases", type=Path, default=None,
                             help="External reviewed alias CSV; loaded after the generic catalogue")
    consolidate.set_defaults(handler=_consolidate)
    args = parser.parse_args()
    if args.command == "consolidate":
        args.handler(args)
        return

    from .cli import main as interactive_main
    asyncio.run(interactive_main())


if __name__ == "__main__":
    main()
