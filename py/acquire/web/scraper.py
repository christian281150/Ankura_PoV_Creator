"""Targeted company-site and job-posting extraction.

Only links belonging to the page classes defined in the product specification
are requested.  This module deliberately has no HTTP client dependency: a
caller supplies a :class:`Fetcher`, making acquisition testable from saved HTML
and keeping network policy outside parsing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Protocol
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field


class Fetcher(Protocol):
    """Minimal boundary around page retrieval."""

    def fetch(self, url: str) -> str:
        """Return the HTML document for *url* or raise a retrieval error."""


class PageClass(str):
    ABOUT = "about"
    LOCATIONS = "locations"
    PRESS = "press"
    CAREERS = "careers"
    PRODUCTS = "products"
    SUSTAINABILITY = "sustainability"
    IMPRESSUM = "impressum"


class TargetPage(BaseModel):
    page_class: str
    url: str
    title: str | None = None
    text: str
    entity_candidates: list[str] = Field(default_factory=list)


class JobSignal(BaseModel):
    kind: str
    evidence: str


class JobPosting(BaseModel):
    title: str
    url: str
    location: str | None = None
    date_posted: date | None = None
    description: str
    signals: list[JobSignal] = Field(default_factory=list)


class WebScrapeResult(BaseModel):
    pages: list[TargetPage]
    jobs: list[JobPosting]
    skipped_links: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _Rule:
    page_class: str
    path_tokens: tuple[str, ...]


_RULES = (
    _Rule(PageClass.ABOUT, ("ueber-uns", "über-uns", "unternehmen", "historie")),
    _Rule(PageClass.LOCATIONS, ("standorte", "locations", "kontakt")),
    _Rule(PageClass.PRESS, ("presse", "news")),
    _Rule(PageClass.CAREERS, ("karriere", "jobs")),
    _Rule(PageClass.PRODUCTS, ("produkte", "sortiment")),
    _Rule(PageClass.SUSTAINABILITY, ("nachhaltigkeit",)),
    _Rule(PageClass.IMPRESSUM, ("impressum",)),
)
_SPACE = re.compile(r"\s+")
_ENTITY_SUFFIX = re.compile(
    r"\b(?:GmbH(?:\s*&\s*Co\.?(?:\s*KG)?)?|AG|SE|KG|e\.\s*K\.)\b",
    re.IGNORECASE,
)


def _normalised_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "", ""))


def classify_target_url(url: str) -> str | None:
    """Return the permitted page class for *url*, or ``None`` if it is out of scope."""
    path = urlparse(url).path.lower()
    for rule in _RULES:
        if any(token in path for token in rule.path_tokens):
            return rule.page_class
    return None


def _visible_text(node: Tag | BeautifulSoup) -> str:
    for unwanted in node(["script", "style", "noscript", "template"]):
        unwanted.decompose()
    return _SPACE.sub(" ", node.get_text(" ", strip=True)).strip()


def _entity_candidates(text: str) -> list[str]:
    """Return legal-form-bearing text fragments, never a resolved entity."""
    candidates: list[str] = []
    for sentence in re.split(r"[\n.;]", text):
        if _ENTITY_SUFFIX.search(sentence):
            candidate = _SPACE.sub(" ", sentence).strip(" ,:-")
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _signals(text: str) -> list[JobSignal]:
    checks = (
        ("erp_migration", r"\b(?:sap\s*)?s/?4(?:hana)?\b|\berp[- ]?(?:migration|einführung|einfuehrung)\b"),
        ("procurement_centralisation", r"(?:\b(?:einkauf|procurement)\b.{0,80}\b(?:zentral|central|bündel|buendel)|\b(?:zentral|central|bündel|buendel)\w*.{0,80}\b(?:einkauf|procurement)\b)"),
        ("finance_rebuild", r"\b(?:finance|finanz|controlling)\b.{0,100}\b(?:aufbau|transform|neu auf|rebuild)"),
        ("interim_or_restructuring", r"\b(?:interim|restruktur|turnaround|sanierung)\b"),
        ("new_position", r"\bneu geschaffene(?:n|r)? position\b"),
    )
    found: list[JobSignal] = []
    for kind, pattern in checks:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found.append(JobSignal(kind=kind, evidence=match.group(0)))
    return found


def _json_jobs(soup: BeautifulSoup, page_url: str) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict) or value.get("@type") != "JobPosting":
                continue
            title = value.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            description = BeautifulSoup(str(value.get("description", "")), "html.parser").get_text(" ", strip=True)
            location_value = value.get("jobLocation")
            location = None
            if isinstance(location_value, dict):
                address = location_value.get("address")
                if isinstance(address, dict):
                    location = address.get("addressLocality")
            url = value.get("url") if isinstance(value.get("url"), str) else page_url
            jobs.append(JobPosting(title=title.strip(), url=urljoin(page_url, url), location=location,
                                   date_posted=_date(value.get("datePosted")), description=description,
                                   signals=_signals(f"{title} {description}")))
    return jobs


def _card_jobs(soup: BeautifulSoup, page_url: str) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for node in soup.select("article, li, div"):
        classes = " ".join(node.get("class", []))
        if not re.search(r"job|jobboard|stelle|career", classes, re.IGNORECASE):
            continue
        heading = node.find(["h1", "h2", "h3", "h4"])
        if heading is None:
            continue
        title = heading.get_text(" ", strip=True)
        if not title:
            continue
        text = _visible_text(node)
        link = node.find("a", href=True)
        location_node = node.select_one(".location, [data-location]")
        location = location_node.get_text(" ", strip=True) if location_node else None
        jobs.append(JobPosting(title=title, url=urljoin(page_url, link["href"]) if link else page_url,
                               location=location, description=text, signals=_signals(text)))
    return jobs


def extract_job_postings(html: str, page_url: str) -> list[JobPosting]:
    """Extract structured postings from a careers/jobs page without following job links."""
    soup = BeautifulSoup(html, "lxml")
    jobs = _json_jobs(soup, page_url) or _card_jobs(soup, page_url)
    unique: dict[tuple[str, str], JobPosting] = {}
    for job in jobs:
        unique.setdefault((job.title.casefold(), _normalised_url(job.url)), job)
    return list(unique.values())


class TargetedWebScraper:
    """Discover and fetch only spec-approved company-site pages."""

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher

    def scrape(self, site_url: str) -> WebScrapeResult:
        root_url = _normalised_url(site_url)
        root_html = self._fetcher.fetch(root_url)
        root = BeautifulSoup(root_html, "lxml")
        root_host = urlparse(root_url).netloc.casefold()
        targets: dict[str, str] = {}
        skipped: list[str] = []
        for anchor in root.select("a[href]"):
            candidate = _normalised_url(urljoin(root_url, unescape(anchor["href"])))
            if urlparse(candidate).netloc.casefold() != root_host:
                continue
            page_class = classify_target_url(candidate)
            if page_class is None:
                skipped.append(candidate)
            else:
                targets.setdefault(candidate, page_class)

        pages: list[TargetPage] = []
        jobs: list[JobPosting] = []
        for url, page_class in targets.items():
            html = self._fetcher.fetch(url)
            soup = BeautifulSoup(html, "lxml")
            text = _visible_text(soup)
            title_tag = soup.title
            entity_text = _visible_text(soup.body or soup)
            pages.append(TargetPage(page_class=page_class, url=url,
                                    title=title_tag.get_text(" ", strip=True) if title_tag else None,
                                    text=text,
                                    entity_candidates=_entity_candidates(entity_text)
                                    if page_class == PageClass.IMPRESSUM else []))
            if page_class == PageClass.CAREERS:
                jobs.extend(extract_job_postings(html, url))
        return WebScrapeResult(pages=pages, jobs=jobs, skipped_links=list(dict.fromkeys(skipped)))
