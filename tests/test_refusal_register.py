"""Guard deliberate non-mapping decisions from accidental alias reintroduction."""

from __future__ import annotations

import csv
from pathlib import Path

from extractor import _core
from extractor.consolidate import _display_label_key


ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "py" / "acquire" / "bundesanzeiger" / "reviews" / "refusal_register.csv"
ALIAS_PATHS = (
    ROOT / "py" / "acquire" / "bundesanzeiger" / "aliases" / "client_aliases.csv",
    ROOT / "py" / "normalise" / "aliases" / "client_aliases.csv",
)


def _alias_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _alias_key(row: dict[str, str]) -> str:
    normalized_key = row.get("normalized_key", "")
    if normalized_key:
        return normalized_key
    return _core._hgb.normalize(_display_label_key(row.get("client_label", "")))


def test_refusal_register_is_well_formed_and_enforced() -> None:
    register_rows = _alias_rows(REGISTER_PATH)
    aliases = [row for path in ALIAS_PATHS for row in _alias_rows(path)]

    for register in register_rows:
        assert register["reason"], f"Missing refusal-register reason for {register['normalized_key']}"
        assert register["decision"] in {"refuse", "defer"}, (
            f"Invalid refusal-register decision for {register['normalized_key']}: {register['decision']}"
        )
        for alias in aliases:
            assert not (
                _alias_key(alias) == register["normalized_key"]
                and alias.get("std_id", "") == register["proposed_std_id"]
            ), register["reason"]
