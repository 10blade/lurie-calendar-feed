from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5


CALENDAR_TIMEZONE = "America/Chicago"
UID_DOMAIN = "lurie-calendar-feed.github.io"
LURIE_HOSTS = frozenset({"www.cancer.northwestern.edu", "cancer.northwestern.edu"})

# Credentials that mark the end of a speaker's name in lines such as
# "Ronald Hoffman, MD, Icahn School of Medicine at Mount Sinai".
CREDENTIALS = frozenset(
    {
        "md", "phd", "do", "mph", "ms", "msc", "mba", "rn", "bsn", "msn", "dnp", "aprn", "np",
        "pa-c", "pharmd", "drph", "mbbs", "ma", "dsc", "scd", "jd", "facp", "fasco", "faan",
        "facs", "frcp", "frcpc", "ocn", "aocn", "aocns", "cns", "lcsw", "mhs", "msci", "msce",
        "mphil", "dphil", "mmsc", "dmin", "bcc", "mpp", "edd", "psyd", "dds", "dmd", "rph",
        "bcop", "cnp",
    }
)


@dataclass(frozen=True)
class FeedListing:
    """Structured fields from one row of Lurie's professional events listing."""

    title: str
    event_date: date | None = None
    series: str | None = None
    speaker: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    text: str
    source_url: str
    context_text: str | None = None
    title: str | None = None
    listing: FeedListing | None = None


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str


@dataclass
class DetailPage:
    source_url: str
    detail_url: str
    canonical_url: str | None
    visible_text: str
    pdf_urls: list[str]
    registration_url: str | None
    html: str
    title: str | None = None
    source_event_id: str | None = None
    listing: FeedListing | None = None


@dataclass
class PdfDocument:
    source_url: str
    final_url: str
    sha256: str
    text: str
    extractable_text: bool
    size_bytes: int
    content_type: str | None = None


@dataclass
class ParsedEvent:
    stable_uid: str | None
    source_event_id: str | None
    source_url: str
    detail_url: str | None
    pdf_url: str | None
    pdf_sha256: str | None
    title: str
    series: str | None
    speaker: str | None
    speaker_affiliation: str | None
    topic: str | None
    start_datetime: datetime
    end_datetime: datetime
    timezone: str
    location: str | None
    virtual_or_in_person: str | None
    registration_url: str | None
    description: str
    confidence: float
    last_seen_at: datetime
    scraped_at: datetime
    raw_source_excerpt: str
    sequence: int = 0
    last_modified_at: datetime | None = None
    status: str = "CONFIRMED"


