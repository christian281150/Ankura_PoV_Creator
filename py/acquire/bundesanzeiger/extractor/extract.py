"""PDF table extraction (pdfplumber + heuristics) and statement classification."""

import re
from collections import Counter
from pathlib import Path
from typing import Optional
import pdfplumber
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn

from ._core import console


def _normalise_detection_text(text: str) -> str:
    """Return PDF text in a form suitable for deterministic evidence checks."""
    return " ".join(str(text or "").lower().split())


def _detect_filing_basis(pdf: pdfplumber.PDF) -> dict[str, object]:
    """Detect accounting framework and P&L method from filing evidence.

    Framework is deliberately detected only from an explicit accounting-basis
    statement.  The method may additionally be detected from an unambiguous
    P&L signature.  An absent or conflicting signal remains ``unknown``.
    """
    pages = [(number, page.extract_text() or "") for number, page in enumerate(pdf.pages, 1)]
    framework_signals: list[tuple[str, int, str]] = []
    method_signals: list[tuple[str, int, str]] = []

    for page_number, text in pages:
        normalised = _normalise_detection_text(text)
        if ("ifrs accounting standards" in normalised
                or "international financial reporting standards" in normalised
                or ("§ 315e" in normalised and "ifrs" in normalised)):
            framework_signals.append(("ifrs", page_number, "explicit_accounting_basis"))
        hgb_basis = (
            "deutschen handelsrechtlichen rechnungslegungsvorschriften" in normalised
            or "nach den vorschriften des hgb aufgestellt" in normalised
            or bool(re.search(r"(?:konzern|jahres)abschluss.{0,100}?(?:ist|wird|wurde).{0,100}?(?:nach|gemäß|gemaess).{0,100}?"
                              r"(?:hgb|handelsgesetzbuch|handelsrechtlichen)", normalised))
        )
        if hgb_basis and "ifrs" not in normalised:
            framework_signals.append(("hgb", page_number, "explicit_accounting_basis"))

        if "nach dem gesamtkostenverfahren" in normalised or "§ 275 abs. 2 hgb" in normalised:
            method_signals.append(("gkv", page_number, "explicit_declaration"))
        if "nach dem umsatzkostenverfahren" in normalised or "§ 275 abs. 3 hgb" in normalised:
            method_signals.append(("ukv", page_number, "explicit_declaration"))

    framework_values = {value for value, _, _ in framework_signals}
    framework = next(iter(framework_values)) if len(framework_values) == 1 else "unknown"
    framework_evidence = next(({
        "page": page, "reason": reason,
    } for value, page, reason in framework_signals if value == framework), None)

    explicit_method_values = {value for value, _, reason in method_signals if reason == "explicit_declaration"}
    if len(explicit_method_values) == 1:
        pnl_method = next(iter(explicit_method_values))
        method_evidence = next({"page": page, "reason": reason}
                               for value, page, reason in method_signals if value == pnl_method)
    elif len(explicit_method_values) > 1:
        pnl_method, method_evidence = "unknown", None
    else:
        # Table labels are evaluated only after statement extraction below.
        # A mention in an Anhang note is not an unambiguous P&L signature.
        pnl_method, method_evidence = "unknown", None

    return {
        "framework": framework,
        "pnl_method": pnl_method,
        "framework_evidence": framework_evidence,
        "pnl_method_evidence": method_evidence,
    }


def _detect_method_from_statement_signature(tables: list[dict]) -> dict[str, object] | None:
    """Return a method only for an unambiguous extracted primary P&L table."""
    pnl_tables = [table for table in tables if _classify_table(table) == 1]
    if not pnl_tables:
        return None
    primary = max(pnl_tables, key=lambda table: len(table.get("rows") or []))
    labels = " ".join(_normalise_detection_text(row[0]) for row in primary.get("rows", [])[1:] if row)
    gkv_terms = ("materialaufwand", "personalaufwand", "veränderung des bestands",
                 "veraenderung des bestands", "andere aktivierte eigenleistungen")
    ukv_terms = ("umsatzkosten", "vertriebskosten", "allgemeine verwaltungskosten")
    gkv_hits = sum(term in labels for term in gkv_terms)
    gkv_hits += bool(re.search(r"bestandsver.nderung", labels))
    ukv_hits = sum(term in labels for term in ukv_terms)
    if gkv_hits >= 2 and ukv_hits < 2:
        return {"pnl_method": "gkv", "pnl_method_evidence": {"page": primary.get("page_start"),
                                                                   "reason": "statement_signature"}}
    if ukv_hits >= 2 and gkv_hits < 2:
        return {"pnl_method": "ukv", "pnl_method_evidence": {"page": primary.get("page_start"),
                                                                   "reason": "statement_signature"}}
    return None


