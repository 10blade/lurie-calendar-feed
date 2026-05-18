from datetime import UTC, datetime
from pathlib import Path

from lurie_calendar.ics_writer import build_calendar
from lurie_calendar.models import CALENDAR_TIMEZONE, ParsedEvent, apply_stable_uids


def make_event(start: datetime) -> ParsedEvent:
    return ParsedEvent(
        stable_uid=None,
        source_event_id=None,
        source_url="https://www.cancer.northwestern.edu/events/index.html",
        detail_url="https://www.cancer.northwestern.edu/events/professional/test/",
        pdf_url=None,
        pdf_sha256=None,
        title="Lurie Test Seminar",
        series="Seminar Series",
        speaker="Ada Lovelace, PhD",
        speaker_affiliation="Northwestern University",
        topic="Analytical Engines in Oncology",
        start_datetime=start,
        end_datetime=start.replace(hour=start.hour + 1),
        timezone=CALENDAR_TIMEZONE,
        location="Hughes Auditorium",
        virtual_or_in_person="in_person",
        registration_url=None,
        description="Test event",
        confidence=0.9,
        last_seen_at=datetime(2026, 5, 18, tzinfo=UTC),
        scraped_at=datetime(2026, 5, 18, tzinfo=UTC),
        raw_source_excerpt="Lurie Test Seminar Friday, June 5, 2026 11:00 a.m. - 12:00 p.m.",
    )


def test_stable_uid_survives_date_move(tmp_path: Path) -> None:
    mapping_path = tmp_path / "stable_uids.json"
    first = apply_stable_uids(
        [make_event(datetime(2026, 6, 5, 11, tzinfo=UTC))],
        mapping_path,
        now=datetime(2026, 5, 18, tzinfo=UTC),
    )[0]
    second = apply_stable_uids(
        [make_event(datetime(2026, 6, 12, 11, tzinfo=UTC))],
        mapping_path,
        now=datetime(2026, 5, 19, tzinfo=UTC),
    )[0]

    assert second.stable_uid == first.stable_uid
    assert second.sequence == first.sequence + 1


def test_ics_contains_timezone_and_event() -> None:
    event = make_event(datetime(2026, 6, 5, 11, tzinfo=UTC))
    event.stable_uid = "test@example.com"
    ics = build_calendar([event], now=datetime(2026, 5, 18, tzinfo=UTC))

    assert "BEGIN:VCALENDAR" in ics
    assert "TZID:America/Chicago" in ics
    assert "SUMMARY:Lurie Seminar:" in ics
    assert "lurie-professional-events" not in ics
