"""
config.py  --  reads settings from config.cfg (plain text, Notepad-editable).
Falls back to built-in defaults if config.cfg is missing.

Theming
-------
The original colour constants (C_BG, C_PANEL, …) remain exported unchanged so
that ur_extractor.py and any legacy importers keep working.  Those values are
the DARK palette (sourced from config.cfg).

The redesigned GUI is theme-aware: it consumes the LIGHT_THEME / DARK_THEME
dicts via build_theme(name) rather than the bare module constants, so the user
can switch between light (default) and dark at runtime.
"""
import configparser, sys
from pathlib import Path

_here = Path(__file__).parent
_exe  = Path(sys.executable).parent
_cfg_path = next(
    (p for p in [_here / "config.cfg", _exe / "config.cfg"] if p.exists()),
    None,
)

# No inline_comment_prefixes so hex colours (#rrggbb) are NOT stripped.
# config.cfg uses ; for comments instead of #.
_cfg = configparser.ConfigParser()
if _cfg_path:
    _cfg.read(str(_cfg_path), encoding="utf-8")

def _s(sec, key, default):
    try:   return _cfg.get(sec, key).strip()
    except Exception: return default

def _i(sec, key, default):
    try:   return int(_s(sec, key, default))
    except Exception: return default

def _f(sec, key, default):
    raw = _s(sec, key, None)
    if not raw: return default
    parts = [p.strip() for p in raw.split(",")]
    try:
        fam    = parts[0]
        size   = int(parts[1]) if len(parts) > 1 else default[1]
        weight = parts[2]      if len(parts) > 2 else None
        return (fam, size, weight) if weight else (fam, size)
    except Exception: return default

WINDOW_WIDTH   = _i("window","width",1300);  WINDOW_HEIGHT  = _i("window","height",860)
WINDOW_MIN_W   = _i("window","min_width",1040); WINDOW_MIN_H = _i("window","min_height",700)
SIDEBAR_WIDTH  = _i("window","sidebar_width",400); RESULTS_HEIGHT = _i("window","results_height",148)

# ── DARK palette (legacy module constants — sourced from config.cfg) ───────────
C_BG      = _s("colours","background",    "#0d0d14")
C_PANEL   = _s("colours","panel",         "#13131f")
C_CARD    = _s("colours","card",          "#1c1c2e")
C_CARD2   = _s("colours","card2",         "#22223a")
C_BORDER  = _s("colours","border",        "#2d2d48")
C_IND     = _s("colours","accent",        "#6366f1")
C_IND2    = _s("colours","accent_light",  "#818cf8")
C_IND_DIM = _s("colours","accent_dim",    "#2d2d6e")
C_T1      = _s("colours","text_primary",  "#f1f5f9")
C_T2      = _s("colours","text_secondary","#94a3b8")
C_T3      = _s("colours","text_muted",    "#475569")
C_GREEN   = _s("colours","green",         "#22c55e")
C_AMBER   = _s("colours","amber",         "#f59e0b")
C_RED     = _s("colours","red",           "#ef4444")
C_PRV_BG  = _s("colours","preview_bg",    "#f8fafc")
C_PRV_TXT = _s("colours","preview_text",  "#0f172a")

TYPE_COLORS = {
    0:  _s("type_colours","bilanz",       "#3b82f6"),
    1:  _s("type_colours","guv",          "#10b981"),
    2:  _s("type_colours","kapitalfluss", "#8b5cf6"),
    99: _s("type_colours","other",        "#6b7280"),
}
TYPE_LABELS = {0:"Bilanz",1:"GuV / Ergebnis",2:"Kapitalfluss",99:"Sonstige"}

R_PILL = 24;  R_CARD = 12;  R_SM = 8

FONT_HERO  = _f("fonts","hero",  ("Segoe UI",14,"bold"))
FONT_H1    = _f("fonts","h1",   ("Segoe UI",13,"bold"))
FONT_H2    = _f("fonts","h2",   ("Segoe UI",11,"bold"))
FONT_BODY  = _f("fonts","body", ("Segoe UI",12))
FONT_SM    = _f("fonts","small",("Segoe UI",11))
FONT_XS    = _f("fonts","xsmall",("Segoe UI",10))
FONT_LABEL = _f("fonts","label",("Segoe UI",9,"bold"))

# Monospace family for tabular figures in the financial grid.
FONT_MONO_FAMILY = _s("fonts","mono_family", "Consolas")

TABLE_ROW_PADY    = _i("table_rows","row_padding",  3)
TABLE_ROW_CB_SIZE = _i("table_rows","checkbox_size",13)
TABLE_LABEL_FONT  = _f("table_rows","label_font",   ("Segoe UI",10))

