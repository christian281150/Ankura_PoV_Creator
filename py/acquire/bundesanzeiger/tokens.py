"""
tokens.py — Single source of visual truth for UR Financial Extractor.

All colors, fonts, spacing, row heights, border radii, badge styles, and
state tokens live here. No other file in the codebase should contain
literal hex color strings or hard-coded font names.

Usage:
    from tokens import T, FONT, SPACE, ROW_H, RADIUS, BORDER, BADGE, LAYOUT

T  is a flat convenience dict for fast access: T["P600"], T["N700"], T["warning"], etc.
All values sourced from tokens_export.json v1.0 (analyst-dense-light style).
"""

import tkinter.font as _tkfont

# ── Color palette ──────────────────────────────────────────────────────────────

COLOR = {
    "primary": {
        "50":  "#EEF2FF",
        "100": "#E0E7FF",
        "500": "#6366F1",
        "600": "#4F46E5",
        "700": "#4338CA",
        "900": "#312E81",
    },
    "neutral": {
        "0":   "#FFFFFF",
        "50":  "#F9FAFB",
        "100": "#F3F4F6",
        "200": "#E5E7EB",
        "300": "#D1D5DB",
        "400": "#9CA3AF",
        "500": "#6B7280",
        "600": "#4B5563",
        "700": "#374151",
        "800": "#1F2937",
        "900": "#111827",
    },
    "semantic": {
        "success": {"50": "#ECFDF5", "500": "#10B981"},
        "warning": {"50": "#FFFBEB", "500": "#F59E0B", "700": "#B45309"},
        "error":   {"50": "#FEF2F2", "500": "#EF4444"},
        "info":    {"500": "#3B82F6"},
    },
    "surface": {
        "canvas":           "#FFFFFF",
        "rail":             "#F9FAFB",
        "statusbar":        "#FFFFFF",
        "statusbar_border": "#E5E7EB",
        "hover":            "#F3F4F6",
        "selected":         "#EEF2FF",
        "subtotal":         "#F3F4F6",
        "section_header":   "#F3F4F6",
    },
}

# ── Font resolution ───────────────────────────────────────────────────────────

def _pick(candidates: list) -> str:
    try:
        available = set(_tkfont.families())
        for f in candidates:
            if f in available:
                return f
    except Exception:
        pass
    return candidates[-1]


_SANS    = _pick(["Inter", "Segoe UI", "Helvetica", "TkDefaultFont"])
_NUMERIC = _pick(["Inter", "Cascadia Code", "Consolas", "Courier New"])
_MONO    = _pick(["JetBrains Mono", "Cascadia Code", "Consolas", "Courier New"])


def resolve_sans_font()    -> str: return _SANS
def resolve_numeric_font() -> str: return _NUMERIC


FONT = {
    "family_sans":    _SANS,
    "family_numeric": _NUMERIC,
    "family_mono":    _MONO,
    # (family, size, weight) tuples — pass directly to tkinter font= parameters
    "micro":       (_SANS,    11, "normal"),
    "caption":     (_SANS,    12, "normal"),
    "small":       (_SANS,    13, "normal"),
    "small_bold":  (_SANS,    13, "bold"),
    "body":        (_SANS,    14, "normal"),
    "body_strong": (_SANS,    14, "bold"),
    "h6":          (_SANS,    14, "bold"),
    "h5":          (_SANS,    16, "bold"),
    "h4":          (_SANS,    18, "bold"),
    "h3":          (_SANS,    22, "bold"),
    "num_small":   (_NUMERIC, 13, "normal"),
    "mono":        (_MONO,    11, "normal"),
}

# ── Spacing ───────────────────────────────────────────────────────────────────

SPACE = {
    "s0":  0,  "s1":  4,  "s2":  8,  "s3":  12,
    "s4": 16,  "s5": 20,  "s6": 24,  "s8":  32,  "s10": 40,
}

# ── Density ───────────────────────────────────────────────────────────────────

ROW_H = {"dense": 24, "default": 28, "comfortable": 36}
ROW_P = {"x": 12, "y": 4}  # cell padding

