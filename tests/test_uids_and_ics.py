from datetime import UTC, datetime
from pathlib import Path

import pytest

from lurie_calendar.ics_writer import build_calendar, summary_for_event
from lurie_calendar.models import (
    CALENDAR_TIMEZONE,
    ParsedEvent,
    apply_stable_uids,
    dedupe_events,
    normalized_url,
    split_speaker,
)


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


def test_summary_uses_short_speaker_and_drops_redundant_series() -> None:
    event = make_event(datetime(2026, 11, 10, 17, tzinfo=UTC))
    event.series = "Lurie Cancer Center Basic Research Seminar"
    event.speaker = "Hidayatullah Munshi, MD, Northwestern University Feinberg School of Medicine"
    event.topic = "Understanding and Overcoming Resistance to KRAS Inhibitors in Pancreatic Cancer"
    assert summary_for_event(event) == (
        "Lurie Seminar: Hidayatullah Munshi, MD - "
        "Understanding and Overcoming Resistance to KRAS Inhibitors in Pancreatic Cancer"
    )

    event.series = "Lurie Cancer Center"
    event.title = event.topic = "Inaugural GI Oncology Symposium"
    assert summary_for_event(event) == "Lurie: Inaugural GI Oncology Symposium"

    event.series = "Lurie Cancer Center Professional Education Events"
    assert summary_for_event(event) == "Lurie: Inaugural GI Oncology Symposium"

    event.series = "Lurie Cancer Center Survivorship Program"
    event.topic = "Late Effects After Childhood Cancer"
    assert summary_for_event(event) == "Lurie Survivorship Program: Late Effects After Childhood Cancer"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Ronald Hoffman, MD, Icahn School of Medicine at Mount Sinai",
            ("Ronald Hoffman, MD", "Icahn School of Medicine at Mount Sinai"),
        ),
        (
            "Mohamed Abazeed, MD, PhD & Anish Thomas, MD, Northwestern University Feinberg School of Medicine",
            ("Mohamed Abazeed, MD, PhD & Anish Thomas, MD", "Northwestern University Feinberg School of Medicine"),
        ),
        ("De-Chen Lin, Ph.D., University of Southern California", ("De-Chen Lin, Ph.D.", "University of Southern California")),
        ("Hening Lin, PhD", ("Hening Lin, PhD", None)),
        ("Innovation with Heart: The Science and Soul of Oncology Nursing", (None, None)),
        (None, (None, None)),
    ],
)
def test_split_speaker(raw: str | None, expected: tuple[str | None, str | None]) -> None:
    assert split_speaker(raw) == expected


def test_url_spellings_of_one_lurie_page_share_a_key() -> None:
    variants = [
        "http://cancer.northwestern.edu/events/professional/nursing/index.html",
        "https://www.cancer.northwestern.edu/events/professional/nursing/",
        "https://www.cancer.northwestern.edu/events/professional/nursing",
    ]
    assert len({normalized_url(url) for url in variants}) == 1
    assert normalized_url("https://planitpurple.northwestern.edu/event/647820") != normalized_url(
        "https://planitpurple.northwestern.edu/event/647666"
    )


def test_same_page_found_twice_is_published_once() -> None:
    first = make_event(datetime(2026, 11, 20, 15, tzinfo=UTC))
    first.detail_url = "http://cancer.northwestern.edu/events/professional/test/index.html"
    first.confidence = 0.9
    second = make_event(datetime(2026, 11, 20, 15, tzinfo=UTC))
    second.detail_url = "https://www.cancer.northwestern.edu/events/professional/test/"
    second.confidence = 0.95

    kept = dedupe_events([first, second])

    assert len(kept) == 1
    assert kept[0].confidence == 0.95