def extract_tables_from_pdf(pdf_path: Path) -> Optional[list[dict]]:
    """
    Full extraction pipeline: PDF → structured table list.

    Pipeline stages
    ~~~~~~~~~~~~~~~
    1. Open PDF with pdfplumber.
    2. For each page, call find_tables() to get bounding boxes, then
       extract_tables() to get cell data.  Build a raw list of table dicts.
    3. _stitch_tables(): merge multi-page fragments.
    4. _split_mixed_tables(): separate fused Bilanz+GuV tables.
    5. _pin_key_tables(): move Bilanz to index 1, GuV to 2, KFR to 3.
    6. For each table: call _extract_heading() to get the section title from
       the PDF characters above the table.

    Each returned dict contains:
        index      int           1-based position after pinning
        heading    str           Section title extracted from PDF layout
        rows       list[list]    Cell values (strings / None)
        row_count  int
        col_count  int
        page_start int           1-based page number of first fragment
        page_end   int           1-based page number of last fragment
        framework  str           hgb | ifrs | unknown, from basis statement
        pnl_method str           gkv | ukv | unknown, from declaration/signature
        doc_label  str           Set by the GUI worker, e.g. "FY2024"
        preview    list[list]    First few rows (for display without rows)

    Args
    ----
    pdf_path : Path
        Path to a locally saved PDF file.

    Returns
    -------
    list[dict] | None
        List of table dicts (may be empty if no tables found).
        Returns None only if the PDF cannot be opened at all.
    """
    """
    Open PDF with pdfplumber and extract all non-empty tables.
    Uses find_tables() for bbox info, extracts headings above each table,
    then stitches fragments that span consecutive pages.
    Returns None on open failure, [] if no tables found.
    """
    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception as exc:
        console.print("[red]Cannot read PDF. File may be corrupt or password-protected.[/red]")
        console.print(f"[dim]Detail: {exc}[/dim]")
        return None

    detection = _detect_filing_basis(pdf)
    raw: list[dict] = []
    table_bboxes: dict[int, list[tuple]] = {}
    total_pages = len(pdf.pages)
    console.print(f"[cyan]Scanning {total_pages} pages for tables…[/cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting tables", total=total_pages)
        for page_num, page in enumerate(pdf.pages, 1):
            progress.update(task, advance=1, description=f"Page {page_num}/{total_pages}")
            found = page.find_tables()
            if not found:
                continue
            for tbl_obj in found:
                rows = tbl_obj.extract()
                if not rows:
                    continue
                cleaned = [
                    [cell if cell is not None else "" for cell in row]
                    for row in rows
                    if any(cell for cell in row)
                ]
                if not cleaned:
                    continue
                raw.append({
                    "page_start":   page_num,
                    "page_end":     page_num,
                    "page_height":  page.height,
                    "bbox":         tbl_obj.bbox,
                    "rows":         cleaned,
                    "row_pages":    [page_num] * len(cleaned),
                    "heading":      _extract_heading(page, tbl_obj.bbox),
                })
                table_bboxes.setdefault(page_num, []).append(tbl_obj.bbox)

    narratives = _extract_narrative_sections(pdf, table_bboxes)
    pdf.close()

    if not raw:
        console.print("[yellow]No structured tables detected. This PDF may use a "
                      "non-standard layout (common in scanned or designed reports).[/yellow]")
        console.print("[cyan]Falling back to bounding-box word grouping…[/cyan]")
        heuristic = _heuristic_word_extraction(pdf_path)
        if heuristic:
            for table in heuristic:
                table["index"] = len(narratives) + table["index"]
                table.update(detection)
            for narrative in narratives:
                narrative.update(detection)
            return narratives + heuristic
        if narratives:
            for narrative in narratives:
                narrative.update(detection)
            return narratives
        console.print("[red]Could not extract tables automatically. "
                      "Recommend opening the PDF manually.[/red]")
        return []

    # Stitch table fragments that span consecutive pages
    stitched = _stitch_tables(raw)
    # Split any table that contains multiple statements (e.g. Bilanz + GuV)
    stitched = _split_mixed_tables(stitched)

    # Drop tables with no numeric financial content (e.g. Aufsichtsratsbericht,
    # cover pages, footnote sections that pdfplumber reads as phantom tables).
    before = len(stitched)
    stitched = [t for t in stitched if _has_financial_content(t)]
    dropped = before - len(stitched)
    if dropped:
        console.print(f"[dim]Filtered out {dropped} text-only section(s) "
                      f"(no numeric content).[/dim]")

    if not stitched:
        if narratives:
            for narrative in narratives:
                narrative.update(detection)
            return narratives
        console.print("[yellow]No financial tables found in this PDF. "
                      "The document may contain only text (e.g. a supervisory-board "
                      "letter or cover page).[/yellow]")
        return []

    tables = []
    for i, table in enumerate(stitched, 1):
        source_rows = table["rows"]
        row_pages = table.get("row_pages") or [table["page_start"]] * len(source_rows)
        rows_with_pages = [
            list(row) + (["PDF Page"] if row_index == 0 else [row_pages[row_index]])
            for row_index, row in enumerate(source_rows)
        ]
        tables.append({
            "index":      i,
            "page_start": table["page_start"],
            "page_end":   table["page_end"],
            "rows":       rows_with_pages,
            "row_pages":  row_pages,
            "row_count":  len(rows_with_pages),
            "col_count":  max(len(row) for row in rows_with_pages),
            "heading":    table.get("heading", ""),
            "preview":    rows_with_pages[:2],
            **detection,
        })
    # Pin Bilanz → 1, GuV → 2, Kapitalfluss → 3
    tables = _pin_key_tables(tables)
    if detection["pnl_method"] == "unknown":
        signature_detection = _detect_method_from_statement_signature(tables)
        if signature_detection:
            detection.update(signature_detection)
            for table in tables:
                table.update(signature_detection)
    for index, narrative in enumerate(narratives, len(tables) + 1):
        narrative["index"] = index
        narrative.update(detection)
    return tables + narratives
