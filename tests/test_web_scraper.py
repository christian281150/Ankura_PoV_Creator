from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

WEB_DIR = Path(__file__).parents[1] / "py" / "acquire" / "web"
_SPEC = importlib.util.spec_from_file_location("lane_c_scraper", WEB_DIR / "scraper.py")
assert _SPEC and _SPEC.loader
_SCRAPER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SCRAPER
_SPEC.loader.exec_module(_SCRAPER)

PageClass = _SCRAPER.PageClass
TargetedWebScraper = _SCRAPER.TargetedWebScraper
TargetPage = _SCRAPER.TargetPage
WebScrapeResult = _SCRAPER.WebScrapeResult
classify_target_url = _SCRAPER.classify_target_url
extract_job_postings = _SCRAPER.extract_job_postings
_entity_candidates = _SCRAPER._entity_candidates


FIXTURES = Path(__file__).parent / "fixtures" / "web"


class FixtureFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name == "example.test":
            name = "home"
        if name == "karriere":
            name = "careers"
        path = FIXTURES / f"{name}.html"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return "<html><head><title>Target</title></head><body>target page</body></html>"


def test_scraper_fetches_only_targeted_page_classes_and_extracts_jobs() -> None:
    fetcher = FixtureFetcher()
    result = TargetedWebScraper(fetcher).scrape("https://example.test/")

    assert "https://example.test/blog" not in fetcher.calls
    assert len(result.pages) == 7
    assert {page.page_class for page in result.pages} == {
        PageClass.ABOUT, PageClass.LOCATIONS, PageClass.PRESS, PageClass.CAREERS,
        PageClass.PRODUCTS, PageClass.SUSTAINABILITY, PageClass.IMPRESSUM,
    }
    assert result.pages[-1].entity_candidates == ["Diensteanbieter: TK Store-Management GmbH, Bielefeld"]
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.title == "Head of Group Procurement"
    assert job.location == "Bielefeld"
    assert job.date_posted and job.date_posted.isoformat() == "2026-07-01"
    assert {signal.kind for signal in job.signals} == {"erp_migration", "procurement_centralisation", "new_position"}


# ---------------------------------------------------------------------------
# The five "thin" page classes: ABOUT / LOCATIONS / PRESS / PRODUCTS /
# SUSTAINABILITY get no structured extraction today -- only a flattened text
# blob. These tests pin real synthetic-fixture content through that path so a
# future change to _visible_text can't silently start losing content, and so
# it is visible in the suite that these classes are "fetch + dump text", not
# structured extraction like CAREERS/IMPRESSUM.
# ---------------------------------------------------------------------------

def _scrape_home() -> WebScrapeResult:
    return TargetedWebScraper(FixtureFetcher()).scrape("https://example.test/")


def _page(result: WebScrapeResult, page_class: str):
    matches = [p for p in result.pages if p.page_class == page_class]
    assert len(matches) == 1
    return matches[0]


def test_about_page_extracts_flattened_text_and_strips_script_and_style() -> None:
    page = _page(_scrape_home(), PageClass.ABOUT)
    assert page.title == "Über uns"
    assert "1919" in page.text
    assert "Bielefeld" in page.text
    assert "trackingId" not in page.text
    assert "not-content" not in page.text


def test_about_page_never_populates_entity_candidates_even_with_legal_form_text() -> None:
    # The fixture's body text contains "GmbH & Co. KG" -- proving entity_candidates
    # is gated on page_class == IMPRESSUM, not on whether the text matches the
    # legal-form regex.
    page = _page(_scrape_home(), PageClass.ABOUT)
    assert "GmbH" in page.text
    assert page.entity_candidates == []


def test_locations_page_extracts_flattened_text() -> None:
    page = _page(_scrape_home(), PageClass.LOCATIONS)
    assert page.title == "Standorte"
    for expected in ("Bielefeld", "Vlotho", "Hamburg"):
        assert expected in page.text
    assert page.entity_candidates == []


def test_press_page_text_has_no_structured_dates_extracted() -> None:
    # Spec wants a "dated own-voice event log" (§4 1c). Current extraction only
    # dumps flattened text -- the dates are present as text but there is no
    # date field, unlike JobPosting.date_posted for careers. This test documents
    # that gap rather than asserting a date field that doesn't exist.
    page = _page(_scrape_home(), PageClass.PRESS)
    assert page.title == "Presse"
    assert "01.03.2026" in page.text
    assert "Neue Kollektion vorgestellt" in page.text
    assert "15.11.2025" in page.text
    assert not hasattr(page, "date_posted")