DEFAULT_DECIMAL_SEP  = "."
DEFAULT_THOUSAND_SEP = ","
DEFAULT_PDF_DIR      = _s("export","pdf_download_folder","~/Downloads/UR_Extracts")

# Currency unit shown once in grid column headers (display-only suffix).
CURRENCY_UNITS   = ["TEUR", "€k", "€'000", "€m", "none"]
DEFAULT_CURRENCY = "TEUR"
DEFAULT_THEME    = "Light"

PAGE_LOAD_TIMEOUT = _i("timeouts","page_load", 15000)
SEARCH_TIMEOUT    = _i("timeouts","search",    20000)
CAPTCHA_TIMEOUT   = _i("timeouts","captcha",   20000)
DOWNLOAD_TIMEOUT  = _i("timeouts","download",  15000)
CLICK_TIMEOUT     = _i("timeouts","click",      8000)
CAPTCHA_WAIT_S    = _i("timeouts","captcha_wait_seconds", 2)

BASE_URL = _s("urls","base_url","https://www.unternehmensregister.de/de")


# ── Theme palettes ────────────────────────────────────────────────────────────
# Each palette is a flat dict consumed by the GUI's theme manager.  Keys mirror
# the legacy C_* names (without the "C_" prefix) plus the new grid-row tokens.

LIGHT_THEME = {
    "BG":      "#ffffff",
    "PANEL":   "#f8fafc",
    "CARD":    "#ffffff",
    "CARD2":   "#f1f5f9",
    "BORDER":  "#e5e7eb",
    "IND":     "#4f46e5",   # single accent (indigo)
    "IND2":    "#6366f1",   # accent hover
    "IND_DIM": "#e0e7ff",   # accent tint
    "T1":      "#0f172a",   # text primary
    "T2":      "#64748b",   # text secondary
    "T3":      "#94a3b8",   # text muted
    "GREEN":   "#059669",
    "AMBER":   "#d97706",
    "RED":     "#dc2626",
    "PRV_BG":  "#ffffff",
    "PRV_TXT": "#0f172a",
    # Grid row backgrounds
    "ROW_HEADER":  "#e2e8f0",   # section header rows
    "ROW_SUBTOT":  "#f1f5f9",   # subtotal rows
    "ROW_GRAND":   "#e2e8f0",   # grand total rows
    "ROW_LINE":    "#ffffff",   # line item rows
    "ROW_ALT":     "#fafafa",   # alternating line item tint
    "ROW_NEG":     "#dc2626",   # negative number text
    "TREE_BG":     "#ffffff",
    "TREE_FG":     "#0f172a",
    "TREE_HDR_BG": "#e2e8f0",
    "TREE_HDR_FG": "#0f172a",
    "TREE_SEL":    "#c7d2fe",
    "TREE_SEL_FG": "#0f172a",
    "LOG_BG":      "#0d1117",   # debug log stays dark in both themes
    "LOG_FG":      "#9ca3af",
}

DARK_THEME = {
    "BG":      C_BG,
    "PANEL":   C_PANEL,
    "CARD":    C_CARD,
    "CARD2":   C_CARD2,
    "BORDER":  C_BORDER,
    "IND":     C_IND,
    "IND2":    C_IND2,
    "IND_DIM": C_IND_DIM,
    "T1":      C_T1,
    "T2":      C_T2,
    "T3":      C_T3,
    "GREEN":   C_GREEN,
    "AMBER":   C_AMBER,
    "RED":     C_RED,
    "PRV_BG":  C_PRV_BG,
    "PRV_TXT": C_PRV_TXT,
    "ROW_HEADER":  "#22223a",
    "ROW_SUBTOT":  "#1c1c2e",
    "ROW_GRAND":   "#2d2d48",
    "ROW_LINE":    "#13131f",
    "ROW_ALT":     "#181826",
    "ROW_NEG":     "#f87171",
    "TREE_BG":     "#13131f",
    "TREE_FG":     "#e2e8f0",
    "TREE_HDR_BG": "#1e293b",
    "TREE_HDR_FG": "#f1f5f9",
    "TREE_SEL":    "#4f46e5",
    "TREE_SEL_FG": "#ffffff",
    "LOG_BG":      "#0d1117",
    "LOG_FG":      "#9ca3af",
}


def build_theme(name: str = "Light") -> dict:
    """Return the palette dict for 'Light' or 'Dark'.  Default: light."""
    return dict(DARK_THEME if str(name).lower().startswith("d") else LIGHT_THEME)
