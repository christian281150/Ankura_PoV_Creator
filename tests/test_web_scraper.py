from __future__ import annotations

import importlib.util
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