def test_products_page_extracts_flattened_text() -> None:
    page = _page(_scrape_home(), PageClass.PRODUCTS)
    assert page.title == "Produkte"
    assert "Hemden" in page.text
    assert "Blusen" in page.text
    assert page.entity_candidates == []


def test_sustainability_page_extracts_flattened_text() -> None:
    page = _page(_scrape_home(), PageClass.SUSTAINABILITY)
    assert page.title == "Nachhaltigkeit"
    assert "GOTS" in page.text
    assert "OEKO-TEX" in page.text
    assert page.entity_candidates == []


# ---------------------------------------------------------------------------
# classify_target_url: matching rules, including a documented false-positive.
# ---------------------------------------------------------------------------

def test_classify_target_url_matches_ascii_and_umlaut_about_variants() -> None:
    assert classify_target_url("https://example.test/ueber-uns") == PageClass.ABOUT
    assert classify_target_url("https://example.test/über-uns") == PageClass.ABOUT
    assert classify_target_url("https://example.test/unternehmen/historie") == PageClass.ABOUT


def test_classify_target_url_is_case_insensitive_and_ignores_trailing_slash() -> None:
    assert classify_target_url("https://example.test/KARRIERE/") == PageClass.CAREERS
    assert classify_target_url("https://example.test/Karriere") == PageClass.CAREERS


def test_classify_target_url_ignores_query_and_fragment() -> None:
    assert classify_target_url("https://example.test/karriere?ref=nav#jobs") == PageClass.CAREERS
    assert classify_target_url("https://example.test/datenschutz?ref=nav#top") is None


def test_classify_target_url_returns_none_for_unmatched_path() -> None:
    assert classify_target_url("https://example.test/datenschutz") is None
    assert classify_target_url("https://example.test/blog/jahresrueckblick-2025") is None


def test_classify_target_url_has_a_known_substring_false_positive() -> None:
    """Documents a real gap, not desired behaviour: classify_target_url matches by
    substring-in-path, not by path segment. A blog slug that happens to contain
    "karriere" or "jobs" gets misclassified as the Karriere page class and would be
    fetched and run through job extraction, which is exactly the "scrape every page"
    failure mode AGENTS.md warns against ("Do not scrape every page of a company
    site. Target the page classes in spec §4.1c."). Flagged for the owning lane to
    decide on -- narrowing this to path-segment matching is a real behaviour change
    (it would also stop matching a legitimate "/karriere/software-engineer" job
    listing path unless segment-matching is done carefully), so it is left alone
    here rather than silently patched as part of a test-coverage pass.
    """
    assert classify_target_url("https://example.test/blog/karriere-tipps-2026") == PageClass.CAREERS
    assert classify_target_url("https://example.test/ratgeber/jobsuche-tipps") == PageClass.CAREERS


# ---------------------------------------------------------------------------
# Crawl containment: a richer distractor set than the single "/blog" link in
# the original test. StrictFetcher raises if the scraper ever requests a URL
# outside the whitelist, so an accidental widening of scope fails loudly.
# ---------------------------------------------------------------------------

