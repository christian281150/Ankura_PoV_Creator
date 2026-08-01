"""Shared foundation: imports, console, HGB handle, State, type maps, and
small cross-cutting helpers (number parsing, canonical row keys)."""

import re
from enum import Enum, auto
from pathlib import Path
from rich.console import Console

# Repo root, anchored one level up from this package (source) so the
# data/aliases/reviews/library paths resolve exactly as before.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

console = Console()
try:
    import lib.hgb_map as _hgb
    _HGB_AVAILABLE = True
except Exception:
    _hgb = None
    _HGB_AVAILABLE = False


class State(Enum):
    """Phases of the register-acquisition pipeline (drives status reporting):
    SEARCH → SELECT_DOC → CAPTCHA → DOWNLOAD → EXTRACT → EXPORT → QUIT.
    """
    SEARCH      = auto()
    SELECT_DOC  = auto()
    CAPTCHA     = auto()
    DOWNLOAD    = auto()
    EXTRACT     = auto()
    EXPORT      = auto()
    QUIT        = auto()


def sanitize_filename(text: str) -> str:
    """Replace spaces and non-alphanumeric characters with underscores."""
    return re.sub(r"[^\w]+", "_", text).strip("_")


def _parse_num_cell(val, thousand_sep: str = ".", decimal_sep: str = ","):
    """
    Parse a PDF cell value as a bare Python float.

    Three-pass approach
    -------------------
    Pass 1 — primary locale (thousands + decimal):
        Use the caller-supplied separators. Handles standard values and the
        single-separator decimal fallback (e.g. "87.0596" → 87.0596).

    Pass 2 — strict thousands fallback (alternate locale):
        If Pass 1 fails, attempt the *opposite* locale using ONLY the
        thousands-group matching path (no decimal fallback). This means
        "10.696.470,77" still parses when "English" is selected, but
        short values like "4.8" (Anhang cross-references) are NOT parsed
        via the decimal path and correctly return None.

    Negative numbers
    ----------------
    A leading "-" is preserved as negative throughout all passes.

    Returns
    -------
    float | None
        Parsed float, or None if the value is plain text / an Anhang reference.
    """

    def _try_full(s2, tho, dec):
        """
        Full parse: thousands-group matching PLUS single-separator decimal
        fallback.  Used as the primary (Pass 1) attempt.
        """
        int_part = s2.split(dec, 1)[0] if dec and dec in s2 else s2
        if tho and tho in int_part:
            groups   = int_part.split(tho)
            first_ok = 1 <= len(groups[0]) <= 3
            rest_ok  = all(len(g) == 3 and g.isdigit() for g in groups[1:])
            if first_ok and rest_ok:
                cleaned = s2.replace(tho, "")
                cleaned = cleaned.replace(dec, ".") if dec else cleaned
                try:
                    return float(cleaned)
                except ValueError:
                    return None
            # Single-separator with >= 3 trailing digits → treat as decimal
            if dec not in s2 and s2.count(tho) == 1:
                after = groups[-1]
                if len(after) >= 3 and after.isdigit():
                    try:
                        return float(s2.replace(tho, ".", 1))
                    except ValueError:
                        pass
            return None
        elif not int_part.isdigit():
            return None
        cleaned = s2.replace(dec, ".") if dec else s2
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _try_thousands_only(s2, tho, dec):
        """
        Strict parse: only accepts values that match the thousands-group
        pattern (first group 1-3 digits, remaining groups exactly 3 digits).
        Does NOT fall through to the decimal path, so "4.8" returns None.
        Used as the fallback (Pass 2) to avoid mis-parsing Anhang references.
        """
        int_part = s2.split(dec, 1)[0] if dec and dec in s2 else s2
        if not (tho and tho in int_part):
            return None
        groups   = int_part.split(tho)
        first_ok = 1 <= len(groups[0]) <= 3
        rest_ok  = all(len(g) == 3 and g.isdigit() for g in groups[1:])
        if not (first_ok and rest_ok):
            return None
        cleaned = s2.replace(tho, "")
        cleaned = cleaned.replace(dec, ".") if dec else cleaned
        try:
            return float(cleaned)
        except ValueError:
            return None

    # ── Validate input ────────────────────────────────────────────────────────
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ("-", "\u2013", "\u2014"):
        return None

    negative = s.startswith("-")
    s2 = s.lstrip("-").strip()
    if not s2 or not s2[0].isdigit():
        return None

    # ── Pass 1: primary locale (full parse) ───────────────────────────────────
    result = _try_full(s2, thousand_sep, decimal_sep)
    if result is not None:
        return -result if negative else result

    # ── Pass 2: alternate locale, thousands-only (no decimal fallback) ────────
    alt_tho = "," if thousand_sep == "." else "."
    alt_dec = "." if decimal_sep   == "," else ","
    result  = _try_thousands_only(s2, alt_tho, alt_dec)
    if result is not None:
        return -result if negative else result

    return None
_ROW_SYNONYMS = [
    (re.compile(
        r'jahres(?:über|fehl)betrag|jahresüberschuss|jahresergebnis'
        r'|ergebnis des geschäftsjahres|ergebnis nach (steuern|ertragsteuern)',
        re.I), 'jahresergebnis'),
    (re.compile(
        r'gesamt(?:ergebnis|verlust|periodenergebnis)'
        r'|sonstiges gesamtergebnis nach steuern'
        r'|gesamtergebnis.*periode', re.I), 'gesamtergebnis'),
    (re.compile(
        r'(?:ergebnis|verlust|fehlbetrag|gewinn)\s+vor\s+ertragsteuern'
        r'|ergebnis vor steuern', re.I), 'ergebnis vor ertragsteuern'),
    (re.compile(r'bilanz(?:gewinn|verlust|ergebnis)', re.I), 'bilanzergebnis'),
    (re.compile(r'bilanzsumme|summe\s+(?:aktiva|passiva)', re.I), 'bilanzsumme'),
]


def _canonical_row_key(desc: str) -> str:
    """Normalise a row label to the key used for cross-year row matching."""
    n = re.sub(r"\s+", " ", str(desc or "").strip()).lower()
    for pat, canon in _ROW_SYNONYMS:
        if pat.search(n):
            return canon
    return n
_TYPE_INT_MAP = {"Bilanz": 0, "GuV": 1, "Cashflow": 2, "Other": 99}
_TYPE_LABEL   = {0: "Bilanz", 1: "GuV", 2: "Cashflow", 99: "Other"}
