"""
hgb_lookup.py — Mapping helper for German account/label → HGB §266 / §275 positions.

Designed for downstream tools that ingest already-aggregated published statements
(Bilanz, GuV in either GKV or UKV form) OR raw account-level extracts (DATEV-style
Summen-/Saldenliste).

Features
--------
1. Account-number → HGB position (supports SKR03, SKR04, IKR).
2. Label → HGB position (German + English synonyms, normalization-tolerant).
3. **PnL format auto-detection** from a list of input labels (GKV vs UKV).
4. **GKV ↔ UKV bridge** with cost-center-allocation flags.
5. **Allocation warnings**: flags when a UKV lookup cannot be deterministic.

Usage
-----
>>> from hgb_lookup import HGBMapper
>>> m = HGBMapper(mapping_dir="./")
>>>
>>> # 1. Detect format from a list of statement labels
>>> labels = ["Umsatzerlöse", "Umsatzkosten", "Bruttoergebnis vom Umsatz", "Vertriebskosten"]
>>> m.detect_pnl_format(labels)
{'format': 'UKV', 'confidence': 'definitive', 'signals': [...]}
>>>
>>> # 2. Label lookup, format-aware
>>> m.lookup_label("Umsatzkosten", pnl_format="UKV")
{'hgb_code': 'PL_UKV-2', 'name_de': '2. Herstellungskosten der Umsatzerlöse', ...}
>>>
>>> # 3. Account lookup with UKV preference + allocation warning
>>> m.lookup_account("SKR04", 6010, use_ukv=True)
{'hgb_code': 'PL_UKV-5', 'allocation_required': True, 'allocation_warning': '...'}
>>>
>>> # 4. GKV → UKV bridge
>>> m.bridge_gkv_to_ukv("PL_GKV-6a")
{'ukv_codes': ['PL_UKV-2', 'PL_UKV-4', 'PL_UKV-5'], 'allocation_required': True, ...}
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _normalize(s: str) -> str:
    """Match ``lib.hgb_map.normalize`` when generating label keys."""
    s = str(s or "").strip()
    s = re.sub(r"-\s*\r?\n\s*", "", s)
    s = re.sub(r"\s*\((?:gkv|ukv)\)\s*$", "", s, flags=re.I)
    s = re.sub(
        r"^(?:\d+[A-Za-z]?\.\s+|[a-z]\)\s+|[IVXLCDM]+\.\s+|[A-Z]\.\s+)",
        "",
        s,
        count=1,
    )
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return "".join(c for c in s if c.isalnum())


_CONFIDENCE_WEIGHT = {"definitive": 10, "high": 4, "medium": 2, "neutral": 0, "low": 1}


@dataclass
class HGBMapper:
    mapping_dir: str = "."

    taxonomy: dict[str, dict] = field(default_factory=dict)
    ranges: dict[str, list[dict]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    bridge: dict[str, dict] = field(default_factory=dict)
    detection: dict[str, dict] = field(default_factory=dict)
    subtotals: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        base = Path(self.mapping_dir)

        with open(base / "hgb_taxonomy.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["is_subtotal"] = r.get("is_subtotal") == "True"
                r["ukv_allocation_required"] = r.get("ukv_allocation_required") == "True"
                self.taxonomy[r["hgb_code"]] = r

        with open(base / "account_ranges.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["account_low"] = int(r["account_low"])
                r["account_high"] = int(r["account_high"])
                r["sign_dependent"] = r["sign_dependent"] == "True"
                self.ranges.setdefault(r["skr_variant"], []).append(r)
        for v in self.ranges.values():
            v.sort(key=lambda r: r["account_low"])

        with open(base / "label_synonyms.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.labels[r["normalized_key"]] = r["hgb_code"]

        bp = base / "pnl_format_bridge.csv"
        if bp.exists():
            with open(bp, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    r["allocation_required"] = r["allocation_required"] == "True"
                    r["ukv_codes_list"] = [c.strip() for c in r["ukv_codes"].split(",") if c.strip()]
                    self.bridge[r["gkv_code"]] = r

        dp = base / "pnl_format_detection.csv"
        if dp.exists():
            with open(dp, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.detection[r["normalized_label"]] = r

        sp = base / "pnl_subtotals.csv"
        if sp.exists():
            with open(sp, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.subtotals[r["subtotal_code"]] = r

    # ============================================================
    # FORMAT DETECTION
    # ============================================================

    def detect_pnl_format(self, labels: list[str]) -> dict:
        """Detect GKV vs UKV from a list of P&L line labels.

        Returns dict with keys: format, confidence, gkv_score, ukv_score, signals.
        format ∈ {GKV, UKV, UNKNOWN, AMBIGUOUS}.
        """
        gkv_score = ukv_score = 0
        signals = []
        for raw in labels:
            key = _normalize(raw)
            rule = self.detection.get(key)
            if not rule:
                rule = next(
                    (v for k, v in self.detection.items()
                     if k and (k in key or key in k) and v["detected_format"] != "BOTH"),
                    None,
                )
            if not rule:
                continue
            w = _CONFIDENCE_WEIGHT.get(rule["confidence"], 0)
            if rule["detected_format"] == "GKV":
                gkv_score += w
            elif rule["detected_format"] == "UKV":
                ukv_score += w
            signals.append({
                "label": raw,
                "detected_format": rule["detected_format"],
                "confidence": rule["confidence"],
                "rationale": rule.get("rationale", ""),
            })

        if gkv_score == 0 and ukv_score == 0:
            return {"format": "UNKNOWN", "confidence": "none",
                    "gkv_score": 0, "ukv_score": 0, "signals": signals}

        defs = [s for s in signals if s["confidence"] == "definitive"]
        gkv_defs = [s for s in defs if s["detected_format"] == "GKV"]
        ukv_defs = [s for s in defs if s["detected_format"] == "UKV"]

        if gkv_defs and not ukv_defs:
            fmt, conf = "GKV", "definitive"
        elif ukv_defs and not gkv_defs:
            fmt, conf = "UKV", "definitive"
        elif gkv_defs and ukv_defs:
            fmt, conf = "AMBIGUOUS", "low"
        else:
            ratio = max(gkv_score, ukv_score) / max(1, min(gkv_score, ukv_score))
            if ratio >= 3:
                fmt = "GKV" if gkv_score > ukv_score else "UKV"
                conf = "high" if ratio >= 5 else "medium"
            else:
                fmt, conf = "AMBIGUOUS", "low"

        return {"format": fmt, "confidence": conf,
                "gkv_score": gkv_score, "ukv_score": ukv_score, "signals": signals}

    # ============================================================
    # LOOKUPS
    # ============================================================

    def lookup_account(
        self,
        skr_variant: str,
        account_no: int | str,
        use_ukv: bool = False,
    ) -> Optional[dict]:
        n = self._coerce(account_no)
        if n is None:
            return None
        variant_ranges = self.ranges.get(skr_variant.upper())
        if not variant_ranges:
            return None
        candidates = [r for r in variant_ranges if r["account_low"] <= n <= r["account_high"]]
        if not candidates:
            return None
        best = min(candidates, key=lambda r: r["account_high"] - r["account_low"])
        code = best["hgb_code_ukv"] if (use_ukv and best.get("hgb_code_ukv")) else best["hgb_code_default"]
        pos = self.taxonomy.get(code, {})

        allocation_warning = None
        if use_ukv and pos.get("ukv_allocation_required"):
            allocation_warning = (
                f"Account {n} maps to UKV position {code} ({pos.get('name_de', '')}). "
                "Without cost-center allocation the split across COGS / Vertrieb / Verwaltung is "
                "a best-effort default. For accurate UKV reporting, source the company's internal "
                "Kostenstellenrechnung."
            )

        return {
            "account_no": n,
            "skr_variant": skr_variant,
            "hgb_code": code,
            "hgb_code_default": best["hgb_code_default"],
            "hgb_code_ukv": best["hgb_code_ukv"] or None,
            "statement": pos.get("statement"),
            "pnl_format": pos.get("pnl_format"),
            "name_de": pos.get("name_de"),
            "name_en": pos.get("name_en"),
            "sign_dependent": best["sign_dependent"],
            "is_subtotal": pos.get("is_subtotal", False),
            "allocation_required": pos.get("ukv_allocation_required", False),
            "allocation_warning": allocation_warning,
            "hint": best["hint"],
        }

    def lookup_label(self, label: str, pnl_format: Optional[str] = None) -> Optional[dict]:
        """Map a German/English line-item label → HGB position.

        When `pnl_format` is provided ('GKV' or 'UKV'), the response includes a
        `format_match` boolean and a warning if the mapped position belongs to the
        other format (e.g. trying to map 'Materialaufwand' in a UKV statement).
        """
        key = _normalize(label)
        code = self.labels.get(key)
        if not code:
            for synkey, syncode in self.labels.items():
                if synkey and (synkey in key or key in synkey):
                    code = syncode
                    break
        if not code:
            return None

        pos = self.taxonomy.get(code, {})
        result = {
            "input_label": label,
            "hgb_code": code,
            "statement": pos.get("statement"),
            "pnl_format": pos.get("pnl_format"),
            "name_de": pos.get("name_de"),
            "name_en": pos.get("name_en"),
            "is_subtotal": pos.get("is_subtotal", False),
        }

        if pnl_format:
            pnl_format = pnl_format.upper()
            mapped_fmt = pos.get("pnl_format")
            if mapped_fmt in ("GKV", "UKV") and mapped_fmt != pnl_format:
                alt = None
                if mapped_fmt == "GKV" and pnl_format == "UKV":
                    b = self.bridge.get(code, {})
                    alt = b.get("ukv_codes_list", [])
                elif mapped_fmt == "UKV" and pnl_format == "GKV":
                    for gkv_code, b in self.bridge.items():
                        if code in b.get("ukv_codes_list", []):
                            alt = [gkv_code]
                            break
                result["format_match"] = False
                result["format_warning"] = (
                    f"Label '{label}' resolves to {mapped_fmt} position {code}, "
                    f"but statement was identified as {pnl_format}. "
                    f"Bridge candidates: {alt}"
                )
            else:
                result["format_match"] = True

        return result

    def get_position(self, hgb_code: str) -> Optional[dict]:
        return self.taxonomy.get(hgb_code)

    def bridge_gkv_to_ukv(self, gkv_code: str) -> Optional[dict]:
        b = self.bridge.get(gkv_code)
        if not b:
            return None
        return {
            "gkv_code": gkv_code,
            "ukv_codes": b["ukv_codes_list"],
            "allocation_required": b["allocation_required"],
            "allocation_method": b["allocation_method"],
            "notes": b.get("notes", ""),
        }

    def bridge_ukv_to_gkv(self, ukv_code: str) -> list[str]:
        return [g for g, b in self.bridge.items() if ukv_code in b.get("ukv_codes_list", [])]

    @staticmethod
    def _coerce(v) -> Optional[int]:
        s = str(v).strip()
        digits = ""
        for c in s:
            if c.isdigit():
                digits += c
            else:
                break
        return int(digits) if digits else None


# ============================================================
# DEMO
# ============================================================
if __name__ == "__main__":
    m = HGBMapper(mapping_dir=".")

    print("=" * 70)
    print("1. FORMAT DETECTION on your screenshot's labels (Konzern UKV)")
    print("=" * 70)
    screenshot_labels = [
        "Umsatzerlöse", "Umsatzkosten", "Bruttoergebnis vom Umsatz",
        "Vertriebskosten", "Forschungs- und Entwicklungskosten",
        "Allgemeine Verwaltungskosten", "Sonstige Erträge und Aufwendungen, netto",
        "Betriebsergebnis",
    ]
    det = m.detect_pnl_format(screenshot_labels)
    print(f"  Detected: {det['format']}  (confidence: {det['confidence']})")
    print(f"  GKV score: {det['gkv_score']}  |  UKV score: {det['ukv_score']}")

    print()
    print("=" * 70)
    print("2. FORMAT DETECTION on a Mittelstand GKV statement")
    print("=" * 70)
    gkv_labels = [
        "Umsatzerlöse", "Bestandsveränderungen", "Materialaufwand",
        "Personalaufwand", "Abschreibungen", "Sonstige betriebliche Aufwendungen",
    ]
    det = m.detect_pnl_format(gkv_labels)
    print(f"  Detected: {det['format']}  (confidence: {det['confidence']})")
    print(f"  GKV score: {det['gkv_score']}  |  UKV score: {det['ukv_score']}")

    print()
    print("=" * 70)
    print("3. FORMAT-AWARE LABEL LOOKUP — catches the cross-format trap")
    print("=" * 70)
    r = m.lookup_label("Materialaufwand", pnl_format="UKV")
    print(f"  lookup_label('Materialaufwand', pnl_format='UKV')")
    print(f"    HGB: {r['hgb_code']}  format: {r['pnl_format']}  format_match: {r.get('format_match')}")
    if r.get('format_warning'):
        print(f"    ⚠ {r['format_warning']}")

    print()
    print("=" * 70)
    print("4. GKV → UKV BRIDGE for cost-center-critical items")
    print("=" * 70)
    for code in ["PL_GKV-6a", "PL_GKV-7a", "PL_GKV-5a", "PL_GKV-13"]:
        b = m.bridge_gkv_to_ukv(code)
        pos = m.get_position(code)
        print(f"  {code:<12} ({pos['name_de'][:50]})")
        print(f"    → UKV: {b['ukv_codes']}   allocation_required: {b['allocation_required']}")

    print()
    print("=" * 70)
    print("5. ACCOUNT LOOKUP with UKV allocation warning")
    print("=" * 70)
    for skr, acct, ukv in [("SKR04", 6010, True), ("SKR04", 6010, False), ("SKR04", 4000, True)]:
        r = m.lookup_account(skr, acct, use_ukv=ukv)
        print(f"  {skr} {acct}, use_ukv={ukv}  →  {r['hgb_code']}  ({r['name_de'][:50]})")
        if r.get('allocation_warning'):
            print(f"    ⚠ allocation_required=True (see allocation_warning)")

    print()
    print("=" * 70)
    print("6. REVERSE BRIDGE: which GKV positions feed UKV-2 (Herstellungskosten)?")
    print("=" * 70)
    for s in m.bridge_ukv_to_gkv("PL_UKV-2"):
        p = m.get_position(s)
        print(f"  ← {s:<12} {p['name_de']}")
