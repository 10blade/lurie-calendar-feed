from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lurie_calendar.models import CALENDAR_TIMEZONE, ParsedEvent

CALENDAR_NAME = "Lurie Cancer Center Professional Education Events"
PRODID = "-//10blade//Lurie Calendar Feed//EN"


def escape_text(value: str | None) -> str:
    if not value:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in line:
        candidate = current + char
        limit = 75 if not chunks else 74
        if len(candidate.encode("utf-8")) > limit:
            chunks.append(current if not chunks else f" {current}")
            current = char
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current if not chunks else f" {current}")
    return chunks


def format_local_datetime(value: datetime) -> str:
    chicago = ZoneInfo(CALENDAR_TIMEZONE)
    return value.astimezone(chicago).strftime("%Y%m%dT%H%M%S")


def format_utc_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def summary_for_event(event: ParsedEvent) -> str:
    topic = event.topic or event.title
    speaker = event.speaker
    series = (event.series or "").lower()
    if "grand rounds" in series:
        return f"Lurie Grand Rounds: {topic}"
    if "seminar" in series and speaker:
        return f"Lurie Seminar: {speaker} - {topic}"
    if "seminar" in series:
        return f"Lurie Seminar: {topic}"
    if event.series and event.series != event.title:
        return f"Lurie {event.series}: {topic}"
    return f"Lurie: {event.title}"


def description_for_event(event: ParsedEvent) -> str:
    parts = [
        event.description,
        f"Source URL: {event.source_url}",
    ]
    if event.detail_url and event.detail_url != event.source_url:
        parts.append(f"Detail URL: {event.detail_url}")
    if event.pdf_url:
        parts.append(f"PDF URL: {event.pdf_url}")
    if event.pdf_sha256:
        parts.append(f"PDF SHA256: {event.pdf_sha256}")
    if event.registration_url:
        parts.append(f"Registration URL: {event.registration_url}")
    parts.append(f"Scraped at: {event.scraped_at.astimezone(UTC).isoformat()}")
    return "\n".join(parts)


def vtimezone() -> list[str]:
    return [
        "BEGIN:VTIMEZONE",
        f"TZID:{CALENDAR_TIMEZONE}",
        f"X-LIC-LOCATION:{CALENDAR_TIMEZONE}",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:-0600",
        "TZOFFSETTO:-0500",
        "TZNAME:CDT",
        "DTSTART:19700308T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:-0500",
        "TZOFFSETTO:-0600",
        "TZNAME:CST",
        "DTSTART:19701101T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


def event_lines(event: ParsedEvent, dtstamp: datetime) -> list[str]:
    last_modified = event.last_modified_at or dtstamp
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.stable_uid}",
        f"DTSTAMP:{format_utc_datetime(dtstamp)}",
        f"LAST-MODIFIED:{format_utc_datetime(last_modified)}",
        f"SEQUENCE:{event.sequence}",
        f"STATUS:{event.status}",
        f"DTSTART;TZID={CALENDAR_TIMEZONE}:{format_local_datetime(event.start_datetime)}",
        f"DTEND;TZID={CALENDAR_TIMEZONE}:{format_local_datetime(event.end_datetime)}",
        f"SUMMARY:{escape_text(summary_for_event(event))}",
        f"DESCRIPTION:{escape_text(description_for_event(event))}",
    ]
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")
    if event.detail_url:
        lines.append(f"URL:{event.detail_url}")
    lines.append("END:VEVENT")
    return lines


def build_calendar(events: list[ParsedEvent], now: datetime | None = None) -> str:
    dtstamp = now or datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(CALENDAR_NAME)}",
        f"X-WR-TIMEZONE:{CALENDAR_TIMEZONE}",
        *vtimezone(),
    ]
    for event in sorted(events, key=lambda item: (item.start_datetime, item.title)):
        if not event.stable_uid:
            raise ValueError(f"Event is missing stable_uid: {event.title}")
        lines.extend(event_lines(event, dtstamp))
    lines.append("END:VCALENDAR")
    folded = [folded for line in lines for folded in fold_line(line)]
    return "\r\n".join(folded) + "\r\n"


def write_calendar(events: list[ParsedEvent], path: Path, now: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(build_calendar(events, now=now), encoding="utf-8", newline="")
    tmp_path.replace(path)
