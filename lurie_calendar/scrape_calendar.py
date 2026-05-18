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
PROFESSIONAL_EVENTS_FEED_URL = (
    "https://www.cancer.northwestern.edu/events/getEvents.php?q=lcc-e-professional"
)
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
MONTH_ALIASES = {
    "jan": "January",
    "january": "January",
    "feb": "February",
    "february": "February",
    "mar": "March",
    "march": "March",
    "apr": "April",
    "april": "April",
    "may": "May",
    "jun": "June",
    "june": "June",
    "jul": "July",
    "july": "July",
    "aug": "August",
    "august": "August",
    "sep": "September",
    "sept": "September",
    "september": "September",
    "oct": "October",
    "october": "October",
    "nov": "November",
    "november": "November",
    "dec": "December",
    "december": "December",
}


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


def absolute_http_url(url: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, url.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
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


def _normalized_text(tag: object | None, separator: str = " ") -> str:
    if tag is None:
        return ""
    get_text = getattr(tag, "get_text", None)
    if get_text is None:
        return ""
    return re.sub(r"\s+", " ", get_text(separator, strip=True)).strip()


def _month_year_from_heading(value: str) -> tuple[str | None, int | None]:
    match = re.search(r"\b([A-Za-z]+)\s+(20\d{2})\b", value)
    if not match:
        return None, None
    month = MONTH_ALIASES.get(match.group(1).lower())
    return month, int(match.group(2))


def _date_line(monthday: str, day_label: str, current_month: str | None, year: int | None) -> str:
    if year is None:
        return monthday
    month_match = re.match(r"\s*([A-Za-z]+)\s+(\d{1,2})", monthday)
    if month_match:
        month = MONTH_ALIASES.get(month_match.group(1).lower(), month_match.group(1))
        day = month_match.group(2)
    else:
        day_match = re.search(r"\d{1,2}", monthday)
        if not current_month or not day_match:
            return monthday
        month = current_month
        day = day_match.group(0)
    day_prefix = day_label.split("-", 1)[0].strip()
    prefix = f"{day_prefix}, " if day_prefix else ""
    return f"{prefix}{month} {day}, {year}"


def extract_professional_feed_links(html: str, feed_url: str) -> list[DiscoveredLink]:
    soup = BeautifulSoup(html, "html.parser")
    current_month: str | None = None
    current_year: int | None = None
    links: list[DiscoveredLink] = []

    for element in soup.find_all(["h2", "div"]):
        if element.name == "h2":
            current_month, current_year = _month_year_from_heading(element.get_text(" ", strip=True))
            continue
        classes = set(element.get("class", []))
        if "event" not in classes:
            continue

        anchor = element.select_one(".eventDetail h3 a")
        if anchor is None or not anchor.get("href"):
            continue
        href = absolute_http_url(anchor["href"], feed_url)
        if href is None:
            continue

        title = _normalized_text(anchor)
        series = _normalized_text(element.select_one(".eventDetail label"))
        speaker = _normalized_text(element.select_one(".eventDetail .subTitle"))
        location = _normalized_text(element.select_one(".eventLocation"), separator="\n")
        day_label = _normalized_text(element.select_one(".eventDate .day"))
        monthday = _normalized_text(element.select_one(".eventDate .monthday"))
        event_date = _date_line(monthday, day_label, current_month, current_year)

        context_lines = [
            title,
            "Source calendar: Lurie Cancer Center professional events feed",
            f"Series: {series}" if series else "",
            event_date,
            f"Speaker: {speaker}" if speaker else "",
            "Location:" if location else "",
            location,
        ]
        context_text = "\n".join(line for line in context_lines if line)
        display_parts = [part for part in (event_date, series, title, speaker, location) if part]
        links.append(
            DiscoveredLink(
                url=href,
                text=" | ".join(display_parts),
                source_url=feed_url,
                context_text=context_text,
                title=title or None,
            )
        )

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

    try:
        feed = fetch_text(client, PROFESSIONAL_EVENTS_FEED_URL)
        fetched_pages.append(feed.final_url)
        write_text_artifact(artifacts_dir, safe_artifact_name(PROFESSIONAL_EVENTS_FEED_URL), feed.text)
        discovered.extend(extract_professional_feed_links(feed.text, feed.final_url))
    except httpx.HTTPError:
        write_text_artifact(
            artifacts_dir,
            "professional_events_feed_error.txt",
            f"Could not fetch {PROFESSIONAL_EVENTS_FEED_URL}",
        )

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
