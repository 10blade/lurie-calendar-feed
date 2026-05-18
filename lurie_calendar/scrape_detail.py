from __future__ import annotations

import json
import re
from pathlib import Path
from html import unescape
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from lurie_calendar.models import DetailPage
from lurie_calendar.scrape_calendar import safe_artifact_name, write_text_artifact

PDF_TEXT_HINTS = ("pdf", "agenda", "flyer", "brochure", "program")
REGISTRATION_HINTS = ("register", "registration", "rsvp", "sign up")


def _absolute_url(value: str, base_url: str) -> str | None:
    absolute = urljoin(base_url, value.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    return parsed._replace(fragment="").geturl()


def _is_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path.lower().endswith(".pdf") or ".pdf" in parsed.query.lower()


def _may_redirect_to_pdf(text: str, url: str) -> bool:
    combined = f"{text} {url}".lower()
    return any(hint in combined for hint in PDF_TEXT_HINTS)


def _head_is_pdf(client: httpx.Client, url: str) -> bool:
    try:
        response = client.head(url, follow_redirects=True)
        if response.status_code == 405:
            response = client.get(url, follow_redirects=True, headers={"Range": "bytes=0-0"})
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    content_type = response.headers.get("content-type", "").lower()
    return "application/pdf" in content_type or str(response.url).lower().endswith(".pdf")


def discover_pdf_urls(
    soup: BeautifulSoup,
    base_url: str,
    client: httpx.Client | None = None,
    check_redirects: bool = True,
) -> list[str]:
    urls: list[str] = []
    tag_attrs = (("a", "href"), ("iframe", "src"), ("embed", "src"), ("object", "data"))
    for tag_name, attr in tag_attrs:
        for tag in soup.find_all(tag_name):
            raw = tag.get(attr)
            if not raw:
                continue
            absolute = _absolute_url(raw, base_url)
            if absolute is None:
                continue
            text = tag.get_text(" ", strip=True)
            if _is_pdf_url(absolute):
                urls.append(absolute)
                continue
            if client is not None and check_redirects and _may_redirect_to_pdf(text, absolute):
                if _head_is_pdf(client, absolute):
                    urls.append(absolute)

    return sorted(dict.fromkeys(urls))


def discover_registration_url(soup: BeautifulSoup, base_url: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for tag in soup.find_all("a"):
        href = tag.get("href")
        if not href:
            continue
        absolute = _absolute_url(href, base_url)
        if absolute is None:
            continue
        text = tag.get_text(" ", strip=True).lower()
        url_lower = absolute.lower()
        score = 0
        if any(hint in text for hint in REGISTRATION_HINTS):
            score += 5
        if "cloud-cme.com" in url_lower or "lcc.northwestern.edu" in url_lower:
            score += 3
        if score:
            candidates.append((score, absolute))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def extract_visible_text(soup: BeautifulSoup) -> str:
    working = BeautifulSoup(str(soup), "html.parser")
    for selector in ("script", "style", "noscript", "nav", "header", "footer", "form"):
        for tag in working.select(selector):
            tag.decompose()
    text = working.get_text("\n", strip=True)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_canonical_url(soup: BeautifulSoup, base_url: str) -> str | None:
    for tag in soup.find_all("link"):
        rel = tag.get("rel", [])
        rel_values = [rel] if isinstance(rel, str) else list(rel)
        if "canonical" in {value.lower() for value in rel_values} and tag.get("href"):
            return _absolute_url(tag["href"], base_url)
    og_url = soup.find("meta", property="og:url")
    if og_url and og_url.get("content"):
        return _absolute_url(og_url["content"], base_url)
    return None


def extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        title = normalize_display_text(h1.get_text(" ", strip=True))
        if title:
            return title
    title_tag = soup.find("title")
    if not title_tag:
        return None
    title = normalize_display_text(title_tag.get_text(" ", strip=True))
    return re.sub(r"\s*:\s*Robert H\..*$", "", title).strip() or None


def normalize_display_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def extract_source_event_id(url: str, soup: BeautifulSoup) -> str | None:
    for meta_name in ("event-id", "event_id", "id"):
        meta = soup.find("meta", attrs={"name": meta_name})
        if meta and meta.get("content"):
            return meta["content"].strip()
    match = re.search(r"(?:event|id)[=-](\d{3,})", url, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def detail_from_html(
    html: str,
    detail_url: str,
    source_url: str | None = None,
    client: httpx.Client | None = None,
    check_pdf_redirects: bool = True,
    context_text: str | None = None,
    context_title: str | None = None,
) -> DetailPage:
    soup = BeautifulSoup(html, "html.parser")
    canonical_url = extract_canonical_url(soup, detail_url)
    pdf_urls = discover_pdf_urls(
        soup,
        detail_url,
        client=client,
        check_redirects=check_pdf_redirects,
    )
    visible_text = extract_visible_text(soup)
    if context_text:
        visible_text = f"{context_text}\n\n{visible_text}" if visible_text else context_text
    return DetailPage(
        source_url=source_url or detail_url,
        detail_url=detail_url,
        canonical_url=canonical_url,
        visible_text=visible_text,
        pdf_urls=pdf_urls,
        registration_url=discover_registration_url(soup, detail_url),
        html=html,
        title=extract_title(soup) or context_title,
        source_event_id=extract_source_event_id(detail_url, soup),
    )


def fetch_detail(
    client: httpx.Client,
    detail_url: str,
    source_url: str | None = None,
    artifacts_dir: Path | None = None,
    context_text: str | None = None,
    context_title: str | None = None,
) -> DetailPage:
    if _is_pdf_url(detail_url):
        visible_text = context_text or context_title or detail_url
        write_text_artifact(artifacts_dir, safe_artifact_name(detail_url, ".txt"), visible_text)
        return DetailPage(
            source_url=source_url or detail_url,
            detail_url=detail_url,
            canonical_url=None,
            visible_text=visible_text,
            pdf_urls=[detail_url],
            registration_url=None,
            html="",
            title=context_title,
            source_event_id=None,
        )

    response = client.get(detail_url)
    response.raise_for_status()
    html = response.text
    write_text_artifact(artifacts_dir, safe_artifact_name(detail_url), html)
    detail = detail_from_html(
        html,
        detail_url=str(response.url),
        source_url=source_url or detail_url,
        client=client,
        check_pdf_redirects=True,
        context_text=context_text,
        context_title=context_title,
    )
    if artifacts_dir is not None:
        write_text_artifact(
            artifacts_dir,
            f"{safe_artifact_name(detail_url, '.json')}",
            json.dumps(
                {
                    "detail_url": detail.detail_url,
                    "canonical_url": detail.canonical_url,
                    "pdf_urls": detail.pdf_urls,
                    "registration_url": detail.registration_url,
                    "title": detail.title,
                },
                indent=2,
                sort_keys=True,
            ),
        )
    return detail
