from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5


CALENDAR_TIMEZONE = "America/Chicago"
UID_DOMAIN = "lurie-calendar-feed.github.io"


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    text: str
    source_url: str


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
    if not value:
        return ""
    parsed = urlparse(value)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, query=parsed.query, fragment="").geturl().lower()


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