class StrictFetcher:
    """Fetcher that fails the test immediately on any out-of-scope request."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        if url not in self._pages:
            raise AssertionError(f"unexpected fetch of out-of-scope URL: {url}")
        return self._pages[url]


_DISTRACTOR_ROOT_HTML = """<!doctype html><html><body><nav>
<a href="/ueber-uns">Über uns</a>
<a href="/standorte">Standorte</a>
<a href="/presse">Presse</a>
<a href="/karriere">Karriere</a>
<a href="/produkte">Produkte</a>
<a href="/nachhaltigkeit">Nachhaltigkeit</a>
<a href="/impressum">Impressum</a>
</nav>
<footer>
<a href="/impressum">Impressum (footer duplicate)</a>
<a href="/datenschutz">Datenschutz</a>
<a href="/agb">AGB</a>
<a href="/blog/post-1">Blog Post 1</a>
<a href="/blog/post-2">Blog Post 2</a>
<a href="https://external.example/impressum">External Impressum</a>
<a href="mailto:info@example.test">Mail us</a>
<a href="tel:+491234567">Call us</a>
<a href="javascript:void(0)">No-op</a>
<a href="#top">Back to top</a>
</footer>
</body></html>"""

_MINIMAL_TARGET_HTML = "<html><head><title>Target</title></head><body>content</body></html>"


def test_scraper_only_ever_fetches_root_and_the_seven_targeted_classes() -> None:
    root_url = "https://example.test/"
    pages = {
        root_url: _DISTRACTOR_ROOT_HTML,
        "https://example.test/ueber-uns": _MINIMAL_TARGET_HTML,
        "https://example.test/standorte": _MINIMAL_TARGET_HTML,
        "https://example.test/presse": _MINIMAL_TARGET_HTML,
        "https://example.test/karriere": _MINIMAL_TARGET_HTML,
        "https://example.test/produkte": _MINIMAL_TARGET_HTML,
        "https://example.test/nachhaltigkeit": _MINIMAL_TARGET_HTML,
        "https://example.test/impressum": _MINIMAL_TARGET_HTML,
    }
    fetcher = StrictFetcher(pages)
    result = TargetedWebScraper(fetcher).scrape(root_url)

    # Exactly 8 fetches: the root, plus each of the 7 targets once each -- the
    # duplicated /impressum link (nav + footer) must collapse to a single fetch.
    assert len(fetcher.calls) == 8
    assert fetcher.calls.count(root_url) == 1
    for target in list(pages)[1:]:
        assert fetcher.calls.count(target) == 1

    # Distractors never fetched under any circumstance.
    for out_of_scope in (
        "https://example.test/datenschutz",
        "https://example.test/agb",
        "https://example.test/blog/post-1",
        "https://example.test/blog/post-2",
        "https://external.example/impressum",
    ):
        assert out_of_scope not in fetcher.calls

    # mailto:/tel:/javascript: links are dropped before classification (no netloc
    # match), so they never surface anywhere -- not fetched, not even skipped.
    joined_skipped = " ".join(result.skipped_links)
    for scheme_link in ("mailto:", "tel:", "javascript:"):
        assert scheme_link not in joined_skipped

    assert "https://example.test/datenschutz" in result.skipped_links
    assert "https://example.test/agb" in result.skipped_links
    assert "https://example.test/blog/post-1" in result.skipped_links
    assert "https://example.test/blog/post-2" in result.skipped_links
    assert "https://external.example/impressum" not in result.skipped_links

    # Quirk, documented not fixed: the fragment self-link "#top" normalises back
    # to the root URL, which doesn't match any rule token, so the root URL also
    # shows up in skipped_links even though it was fetched directly. Harmless --
    # it does not cause a second fetch -- but worth pinning so a future change to
    # this codepath doesn't turn it into a real double-fetch.
    assert root_url in result.skipped_links

    assert len(result.pages) == 7


# ---------------------------------------------------------------------------
# extract_job_postings: JSON-LD / card fallback / dedup / date parsing edge
# cases beyond the one JSON-LD job already covered by the main fixture test.
# ---------------------------------------------------------------------------

_KARRIERE_URL = "https://example.test/karriere"


def test_extract_job_postings_falls_back_to_cards_when_json_ld_is_malformed() -> None:
    html = """<html><head><title>Karriere</title>
<script type="application/ld+json">{"@type": "JobPosting", title: "Broken JSON"}</script>
</head><body>
<article class="stelle-card">
<h3>Bilanzbuchhalter (m/w/d)</h3>
<div class="location">Vlotho</div>
<p>Sanierung des Standorts, Interim-Unterstuetzung gesucht.</p>
</article>
</body></html>"""
    jobs = extract_job_postings(html, _KARRIERE_URL)
    assert len(jobs) == 1
    assert jobs[0].title == "Bilanzbuchhalter (m/w/d)"
    assert jobs[0].location == "Vlotho"
    assert "interim_or_restructuring" in {s.kind for s in jobs[0].signals}


def test_extract_job_postings_card_based_fallback_with_no_json_ld_at_all() -> None:
    html = """<html><body>