_INTRO_RE = re.compile(
    r"^(die |das |der |im |in |für |folgende|nachfolgende|zur |es |dabei|"
    r"als |aus |hierbei|zudem|ferner|gemäß|sofern|soweit|aufgrund|"
    r"um die |um den |zur berechnung|berechnung|bestand)",
    re.IGNORECASE,
)
_DATE_ONLY_RE = re.compile(
    r"^\d{1,2}\.\s*(Januar|Februar|März|April|Mai|Juni|Juli|August"
    r"|September|Oktober|November|Dezember)\s+\d{4}$",
    re.IGNORECASE,
)
_BILANZ_END_RE = re.compile(
    r"\b(summe\s+passiva|bilanzsumme|gesamtpassiva|total\s+passiva"
    r"|summe\s+aktiva\s+und\s+passiva)\b",
    re.IGNORECASE,
)
_NEW_STMT_RE = re.compile(
    r"\b(umsatzerlöse?|kapitalflussrechnung|cashflow|cash\s+flow"
    r"|zahlungsstr[öo]me)\b",
    re.IGNORECASE,
)
_TABLE_CLASS_PATTERNS = [
    (0, re.compile(
        r"\b(konzernbilanz|jahresbilanz|bilanz|aktiva|passiva|bilanzsumme)\b",
        re.IGNORECASE)),
    (1, re.compile(
        r"\b(gewinn|verlust|ergebnis|umsatzerlöse?|gesamtergebnis"
        r"|ergebnisrechnung|konzernergebnis|gesamtergebnisrechnung)\b",
        re.IGNORECASE)),
    (2, re.compile(
        r"\b(kapitalfluss|cashflow|cash\s*flow|zahlungsstr[öo]me)\b",
        re.IGNORECASE)),
]

