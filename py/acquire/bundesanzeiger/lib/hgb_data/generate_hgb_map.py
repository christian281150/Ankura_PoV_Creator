"""Regenerate the embedded HGB mapper from ``hgb_mapping.json``.

Run from the Bundesanzeiger submodule:
``python lib/hgb_data/generate_hgb_map.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
MAPPING_PATH = HERE / "hgb_mapping.json"
MAP_MODULE_PATH = HERE.parent / "hgb_map.py"


def normalize(label: str) -> str:
    """Match the mapper's exact structural-label normalisation."""
    text = str(label or "").strip()
    text = re.sub(r"-\s*\r?\n\s*", "", text)
    text = re.sub(r"\s*\((?:gkv|ukv)\)\s*$", "", text, flags=re.I)
    text = re.sub(
        r"^(?:\d+[A-Za-z]?\.\s+|[a-z]\)\s+|[IVXLCDM]+\.\s+|[A-Z]\.\s+)",
        "",
        text,
        count=1,
    )
    text = text.lower()
    for source, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(source, replacement)
    return "".join(char for char in text if char.isalnum())


def main() -> None:
    data = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    for synonym in data.get("label_synonyms", []):
        synonym["normalized_key"] = normalize(synonym.get("original_label", ""))
    MAPPING_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    module = MAP_MODULE_PATH.read_text(encoding="utf-8")
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    updated, substitutions = re.subn(
        r"_RAW = .*?\n\n_DATA =",
        f"_RAW = {raw!r}\n\n_DATA =",
        module,
        count=1,
        flags=re.S,
    )
    if substitutions != 1:
        raise RuntimeError("could not locate the embedded _RAW payload")
    MAP_MODULE_PATH.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