@dataclass
class ReviewItem:
    reason: str
    source_url: str
    scraped_at: datetime
    detail_url: str | None = None
    pdf_url: str | None = None
    pdf_sha256: str | None = None
    title: str | None = None
    raw_source_excerpt: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def datetime_to_json(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def datetime_from_json(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def event_to_json(event: ParsedEvent) -> dict[str, Any]:
    data = asdict(event)
    for key in ("start_datetime", "end_datetime"):
        data[key] = data[key].isoformat()
    for key in ("last_seen_at", "scraped_at", "last_modified_at"):
        if data[key] is not None:
            data[key] = datetime_to_json(data[key])
    return data


def event_from_json(data: dict[str, Any]) -> ParsedEvent:
    normalized = dict(data)
    for key in ("start_datetime", "end_datetime", "last_seen_at", "scraped_at", "last_modified_at"):
        if normalized.get(key):
            normalized[key] = datetime_from_json(normalized[key])
    return ParsedEvent(**normalized)


def review_to_json(item: ReviewItem) -> dict[str, Any]:
    data = asdict(item)
    data["scraped_at"] = datetime_to_json(item.scraped_at)
    return data


def normalize_key_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def normalized_url(value: str | None) -> str:
    """Comparison key for a URL.

    Lurie pages are reachable as http or https, with or without "www", and with or
    without a trailing "index.html"; all of those spellings map to the same key.
    """
    if not value:
        return ""
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path
    if host in LURIE_HOSTS:
        host = "www.cancer.northwestern.edu"
        if path.lower().endswith("/index.html"):
            path = path[: -len("index.html")]
    path = path.rstrip("/") or "/"
    return parsed._replace(scheme="https", netloc=host, path=path, fragment="").geturl().lower()


def _credential_key(value: str) -> str:
    return value.strip().replace(".", "").replace(" ", "").lower()


def split_speaker(value: str | None) -> tuple[str | None, str | None]:
    """Split "Name, MD, PhD, Affiliation" into ("Name, MD, PhD", "Affiliation").

    Returns (None, None) when the text has no credential, because the listing then
    holds a subtitle or theme rather than a speaker.
    """
    if not value:
        return None, None
    parts = [part.strip() for part in value.split(",")]
    last_credential = None
    for index, part in enumerate(parts):
        if index > 0 and _credential_key(part) in CREDENTIALS:
            last_credential = index
    if last_credential is None:
        return None, None
    name = ", ".join(parts[: last_credential + 1])
    affiliation = ", ".join(part for part in parts[last_credential + 1 :] if part)
    return name, affiliation or None


def uid_key_for_event(event: ParsedEvent) -> str:
    if event.source_event_id:
        return f"event-id:{normalize_key_text(event.source_event_id)}"
    if event.detail_url:
        return f"detail:{normalized_url(event.detail_url)}"
    if event.pdf_url:
        date_part = event.start_datetime.date().isoformat()
        return f"pdf:{normalized_url(event.pdf_url)}:{date_part}"
    title_key = normalize_key_text(event.title)
    series_key = normalize_key_text(event.series)
    date_part = event.start_datetime.date().isoformat()
    return f"title-date:{series_key}:{title_key}:{date_part}"


def make_stable_uid(key: str) -> str:
    digest = uuid5(NAMESPACE_URL, key)
    return f"{digest}@{UID_DOMAIN}"


def load_uid_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "mappings": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "mappings" not in data:
        return {"version": 1, "mappings": {}}
    return data


def save_uid_mapping(path: Path, mapping: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(mapping, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def _event_changed(previous: dict[str, Any] | None, event: ParsedEvent) -> bool:
    if not previous:
        return True
    current = event_to_json(event)
    compared_keys = [
        "title",
        "series",
        "speaker",
        "topic",
        "start_datetime",
        "end_datetime",
        "location",
        "registration_url",
        "status",
    ]
    return any(previous.get(key) != current.get(key) for key in compared_keys)


def dedupe_events(events: list[ParsedEvent]) -> list[ParsedEvent]:
    """Keep one event per UID key, preferring the most confident parse.

    The same page can be discovered through several links; publishing it twice would
    put two VEVENTs with the same UID in the calendar.
    """
    best: dict[str, ParsedEvent] = {}
    for event in events:
        key = uid_key_for_event(event)
        current = best.get(key)
        if current is None or event.confidence > current.confidence:
            best[key] = event
    return list(best.values())


def apply_stable_uids(
    events: list[ParsedEvent],
    mapping_path: Path,
    now: datetime,
    cancellation_days: int = 30,
) -> list[ParsedEvent]:
    mapping = load_uid_mapping(mapping_path)
    mappings: dict[str, Any] = mapping.setdefault("mappings", {})
    seen_keys: set[str] = set()
    output: list[ParsedEvent] = []

    for event in events:
        key = uid_key_for_event(event)
        seen_keys.add(key)
        entry = mappings.get(key, {})
        previous_event = entry.get("event")
        uid = entry.get("uid") or make_stable_uid(key)
        sequence = int(entry.get("sequence", 0))
        if _event_changed(previous_event, event):
            sequence += 1 if previous_event else 0

        event.stable_uid = uid
        event.sequence = sequence
        event.last_modified_at = now
        event.last_seen_at = now
        event.status = "CONFIRMED"
        mappings[key] = {
            "uid": uid,
            "sequence": sequence,
            "last_seen_at": datetime_to_json(now),
            "status": event.status,
            "event": event_to_json(event),
        }
        output.append(event)

    cancellation_window = timedelta(days=cancellation_days)
    for key, entry in list(mappings.items()):
        if key in seen_keys:
            continue
        previous_data = entry.get("event")
        if not previous_data:
            continue
        last_seen_raw = entry.get("last_seen_at")
        last_seen = datetime_from_json(last_seen_raw) if last_seen_raw else now - cancellation_window
        if now - last_seen > cancellation_window:
            continue
        previous_event = event_from_json(previous_data)
        if previous_event.end_datetime < now:
            continue

        previous_status = entry.get("status")
        sequence = int(entry.get("sequence", 0))
        if previous_status != "CANCELLED":
            sequence += 1
        previous_event.status = "CANCELLED"
        previous_event.sequence = sequence
        previous_event.last_modified_at = now
        previous_event.last_seen_at = last_seen
        entry["sequence"] = sequence
        entry["status"] = "CANCELLED"
        entry["event"] = event_to_json(previous_event)
        output.append(previous_event)

    save_uid_mapping(mapping_path, mapping)
    return output


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