# ── Geometry ─────────────────────────────────────────────────────────────────

RADIUS = {"none": 0, "sm": 4, "md": 6, "lg": 8}
BORDER = {"hairline": 1, "emphasis": 2}
LAYOUT = {
    "left_rail_w":       240,
    "right_rail_w":      320,
    "status_bar_h":       44,
    "outer_tab_h":        40,
    "inner_tab_h":        32,
    "outer_tab_active_w":  2,  # bottom border width on active outer tab
}

# ── Badge tokens ──────────────────────────────────────────────────────────────

BADGE = {
    "type": {
        # Bilanz/GuV/Cashflow: neutral grey (engine success ≠ celebration)
        "Bilanz":   {"bg": "#F3F4F6", "fg": "#374151", "border": "#E5E7EB"},
        "GuV":      {"bg": "#F3F4F6", "fg": "#374151", "border": "#E5E7EB"},
        "Cashflow": {"bg": "#F3F4F6", "fg": "#374151", "border": "#E5E7EB"},
        # Other: amber — this is a workflow item demanding attention
        "Other":    {"bg": "#FFFBEB", "fg": "#B45309", "border": "#F59E0B"},
    },
    "in_overview": {
        "included":   {"glyph": "✓",  "color": "#10B981"},
        "excluded":   {"glyph": "—",  "color": "#9CA3AF"},
        "overridden": {"glyph": "✓*", "color": "#10B981"},
    },
}

# ── State tokens ──────────────────────────────────────────────────────────────

STATE = {
    "active_company": {
        "stripe_w":   2,
        "stripe_col": "#4F46E5",
        "bg":         "#E0E7FF",
        "fg_weight":  "bold",
    },
    "selected": {
        "bg":       "#EEF2FF",
        "border_w": 2,
        "border":   "#4F46E5",
    },
    "hover":        {"bg": "#F3F4F6"},
    "needs_review": {"color": "#F59E0B", "size": 4},
}

# ── Flat convenience dict T ───────────────────────────────────────────────────
# Keys are short aliases. Import T for day-to-day use.

_N  = COLOR["neutral"]
_P  = COLOR["primary"]
_SE = COLOR["semantic"]
_SU = COLOR["surface"]

T: dict = {
    # Primary shades
    "P50":  _P["50"],  "P100": _P["100"], "P500": _P["500"],
    "P600": _P["600"], "P700": _P["700"], "P900": _P["900"],
    # Neutral scale
    "N0":   _N["0"],   "N50":  _N["50"],  "N100": _N["100"],
    "N200": _N["200"], "N300": _N["300"], "N400": _N["400"],
    "N500": _N["500"], "N600": _N["600"], "N700": _N["700"],
    "N800": _N["800"], "N900": _N["900"],
    # Semantic shortcuts
    "success":    _SE["success"]["500"],
    "success50":  _SE["success"]["50"],
    "warning":    _SE["warning"]["500"],
    "warning50":  _SE["warning"]["50"],
    "warning700": _SE["warning"]["700"],
    "error":      _SE["error"]["500"],
    "error50":    _SE["error"]["50"],
    "info":       _SE["info"]["500"],
    # Surface aliases
    "BG":       _SU["canvas"],
    "RAIL":     _SU["rail"],
    "STATUSBAR": _SU["statusbar"],
    "HOVER":    _SU["hover"],
    "SELECTED": _SU["selected"],
    "SUBTOTAL": _SU["subtotal"],
    "SECTION":  _SU["section_header"],
    "BORDER":   _N["200"],
    "BORDER_EM": _N["300"],
}

# ── Soft hex-enforcement utility ──────────────────────────────────────────────

def check_hex_usage(source_file: str) -> list:
    """Return list of inline hex color literals found in source_file."""
    import re
    try:
        content = open(source_file, encoding="utf-8").read()
        return re.findall(r'(?<![A-Za-z0-9_=])(["\']#[0-9A-Fa-f]{6}["\'])', content)
    except Exception:
        return []
