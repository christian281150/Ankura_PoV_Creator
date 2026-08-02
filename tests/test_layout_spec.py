"""Fixture checks for the declarative layout extracted from slide 6."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys

SPEC_PATH = Path("render/templates/slide6_layout.json")
MODULE_PATH = Path("py/render/layout_spec.py")
MODULE_SPEC = importlib.util.spec_from_file_location("layout_spec", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
layout_spec = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = layout_spec
MODULE_SPEC.loader.exec_module(layout_spec)


def test_slide6_rectangles_round_trip() -> None:
    fixture = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    layout = layout_spec.load_slide6_layout(SPEC_PATH)

    assert layout.to_data() == fixture
    assert layout.quadrant("top_left").header.to_data() == fixture["quadrants"]["top_left"]["header"]
    assert layout.quadrant("bottom_right").content.to_data() == fixture["quadrants"]["bottom_right"]["content"]
    assert layout.picture_frame("shirts").to_data() == fixture["products_picture_frames"]["shirts"]
    assert layout.font("quadrant_header").to_data() == fixture["font_ramp"]["quadrant_header"]
    assert layout.color("accent_1") == fixture["palette"]["accent_1"]
    assert layout.header_rule.to_data() == fixture["header_rule"]["rect"]
    assert layout.logo_lockup.to_data() == fixture["logo_lockup"]["rect"]
    assert layout.footnote_band.to_data() == fixture["footnote_band"]["rect"]