_NARRATIVE_SECTION_RE = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*|[A-ZÄÖÜ])\.?\s+)?(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
_NARRATIVE_HEADING_RE = re.compile(
    r"^(?:[A-ZÄÖÜ]\.|\d+(?:\.\d+)*\.?)\s+[^.!?:;]{2,120}$",
    re.IGNORECASE,
)
_LAGEBERICHT_START_RE = re.compile(r"^(?:konzern)?lagebericht\b", re.IGNORECASE)
_NARRATIVE_BOUNDARY_RE = re.compile(
    r"^(?:lagebericht|konzern(?:bilanz|[- ]?gewinn|[- ]?kapital|[- ]?eigen|anlagen)|"
    r"bestätigungsvermerk|geschäftsführung|wirtschaftsprüfungsgesellschaft|bielefeld,)\b",
    re.IGNORECASE,
)
_PAGE_FOOTER_RE = re.compile(r"\s+[–-]\s*Seite\s+\d+\s+von\s+\d+\s+[–-].*$", re.IGNORECASE)


def _char_in_table_bbox(char: dict, bbox: tuple) -> bool:
    """Whether a character is fully claimed by a detected table region."""
    x0, top, x1, bottom = bbox
    return (char.get("x0", -1) >= x0 and char.get("x1", -1) <= x1
            and char.get("top", -1) >= top and char.get("bottom", -1) <= bottom)


def _narrative_section(line: str) -> str:
    """Return a workbook-safe Lagebericht section heading, or an empty string."""
    compact = " ".join(str(line or "").split())
    match = _NARRATIVE_SECTION_RE.match(compact)
    if not match:
        return ""
    title = match.group("title").casefold()
    title_ascii = (title.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                    .replace("ß", "ss"))
    heading_like = bool(_NARRATIVE_HEADING_RE.match(compact))
    title_ascii = title.translate({
        ord(chr(0x00E4)): "ae", ord(chr(0x00F6)): "oe",
        ord(chr(0x00FC)): "ue", ord(chr(0x00DF)): "ss",
    })
    if title_ascii == "ertragslage" and (heading_like or compact.casefold() == title):
        return "Ertragslage"
    if (title_ascii in {"vermoegenslage", "vermoegens- und finanzlage"}
            and (heading_like or compact.casefold() == title)):
        return "Vermögenslage"
    if (title_ascii == "nachtragsbericht" or re.fullmatch(
            r"ereignisse?\s+nach\s+(?:dem\s+)?bilanzstichtag", title_ascii)) and heading_like:
        return "Nachtragsbericht"
    title = re.sub(r"^(?:[a-zäöü]\.|\d+(?:\.\d+)*\.?)\s+", "", title)
    if not (_NARRATIVE_HEADING_RE.match(compact)
            or title in {"ertragslage", "vermögenslage", "nachtragsbericht"}):
        return ""
    if title == "ertragslage":
        return "Ertragslage"
    if re.fullmatch(r"vermögens(?:lage|-\s+und\s+finanzlage)", title):
        return "Vermögenslage"
    if (title == "nachtragsbericht" or re.fullmatch(
            r"ereignisse?\s+nach\s+(?:dem\s+)?bilanzstichtag", title)):
        return "Nachtragsbericht"
    if re.fullmatch(r"(?:chancen\s*(?:[-–]\s*und\s*)?risikobericht|"
                    r"risiko\s*(?:[-–]\s*und\s*)?chancenbericht)", title):
        return "Chancen- und Risikobericht"
    return ""


def _unknown_narrative_section(line: str) -> str:
    """Return an explicit record name for an unrecognised Lagebericht heading."""
    compact = " ".join(str(line or "").split())
    if not _NARRATIVE_HEADING_RE.match(compact):
        return ""
    # Table rows commonly begin with a numbered item and end in an amount.
    if re.search(r"\s[-+]?\d[\d.,]*\s*$", compact):
        return ""
    return f"Unknown section: {compact}"


def _extract_narrative_sections(pdf, table_bboxes: dict[int, list[tuple]]) -> list[dict]:
    """Extract sectioned prose from page characters not occupied by tables.

    The page filter deliberately retains non-character objects so
    ``pdfplumber.Page.extract_text`` can perform its normal line reconstruction;
    only characters inside a table bbox are removed.  A narrative record has a
    page column for every paragraph, making it complementary to table output.
    """
    sections: list[dict[str, object]] = []
    active_section = ""
    active_rows: list[list] = []
    inside_lagebericht = False
    for page_number, page in enumerate(pdf.pages, 1):
        bboxes = table_bboxes.get(page_number, [])
        if bboxes:
            filtered_page = page.filter(
                lambda obj: obj.get("object_type") != "char"
                or not any(_char_in_table_bbox(obj, bbox) for bbox in bboxes))
        else:
            filtered_page = page
        lines = filtered_page.extract_text_lines(x_tolerance=3, y_tolerance=3)
        # Table detection can include a section heading in the table bbox.  Keep
        # those headings as boundary events, while continuing to exclude the
        # table body from narrative prose.
        visible_lines = {
            (round(float(line["top"]), 1), " ".join(line["text"].split()))
            for line in lines
        }
        for line in page.extract_text_lines(x_tolerance=3, y_tolerance=3):
            compact = " ".join(line["text"].split())
            key = (round(float(line["top"]), 1), compact)
            if key in visible_lines:
                continue
            if (_LAGEBERICHT_START_RE.match(compact) or _narrative_section(compact)
                    or _NARRATIVE_HEADING_RE.match(compact)):
                lines.append(line)
        lines.sort(key=lambda line: (float(line["top"]), float(line["x0"])))
        if not lines:
            continue

        paragraph_lines: list[str] = []
        previous_bottom: float | None = None

        def flush() -> None:
            if not active_section or not paragraph_lines:
                return
            paragraph = _PAGE_FOOTER_RE.sub("", " ".join(" ".join(paragraph_lines).split()))
            # A section title on its own is not narrative prose.
            if len(paragraph) >= 40:
                active_rows.append([page_number, paragraph])
            paragraph_lines.clear()

        def begin_section(heading: str) -> None:
            nonlocal active_section, active_rows
            flush()
            active_section = heading
            active_rows = []
            sections.append({"heading": heading, "rows": active_rows,
                             "page_start": page_number})

        for raw_line in lines:
            line = " ".join(raw_line["text"].split())
            if not line:
                flush()
                continue
            if _PAGE_FOOTER_RE.search(line) or line.startswith(("Tag der Erstellung:",
                                                                 "Auszug aus dem Unternehmensregister")):
                flush()
                continue
            top = float(raw_line["top"])
            if (previous_bottom is not None and paragraph_lines
                    and top - previous_bottom > 4):
                flush()
            previous_bottom = float(raw_line["bottom"])

            if _LAGEBERICHT_START_RE.match(line):
                flush()
                inside_lagebericht = True
                continue
            heading = _narrative_section(line)
            if heading:
                begin_section(heading)
                continue
            if _NARRATIVE_BOUNDARY_RE.match(line):
                flush()
                active_section = ""
                active_rows = []
                inside_lagebericht = False
                continue
            unknown_heading = _unknown_narrative_section(line) if inside_lagebericht else ""
            if unknown_heading:
                begin_section(unknown_heading)
                continue
            if active_section:
                paragraph_lines.append(line)
        flush()

    records: list[dict] = []
    for index, section in enumerate(sections, 1):
        heading = str(section["heading"])
        rows = section["rows"]
        records.append({
            "index": index,
            "heading": heading,
            "doc_label": "",
            "type": 99,
            "_override_applied": True,
            "narrative": True,
            "page_start": min((row[0] for row in rows), default=section["page_start"]),
            "page_end": max((row[0] for row in rows), default=section["page_start"]),
            "rows": [["Page", "Paragraph"]] + rows,
            "row_count": len(rows),
            "col_count": 2,
            "preview": rows[:2],
        })
    return records


def _chars_to_text(chars: list) -> str:
    """
    Reconstruct readable text from a list of pdfplumber character dicts.

    pdfplumber exposes individual glyph objects with x0/x1 bounding boxes.
    Naively joining ``char["text"]`` values loses word boundaries because PDF
    files store glyphs without explicit space characters.

    Algorithm
    ~~~~~~~~~
    Iterate character pairs.  If the gap between the right edge of char[i]
    and the left edge of char[i+1] exceeds 25 % of the average glyph width
    (or at least 0.5 pt), insert a space.  This threshold was chosen
    empirically on CeramTec and CTEC financial PDFs.

    Args
    ----
    chars : list[dict]
        pdfplumber character dicts, each containing at minimum
        ``{"text": str, "x0": float, "x1": float}``.

    Returns
    -------
    str
        Reconstructed string with inferred word spacing.
    """
    """
    Join a sorted char list into readable text.
    Inserts a space wherever the gap between two consecutive characters
    exceeds 25 % of the average character width — i.e. at word boundaries.
    """
    if not chars:
        return ""
    result = chars[0]["text"]
    for i in range(1, len(chars)):
        prev, curr = chars[i - 1], chars[i]
        gap = curr["x0"] - prev["x1"]
        avg_w = ((prev["x1"] - prev["x0"]) + (curr["x1"] - curr["x0"])) / 2
        if gap > max(avg_w * 0.25, 0.5):
            result += " "
        result += curr["text"]
    return result.strip()


def _extract_heading(page, table_bbox, look_above: float = 220.0) -> str:
    """
    Find the table's section title by scanning characters above it.

    Strategy:
    1. Determine body font size (most common size in the region).
    2. Group characters into lines; reconstruct each line's text with spaces.
    3. Collect lines in a heading font (larger than body or bold).
    4. Return the line with the LARGEST font size — this is the main title
       (e.g. "Konzernbilanz zum 31. Dezember 2024"), not a sub-label like "Aktiva".
    5. Fall back to the last non-introductory-sentence line if no heading font found.
    """
    _, y0, _, _ = table_bbox
    crop_top = max(0, y0 - look_above)
    if crop_top >= y0:
        return ""
    try:
        region = page.crop((0, crop_top, page.width, y0))
        chars = [c for c in region.chars if (c.get("text") or "").strip()]
        if not chars:
            return ""

        # Body font size = most common rounded size in the region
        sizes = [round(c.get("size", 8), 1) for c in chars]
        body_size: float = Counter(sizes).most_common(1)[0][0]

        # Group chars into lines by Y-coordinate (1 pt buckets)
        line_map: dict[int, list] = {}
        for c in chars:
            line_map.setdefault(int(c["top"]), []).append(c)

        # (y_key, text, max_size, is_bold)
        all_lines:     list[tuple] = []
        heading_lines: list[tuple] = []

        for y_key in sorted(line_map):
            lc = sorted(line_map[y_key], key=lambda c: c["x0"])
            text = _chars_to_text(lc)
            if not text or len(text) < 4:
                continue
            max_size = max(c.get("size", body_size) for c in lc)
            is_bold  = any("bold" in (c.get("fontname") or "").lower() for c in lc)
            all_lines.append((y_key, text, max_size, is_bold))
            if max_size > body_size + 0.4 or is_bold:
                heading_lines.append((y_key, text, max_size, is_bold))

        if heading_lines:
            # Pick the LARGEST-font line that is not a bare date string.
            # Bare dates ("31. Dezember 2024") are column headers, not titles.
            for _, text, _, _ in sorted(heading_lines, key=lambda x: x[2], reverse=True):
                if not _DATE_ONLY_RE.match(text.strip()):
                    return text[:100]
            # Every heading-font line was a date — fall through to non-intro fallback.

        # Fallback: last line that does not look like an introductory sentence
        for _, text, _, _ in reversed(all_lines):
            if not _INTRO_RE.match(text):
                return text[:100]

        return all_lines[-1][1][:100] if all_lines else ""

    except Exception:
        return ""


def _stitch_tables(raw: list[dict]) -> list[dict]:
    """
    Merge multi-page table fragments into single logical tables.

    Background
    ~~~~~~~~~~
    pdfplumber's find_tables() treats each page independently.  A wide
    financial table that spans pages 11–13 is returned as three separate
    fragments.  This function detects that pattern and joins them.

    Stitching criteria (all must hold)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    * The two fragments have the **same column count**.
    * The preceding fragment's bottom y-coordinate exceeds 72 % of the page
      height (table runs to near the bottom of the page).
    * The current fragment's top y-coordinate is less than 150 pt (table
      starts near the top of the next page — i.e. it continues immediately).
    * The pages are consecutive.

    Repeated header rows are detected and dropped: if the first row of a
    continuation fragment is identical to the first row of the primary fragment,
    it is a repeated column header and is removed before merging.

    Args
    ----
    raw : list[dict]
        Unsorted list of table dicts as produced by extract_tables_from_pdf's
        per-page loop.  Each dict must contain ``rows``, ``page_start``,
        ``page_end``, ``col_count``, and ``heading``.

    Returns
    -------
    list[dict]
        Tables after stitching.  Fragmented entries are removed; the merged
        entry carries the page_start of the first fragment and page_end of
        the last.
    """
    """
    Merge table fragments that continue across page boundaries.
    Criteria: consecutive pages, same column count, previous fragment ends
    near the page bottom, current fragment starts near the page top.
    Repeated header rows at the top of each continuation are dropped.
    """
    if not raw:
        return []
    result = [dict(raw[0])]
    for curr in raw[1:]:
        prev = result[-1]
        prev_cols = max(len(r) for r in prev["rows"]) if prev["rows"] else 0
        curr_cols = max(len(r) for r in curr["rows"]) if curr["rows"] else 0
        is_consecutive  = curr["page_start"] == prev["page_end"] + 1
        same_cols       = prev_cols == curr_cols and prev_cols > 0
        prev_ends_low   = prev["bbox"][3] > prev["page_height"] * 0.72
        curr_starts_high = curr["bbox"][1] < 150

        if is_consecutive and same_cols and prev_ends_low and curr_starts_high:
            cont_rows = curr["rows"]
            cont_pages = curr.get("row_pages") or [curr["page_start"]] * len(cont_rows)
            # Drop repeated header row if it matches the original first row
            if cont_rows and prev["rows"] and cont_rows[0] == prev["rows"][0]:
                cont_rows = cont_rows[1:]
                cont_pages = cont_pages[1:]
            prev["rows"].extend(cont_rows)
            prev.setdefault("row_pages", [prev["page_start"]] * (len(prev["rows"]) - len(cont_rows)))
            prev["row_pages"].extend(cont_pages)
            prev["page_end"]    = curr["page_end"]
            prev["bbox"]        = curr["bbox"]
            prev["page_height"] = curr["page_height"]
        else:
            result.append(dict(curr))
    return result


def _heuristic_word_extraction(pdf_path: Path) -> list[dict]:
    """
    Fallback: reconstruct table-like structures from word bounding boxes.
    Groups words by Y-coordinate proximity into rows.
    """
    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception:
        return []

    tables = []
    TOLERANCE = 3

    for page_num, page in enumerate(pdf.pages, 1):
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
        if not words:
            continue
        row_buckets: dict[float, list] = {}
        for word in words:
            y = round(word["top"] / TOLERANCE) * TOLERANCE
            row_buckets.setdefault(y, []).append(word)
        sorted_rows = [
            [w["text"] for w in sorted(row_buckets[y], key=lambda w: w["x0"])]
            for y in sorted(row_buckets.keys())
        ]
        if len(sorted_rows) < 2 or max(len(r) for r in sorted_rows) < 2:
            continue
        rows_with_pages = [
            list(row) + (["PDF Page"] if row_index == 0 else [page_num])
            for row_index, row in enumerate(sorted_rows)
        ]
        tables.append({
            "index":      len(tables) + 1,
            "page_start": page_num,
            "page_end":   page_num,
            "rows":       rows_with_pages,
            "row_pages":  [page_num] * len(rows_with_pages),
            "row_count":  len(rows_with_pages),
            "col_count":  max(len(r) for r in rows_with_pages),
            "heading":    "",
            "preview":    rows_with_pages[:2],
        })

    pdf.close()
    return tables
_STMT_NAME_RE = re.compile(
    r"(konzern.?(gesamtergebnis(?:rechnung)?|ergebnisrechnung|gewinn|verlust)"
    r"|gewinn.?und.?verlust(?:rechnung)?"
    r"|gesamtergebnis(?:rechnung)?"
    r"|kapitalfluss(?:rechnung)?|cashflow)",
    re.IGNORECASE,
)


def _classify_stmt_name(rows: list[list]) -> str:
    """Return a standard German statement label inferred from row content."""
    probe = " ".join(str(c) for row in rows[:20] for c in row).lower()
    is_konzern = "konzern" in probe or "konsolidiert" in probe
    if _TABLE_CLASS_PATTERNS[2][1].search(probe):
        return "Konzern-Kapitalflussrechnung" if is_konzern else "Kapitalflussrechnung"
    if _TABLE_CLASS_PATTERNS[1][1].search(probe):
        return "Konzern-Gesamtergebnisrechnung" if is_konzern else "Gewinn- und Verlustrechnung"
    if _TABLE_CLASS_PATTERNS[0][1].search(probe):
        return "Konzernbilanz" if is_konzern else "Bilanz"
    return ""


def _infer_heading_from_rows(rows: list[list]) -> str:
    """
    Try to extract a section title from the first rows of a split table section.
    Pass 1: a cell that contains a recognisable statement name.
    Pass 2: a single-cell row that looks like a generic title.
    """
    # Pass 1: cell contains a known financial-statement name
    for row in rows[:10]:
        for cell in row:
            cell_str = str(cell or "").strip()
            if _STMT_NAME_RE.search(cell_str) and 5 < len(cell_str) < 80:
                return cell_str[:100]
    # Pass 2: single non-empty cell, no leading digit, enough letters
    for row in rows[:6]:
        non_empty = [str(c).strip() for c in row if str(c).strip()]
        if len(non_empty) == 1:
            t = non_empty[0]
            if (len(t) > 8
                    and not re.match(r"^\d", t)
                    and re.search(r"[A-Za-züäöÜÄÖß]{4,}", t)):
                return t[:100]
    return ""
_BILANZ_CONTENT_RE = re.compile(
    r"\b(aktiva|passiva|anlageverm[öo]gen|umlaufverm[öo]gen"
    r"|verbindlichkeiten|eigenkapital|bilanzsumme|r[üu]ckstellungen)\b",
    re.IGNORECASE,
)
_GUV_START_RE = re.compile(
    r"\b(umsatzerlöse?|ergebnisrechnung|gewinn-?\s*und\s*verlust"
    r"|gesamtleistung|betriebsertrag|gesamtertrag)\b",
    re.IGNORECASE,
)
_FIN_NUM_IN_CELL_RE = re.compile(r"\d{1,3}(?:\.\d{3})+|\d+,\d+")


def _find_statement_splits(rows: list[list]) -> list[int]:
    """
    Return row indices where a new financial statement begins inside a merged
    table (e.g. Bilanz stitched with GuV across a page break).

    Strategy 1 — explicit boundary (preferred)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Find 'Summe Passiva' / 'Bilanzsumme' (end-of-Bilanz marker) and then the
    first GuV keyword after it.  Split at the row just after the Bilanz total.

    Strategy 2 — fallback when the total row has no text label
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Some PDFs render the Bilanzsumme as a numbers-only row (empty description
    cell), so Strategy 1 never fires.  Strategy 2 watches for Bilanz content
    keywords (Aktiva, Passiva, Verbindlichkeiten …) and, once seen, triggers a
    split when a GuV-start keyword (Umsatzerlöse, Ergebnisrechnung …) appears.
    It then walks backward from the GuV keyword row to absorb any preceding
    blank/header rows (no financial numbers in value columns) into the GuV part,
    so the GuV section starts cleanly at its own header rather than mid-Bilanz.
    """
    splits: list[int] = []

    # --- Strategy 1 ---
    bilanz_end_idx   = -1
    found_bilanz_end = False
    for i, row in enumerate(rows):
        row_text = " ".join(str(c) for c in row if c).strip()
        if not found_bilanz_end and _BILANZ_END_RE.search(row_text):
            found_bilanz_end = True
            bilanz_end_idx   = i
        elif found_bilanz_end and _NEW_STMT_RE.search(row_text):
            splits.append(bilanz_end_idx + 1)
            found_bilanz_end = False
            bilanz_end_idx   = -1

    if splits:
        return splits

    # --- Strategy 2 ---
    bilanz_seen = False
    for i, row in enumerate(rows):
        row_text = " ".join(str(c) for c in row if c).strip()
        if not bilanz_seen and _BILANZ_CONTENT_RE.search(row_text):
            bilanz_seen = True
            continue
        if bilanz_seen and _GUV_START_RE.search(row_text):
            # Walk backward from i to pull header / spacer rows into the GuV part.
            # A row is a "header or spacer" when its value columns (ci >= 1) contain
            # no German-formatted financial numbers.
            split_idx = i
            for back in range(i - 1, max(0, i - 6), -1):
                value_text = " ".join(
                    str(c) for c in rows[back][1:] if c
                ).strip()
                if not _FIN_NUM_IN_CELL_RE.search(value_text):
                    split_idx = back   # include this header/spacer in the GuV
                else:
                    break              # hit a real financial row — stop here
            splits.append(split_idx)
            bilanz_seen = False        # reset for any further splits in same table
    return splits


def _split_mixed_tables(tables: list[dict]) -> list[dict]:
    """
    Split tables that contain two financial statements merged into one.

    Problem
    ~~~~~~~
    On some PDFs the Bilanz and the following GuV start on the same physical
    page and pdfplumber detects them as a single table.  The result would be a
    giant "Bilanz" table that also contains the income statement rows, making
    both classification and Excel export incorrect.

    Detection
    ~~~~~~~~~
    _find_statement_splits() scans row text for "Summe Passiva" (or equivalent
    subtotals that mark the end of a balance sheet).  The row index immediately
    after that marker is recorded as a split point.

    Splitting
    ~~~~~~~~~
    For each split point the table is divided into two parts.  The first part
    retains the original heading; the second part gets a new heading via
    _infer_heading_from_rows() (looks for known statement-name keywords in the
    first 10 rows) or falls back to _classify_stmt_name() which uses the
    keyword-classification patterns to assign a standard German label.

    Args
    ----
    tables : list[dict]
        Output of _stitch_tables().

    Returns
    -------
    list[dict]
        Potentially longer list where previously merged tables are now separate.
    """
    """
    Split any table that contains multiple financial statements
    (e.g. Bilanz stitched together with GuV across a page break).
    """
    result: list[dict] = []
    for t in tables:
        splits = _find_statement_splits(t["rows"])
        if not splits:
            result.append(t)
            continue
        boundaries = [0] + splits + [len(t["rows"])]
        for j in range(len(boundaries) - 1):
            part_rows = t["rows"][boundaries[j]: boundaries[j + 1]]
            if not part_rows:
                continue
            part = dict(t)
            part["rows"] = part_rows
            part["row_pages"] = (t.get("row_pages") or [t["page_start"]] * len(t["rows"]))[
                boundaries[j]: boundaries[j + 1]]
            part["row_count"] = len(part_rows)
            if j > 0:
                heading = _infer_heading_from_rows(part_rows)
                if not heading:
                    heading = _classify_stmt_name(part_rows)
                part["heading"] = heading
            result.append(part)
    return result


def _has_financial_content(t: dict) -> bool:
    """
    Return True only when at least one value column contains 5 or more cells
    that parse as a financial number.

    Why per-column instead of a global count:
        Text-only sections (Aufsichtsratsbericht, cover pages, footnotes) may
        contain stray years like "2024" or list numbers like "1", "2", "3"
        which look like integers.  These appear at most once or twice in any
        single column.  A real Bilanz / GuV value column has 20–40 numbers.
        Requiring 5 in a single column is extremely unlikely to fire on prose
        and essentially certain to fire on any real financial statement.

    Columns 0 (description text) and the header row (ri == 0) are skipped.
    Dates like "01.01.2025" do NOT match because the groups after each dot
    are 2 digits, not 3 (German thousands require exactly 3-digit groups).
    """
    _FIN_NUM_RE = re.compile(
        r"^-?\s*\d{1,3}(?:\.\d{3})+(?:,\d+)?$"   # German thousands: 1.234 / 1.234,56
        r"|^-?\s*\d+,\d+$"                         # comma-decimal: 3,14
        r"|^-?\s*0$"                                # explicit zero
    )
    rows = t.get("rows", [])
    if not rows:
        return False
    max_cols = max(len(r) for r in rows)

    for ci in range(1, max_cols):          # skip col 0 (description)
        col_numeric = 0
        for ri, row in enumerate(rows):
            if ri == 0:                    # skip header row
                continue
            if ci >= len(row):
                continue
            val = (row[ci] or "").strip().replace("–", "-").replace("−", "-").replace(" ", "")
            if val and val not in ("-", "—", "0-") and _FIN_NUM_RE.match(val):
                col_numeric += 1
                if col_numeric >= 5:
                    return True
    return False


def _classify_table(t: dict) -> int:
    """
    Classify a table as one of four financial statement types.

    Uses keyword matching on the table's rows (cell text) rather than the
    heading alone so that tables with generic or missing headings are still
    classified correctly.

    Classification rules (first match wins)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    0 — Bilanz
        Rows contain "aktiva", "passiva", "bilanzsumme", "eigenkapital",
        "verbindlichkeiten", or "anlagevermögen".
    1 — GuV / Ergebnis
        Rows contain "umsatzerlöse", "jahresergebnis", "ergebnis",
        "gewinn", "verlust", "ebitda", "ebit", or "zinsergebnis".
    2 — Kapitalflussrechnung
        Rows contain "cashflow", "zahlungsmittel", "kapitalfluss",
        "investitionstätigkeit", or "finanzierungstätigkeit".
    99 — Other (Anhang, Eigenkapitalspiegel, notes tables, etc.)

    Args
    ----
    t : dict
        Table dict with at minimum a ``rows`` key (list[list[str|None]]).

    Returns
    -------
    int
        0, 1, 2, or 99.
    """
    """
    Return statement class for ordering:
      0 = Bilanz, 1 = GuV / Ergebnis, 2 = Kapitalflussrechnung, 99 = other
    """
    if t.get("multi_year"):
        return t.get("type", 99)

    h = (t.get("heading") or "").lower()

    # ── Phase 1: heading-only (high confidence) ───────────────────────────
    # KFR must precede GuV because indirect-method cashflow statements start
    # with "Jahresüberschuss" — a GuV keyword — but the heading is unambiguous.
    # Eigenkapitalveränderungsrechnung is forced to Sonstige before any check
    # because its rows contain "Jahresüberschuss" and "Gesamtergebnis".
    if re.search(r'\beigenkapital(?:veränder|spiegel|entwickl)', h):
        return 99  # equity changes statement → Sonstige
    if re.search(r'kapitalfluss|cashflow|cash\s*flow|\bzahlungsstr[öo]me\b', h):
        return 2   # KFR — heading is conclusive (no trailing \b: "Kapitalflussrechnung" is a compound word)
    if re.search(r'\b(konzernbilanz|jahresbilanz|bilanzsumme)\b', h):
        return 0   # Bilanz — strong heading keyword
    if re.search(r'\bbilanz\b', h) and not re.search(r'\berläuterung', h):
        return 0   # Bilanz (weaker) — but NOT notes to the balance sheet
    if re.search(r'\b(gewinn.*verlust|ergebnisrechnung|gesamtergebnisrechnung)\b', h):
        return 1   # GuV

    # ── Phase 2: row-content fallback (for tables with generic headings) ──
    # Scan 20 rows: indirect-method cashflow statements put "Cashflow aus
    # betrieblicher Tätigkeit" at row ~16, beyond the old 12-row window.
    rt = " ".join(str(c) for row in (t.get("rows") or [])[:20] for c in row).lower()

    # Bilanz first: "Eigenkapital" (bold total line) appears in rows 3-6 of the
    # equity section; \b word-boundary ensures we don't match
    # "Eigenkapitalveränderungsrechnung" row text.
    if re.search(r'\b(aktiva|passiva|bilanzsumme|anlagevermögen|summe\s+passiva)\b', rt):
        return 0
    if re.search(r'\beigenkapital\b', rt):
        return 0
    # KFR before GuV: cashflow tables are caught by section-subtotal labels
    # ("Finanzierungstätigkeit", "Investitionstätigkeit") and by indirect-method
    # specifics ("zahlungsunwirksam", "Ertragsteuerzahlung") that never appear
    # in GuV or Bilanz — critical because KFR starts with "Jahresüberschuss"
    # which would otherwise trigger the GuV check below.
    if re.search(
            r'kapitalfluss|cashflow|\bfinanzmittelfonds\b|\bzahlungsmittel\b'
            r'|\bfinanzierungstätigkeit\b|\binvestitionstätigkeit\b'
            r'|\bzahlungsunwirksam|\bertragsteuerzahlung\b', rt):
        return 2
    # GuV: only after ruling out Bilanz and KFR.
    # "verlust(?!vortrag|-)" excludes "Verlustvortrag" AND "Verlust-" (hyphenated
    # compounds like "Verlust- und Zinsvorträge" in deferred-tax notes tables).
    if re.search(
            r'\b(umsatzerlöse?|umsatzkosten|jahresüberschuss|jahresfehlbetrag'
            r'|ebitda|ebit\b|gewinn|verlust(?!vortrag|-))\b', rt):
        return 1

    return 99


def _pin_key_tables(tables: list[dict]) -> list[dict]:
    """
    Reorder so the primary Bilanz, GuV, and Kapitalfluss tables appear at
    positions 1, 2, 3.  'Primary' = largest (most rows) in each class.
    Secondary tables of the same class and all unclassified tables follow.
    Re-assigns sequential index numbers.
    """
    primary: dict[int, dict] = {}
    secondary: list[dict] = []

    for t in tables:
        cls = _classify_table(t)
        if cls in (0, 1, 2):
            if cls not in primary or len(t["rows"]) > len(primary[cls]["rows"]):
                if cls in primary:
                    secondary.append(primary[cls])
                primary[cls] = t
            else:
                secondary.append(t)
        else:
            secondary.append(t)

    ordered = [primary[c] for c in (0, 1, 2) if c in primary] + secondary
    for i, t in enumerate(ordered, 1):
        t["index"] = i
    return ordered


def effective_table_type(t: dict) -> int:
    """Statement type used for consolidation grouping.

    Honours a user's manual reclassification (``_override_applied`` with an
    explicit integer ``type``) over the automatic content classifier, so that
    flagging a table as 'Bilanz' in the GUI actually pulls it into the Bilanz
    consolidation for its year.
    """
    if t.get("_override_applied") and isinstance(t.get("type"), int):
        return t["type"]
    return _classify_table(t)
