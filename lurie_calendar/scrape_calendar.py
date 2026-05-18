from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import httpx

from lurie_calendar.models import DiscoveredLink, FetchedPage

SOURCE_CALENDAR_URL = "https://www.cancer.northwestern.edu/events/index.html"
PROFESSIONAL_EDUCATION_URL = (
    "https://www.cancer.northwestern.edu/research/professional-education-events.html"
)
BASE_URL = "https://www.cancer.northwestern.edu/"
USER_AGENT = (
    "lurie-calendar-feed/0.1 "
    "(unofficial personal calendar; contact via https://github.com/10blade/lurie-calendar-feed)"
)

PROFESSIONAL_TERMS = (
    "professional",
    "grand rounds",
    "basic research seminar",
    "seminar series",
    "symposium",
    "conference",
    "oncology review",
    "cme",
    "continuing medical education",
    "clinician",
    "scientist",
    "healthcare professional",
    "lecture",
)
EXCLUDED_TERMS = (
    "patient",
    "community",
    "wellness",
    "fundraiser",
    "support group",
    "survivors celebration walk",
    "mindfulness",
)
IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js")


def build_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"},
    )


def safe_artifact_name(url: str, suffix: str = ".html") -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "index"
    path = re.sub(r"[^a-zA-Z0-9_.-]+", "_", path)
    if not path.endswith(suffix):
        path = f"{path}{suffix}"
    return path


def fetch_text(client: httpx.Client, url: str) -> FetchedPage:
    response = client.get(url)
    response.raise_for_status()
    return FetchedPage(
        url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        text=response.text,
    )


def write_text_artifact(artifacts_dir: Path | None, name: str, text: str) -> None:
    if artifacts_dir is None:
        return
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / name).write_text(text, encoding="utf-8")


def normalize_url(url: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, url.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"www.cancer.northwestern.edu", "cancer.northwestern.edu"}:
        return None
    parsed = parsed._replace(netloc="www.cancer.northwestern.edu")
    return parsed._replace(fragment="").geturl()


def extract_links_from_html(html: str, base_url: str) -> list[DiscoveredLink]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[DiscoveredLink] = []
    for tag in soup.find_all("a"):
        href = tag.get("href")
        if not href:
            continue
        normalized = normalize_url(href, base_url)
        if normalized is None:
            continue
        text = tag.get_text(" ", strip=True)
        links.append(DiscoveredLink(url=normalized, text=text, source_url=base_url))
    return links


def is_candidate_event_detail(url: str, text: str = "") -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if not path or path.endswith(IGNORED_EXTENSIONS) or path.endswith(".pdf"):
        return False
    if any(part in path for part in ("/registration-information", "/thank-you", "/donate")):
        return False
    if path in {"/events/", "/events/index.html", "/research/professional-education-events.html"}:
        return False
    combined = f"{path} {text}".lower()
    if "/events/public/" in path or "/events/patient" in path:
        return any(term in combined for term in PROFESSIONAL_TERMS) and not any(
            term in combined for term in EXCLUDED_TERMS
        )
    if "/events/professional/" in path:
        return True
    if "/events/" in path and any(term in combined for term in PROFESSIONAL_TERMS):
        return not any(term in combined for term in EXCLUDED_TERMS)
    return False


def _unique_links(links: Iterable[DiscoveredLink]) -> list[DiscoveredLink]:
    by_url: dict[str, DiscoveredLink] = {}
    for link in links:
        by_url.setdefault(link.url.rstrip("/"), link)
    return sorted(by_url.values(), key=lambda item: item.url)


def parse_sitemap_locations(xml_text: str) -> tuple[list[str], list[str]]:
    root = ElementTree.fromstring(xml_text)
    tag = root.tag.lower()
    urls: list[str] = []
    sitemaps: list[str] = []
    for loc in root.iter():
        if not loc.tag.lower().endswith("loc") or loc.text is None:
            continue
        value = loc.text.strip()
        if not value:
            continue
        if tag.endswith("sitemapindex"):
            sitemaps.append(value)
        else:
            urls.append(value)
    return urls, sitemaps


def discover_sitemap_links(
    client: httpx.Client,
    artifacts_dir: Path | None = None,
    max_nested_sitemaps: int = 12,
) -> list[DiscoveredLink]:
    candidates = [
        urljoin(BASE_URL, "sitemap.xml"),
        urljoin(BASE_URL, "sitemap_index.xml"),
        urljoin(BASE_URL, "sitemap-index.xml"),
    ]
    pending = list(candidates)
    seen: set[str] = set()
    discovered: list[DiscoveredLink] = []

    while pending and len(seen) < max_nested_sitemaps:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        try:
            response = client.get(sitemap_url)
            if response.status_code >= 400:
                continue
            xml_text = response.text
            write_text_artifact(artifacts_dir, safe_artifact_name(sitemap_url, ".xml"), xml_text)
            urls, nested = parse_sitemap_locations(xml_text)
        except (httpx.HTTPError, ElementTree.ParseError):
            continue

        for nested_url in nested:
            if nested_url not in seen:
                pending.append(nested_url)
        for url in urls:
            normalized = normalize_url(url, BASE_URL)
            if normalized and is_candidate_event_detail(normalized):
                discovered.append(
                    DiscoveredLink(url=normalized, text="sitemap", source_url=sitemap_url)
                )
    return _unique_links(discovered)


def discover_event_links(
    client: httpx.Client,
    artifacts_dir: Path | None = None,
    seed_urls: Iterable[str] | None = None,
) -> list[DiscoveredLink]:
    seeds = list(seed_urls or (SOURCE_CALENDAR_URL, PROFESSIONAL_EDUCATION_URL))
    discovered: list[DiscoveredLink] = []
    fetched_pages: list[str] = []

    for url in seeds:
        page = fetch_text(client, url)
        fetched_pages.append(page.final_url)
        write_text_artifact(artifacts_dir, safe_artifact_name(url), page.text)
        for link in extract_links_from_html(page.text, page.final_url):
            if is_candidate_event_detail(link.url, link.text):
                discovered.append(link)

    discovered.extend(discover_sitemap_links(client, artifacts_dir=artifacts_dir))
    unique = _unique_links(discovered)
    if artifacts_dir is not None:
        payload = {
            "scraped_at": datetime.now(UTC).isoformat(),
            "seed_urls": seeds,
            "fetched_pages": fetched_pages,
            "event_links": [link.__dict__ for link in unique],
        }
        write_text_artifact(
            artifacts_dir,
            "discovered_event_links.json",
            json.dumps(payload, indent=2, sort_keys=True),
        )
    return unique