<div class="job-listing">
<h2>Leiter Einkauf (m/w/d)</h2>
<a href="/jobs/leiter-einkauf">Details</a>
<p>Sie zentralisieren den Einkauf standortuebergreifend.</p>
</div>
</body></html>"""
    jobs = extract_job_postings(html, _KARRIERE_URL)
    assert len(jobs) == 1
    assert jobs[0].title == "Leiter Einkauf (m/w/d)"
    assert jobs[0].url == "https://example.test/jobs/leiter-einkauf"
    assert jobs[0].location is None
    assert {s.kind for s in jobs[0].signals} == {"procurement_centralisation"}


def test_extract_job_postings_multiple_json_ld_jobs_on_one_page() -> None:
    payload = json.dumps([
        {"@type": "JobPosting", "title": "Bilanzbuchhalter (m/w/d)",
         "description": "Unterstuetzung im Tagesgeschaeft.", "datePosted": "2026-01-10"},
        {"@type": "JobPosting", "title": "Leiter Einkauf (m/w/d)",
         "description": "Sie zentralisieren den Einkauf.", "datePosted": "2026-02-05"},
    ])
    html = f'<html><head><title>Karriere</title><script type="application/ld+json">{payload}</script></head><body></body></html>'
    jobs = extract_job_postings(html, _KARRIERE_URL)
    assert {j.title for j in jobs} == {"Bilanzbuchhalter (m/w/d)", "Leiter Einkauf (m/w/d)"}
    by_title = {j.title: j for j in jobs}
    assert by_title["Bilanzbuchhalter (m/w/d)"].signals == []
    assert {s.kind for s in by_title["Leiter Einkauf (m/w/d)"].signals} == {"procurement_centralisation"}


def test_extract_job_postings_dedups_repeated_title_and_url() -> None:
    payload = json.dumps([
        {"@type": "JobPosting", "title": "Bilanzbuchhalter (m/w/d)",
         "description": "Erste Fassung.", "url": "/jobs/bilanzbuchhalter"},
        {"@type": "JobPosting", "title": "bilanzbuchhalter (m/w/d)",
         "description": "Zweite, doppelte Fassung mit gleicher URL.", "url": "/jobs/bilanzbuchhalter"},
    ])
    html = f'<html><head><title>Karriere</title><script type="application/ld+json">{payload}</script></head><body></body></html>'
    jobs = extract_job_postings(html, _KARRIERE_URL)
    assert len(jobs) == 1
    assert jobs[0].title == "Bilanzbuchhalter (m/w/d)"
    assert jobs[0].description == "Erste Fassung."


def test_extract_job_postings_invalid_date_posted_becomes_none_not_a_crash() -> None:
    html = ('<html><head><title>Karriere</title>'
            '<script type="application/ld+json">{"@type": "JobPosting", "title": "Werkstudent Controlling", '
            '"description": "Unterstuetzung im Reporting.", "datePosted": "not-a-date"}</script>'
            '</head><body></body></html>')
    jobs = extract_job_postings(html, _KARRIERE_URL)
    assert len(jobs) == 1
    assert jobs[0].date_posted is None


def _single_job_html(description: str) -> str:
    payload = json.dumps({"@type": "JobPosting", "title": "Testrolle", "description": description})
    return f'<html><head><title>Karriere</title><script type="application/ld+json">{payload}</script></head><body></body></html>'


def test_job_signal_erp_migration_fires_in_isolation() -> None:
    jobs = extract_job_postings(_single_job_html("Sie verantworten die ERP-Migration auf S/4HANA."), _KARRIERE_URL)
    assert {s.kind for s in jobs[0].signals} == {"erp_migration"}


def test_job_signal_procurement_centralisation_fires_in_isolation() -> None:
    jobs = extract_job_postings(_single_job_html("Sie zentralisieren den Einkauf standortuebergreifend."), _KARRIERE_URL)
    assert {s.kind for s in jobs[0].signals} == {"procurement_centralisation"}


def test_job_signal_finance_rebuild_fires_in_isolation() -> None:
    jobs = extract_job_postings(_single_job_html("Sie bauen den Bereich Finance in dieser Rolle neu auf."), _KARRIERE_URL)
    assert {s.kind for s in jobs[0].signals} == {"finance_rebuild"}


def test_job_signal_interim_or_restructuring_fires_in_isolation() -> None:
    jobs = extract_job_postings(_single_job_html("Wir suchen einen Interim Manager fuer die Sanierung des Standorts."), _KARRIERE_URL)
    assert {s.kind for s in jobs[0].signals} == {"interim_or_restructuring"}


def test_job_signal_new_position_fires_in_isolation() -> None:
    jobs = extract_job_postings(_single_job_html("Diese neu geschaffene Position berichtet direkt an die Geschaeftsfuehrung."), _KARRIERE_URL)
    assert {s.kind for s in jobs[0].signals} == {"new_position"}


def test_job_signal_none_for_bland_description() -> None:
    jobs = extract_job_postings(_single_job_html("Wir suchen eine Reinigungskraft fuer unser Werk in Vlotho. Teilzeit moeglich."), _KARRIERE_URL)
    assert jobs[0].signals == []


# ---------------------------------------------------------------------------
# _entity_candidates: the regex/sentence-split behaviour behind Impressum
# extraction, including a real gap the split introduces.
# ---------------------------------------------------------------------------

def test_entity_candidates_extracts_clean_legal_form_sentences() -> None:
    text = ("Diensteanbieter: TK Store-Management GmbH, Bielefeld. "
            "Seidensticker Vertriebs AG, Zuerich. Kontakt: Herr Mueller.")
    assert _entity_candidates(text) == [
        "Diensteanbieter: TK Store-Management GmbH, Bielefeld",
        "Seidensticker Vertriebs AG, Zuerich",
    ]


def test_entity_candidates_dedups_exact_repeats() -> None:
    text = "Diensteanbieter: Muster GmbH, Berlin. Diensteanbieter: Muster GmbH, Berlin."
    assert _entity_candidates(text) == ["Diensteanbieter: Muster GmbH, Berlin"]


def test_entity_candidates_ignores_sentences_without_a_legal_form() -> None:
    text = "Kontakt: Herr Mueller. Adresse: Musterstrasse 1, 12345 Musterstadt."
    assert _entity_candidates(text) == []


def test_entity_candidates_fragments_abbreviations_with_internal_periods_known_gap() -> None:
    """Documents a real gap, not desired behaviour: sentence splitting on "." also
    splits inside "GmbH & Co. KG" (at the "Co." abbreviation) and inside "e. K."
    (at both periods), because the splitter and the legal-form regex both key off
    the same character. The GmbH & Co. KG case still leaves two matchable-but-torn
    fragments; the e. K. case is worse -- the periods the regex needs are consumed
    by the split, so an e. K. entity is never captured at all. Flagged for the
    owning lane; not fixed here since repairing it means teaching the splitter
    about abbreviations, a real behaviour change out of scope for a test pass.
    """
    co_kg_text = "Muttergesellschaft: Seidensticker Gruppe GmbH & Co. KG, Bielefeld."
    assert _entity_candidates(co_kg_text) == [
        "Muttergesellschaft: Seidensticker Gruppe GmbH & Co",
        "KG, Bielefeld",
    ]

    e_k_text = "Einzelunternehmen Beispiel e. K., Muenster."
    assert _entity_candidates(e_k_text) == []


# ---------------------------------------------------------------------------
# Tripwire: AGENTS.md's hard rule ("Do not treat an Impressum as a
# corporate-structure source") currently holds only because nothing in this
# repo consumes entity_candidates yet -- py/entity/ does not read it. This test
# pins the current contract shape so that wiring a consumer later is a
# conscious act, not a silent one: if someone renames/repurposes
# entity_candidates into a singular "resolved" field, or adds a resolved-entity
# field to WebScrapeResult, this test breaks and forces them to read this
# comment and AGENTS.md's rule before proceeding.
# ---------------------------------------------------------------------------

def test_impressum_entity_candidates_are_not_wired_as_authoritative_tripwire() -> None:
    # 1. The schema itself is candidate-framed (plural list), never a singular
    #    resolved-entity field, on either model that crosses this module's boundary.
    assert set(TargetPage.model_fields) == {"page_class", "url", "title", "text", "entity_candidates"}
    assert set(WebScrapeResult.model_fields) == {"pages", "jobs", "skipped_links"}

    # 2. Behaviourally: even a page containing legal-form-bearing text (the About
    #    fixture mentions "GmbH & Co. KG") never gets entity_candidates populated
    #    unless it is actually the impressum page class.
    result = _scrape_home()
    for page in result.pages:
        if page.page_class == PageClass.IMPRESSUM:
            assert page.entity_candidates, "impressum page should carry candidates"
        else:
            assert page.entity_candidates == [], (
                f"{page.page_class} page must never carry entity_candidates -- "
                "only impressum may, and even then only as candidates, never as "
                "a resolved entity (AGENTS.md: 'Do not treat an Impressum as a "
                "corporate-structure source.')"
            )
