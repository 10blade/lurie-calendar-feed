from datetime import UTC, datetime
from pathlib import Path

from lurie_calendar.models import DetailPage, PdfDocument
from lurie_calendar.parse_event import parse_event


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 5, 18, tzinfo=UTC)


def make_detail(text: str, url: str = "https://www.cancer.northwestern.edu/events/professional/oncology-review/") -> DetailPage:
    return DetailPage(
        source_url="https://www.cancer.northwestern.edu/events/index.html",
        detail_url=url,
        canonical_url=url,
        visible_text=text,
        pdf_urls=[],
        registration_url="https://northwestern.cloud-cme.com/course",
        html="",
        title=text.splitlines()[0],
    )


def test_parse_professional_event() -> None:
    text = (FIXTURES / "professional_event.txt").read_text(encoding="utf-8")
    result = parse_event(make_detail(text), [], now=NOW, days_ahead=180)

    assert result.event is not None
    assert result.event.title == "Oncology Review Symposium"
    assert result.event.series == "Oncology Review"
    assert result.event.start_datetime.isoformat().startswith("2026-07-17T09:00:00")
    assert result.event.end_datetime.isoformat().startswith("2026-07-17T17:10:00")
    assert result.event.virtual_or_in_person == "in_person"
    assert not result.reviews


def test_parse_prefers_program_time_when_schedule_is_inline() -> None:
    text = (
        "Oncology Review Symposium\n"
        "Join us for professional education and oncology review research.\n"
        "Friday, July 17, 2026\n"
        "Breakfast & Exhibits: 8:00 a.m. - 9:00 a.m. Program: 9:00 a.m. - 5:10 p.m.\n"
        "Target Audience\n"
        "Medical, surgical, and radiation oncologists; scientists and healthcare professionals."
    )
    result = parse_event(make_detail(text), [], now=NOW, days_ahead=180)

    assert result.event is not None
    assert result.event.start_datetime.isoformat().startswith("2026-07-17T09:00:00")


def test_parse_symposium_uses_full_poster_session_window_and_keynote() -> None:
    text = (
        "Lurie Cancer Center Symposium & Scientific Poster Session\n"
        "Join us in person on the Chicago campus!\n"
        "Event Details\n"
        "Robert H. Lurie Medical Research Center\n"
        "303 E. Superior St., Chicago, Hughes Auditorium\n"
        "Thursday, June 18, 2026\n"
        "Symposium: 2:00 p.m. - 5:10 p.m. Central Time\n"
        "Awards Presentation: 5:10 p.m. - 5:30 p.m. Central Time\n"
        "Reception and Scientific Poster Session: 5:30 p.m. - 6:30 p.m. Central Time\n"
        "Keynote\n"
        "Protein Acylation in Cancer and Inflammation\n"
        "Hening Lin, PhD\n"
        "James and Karen Frank Family Professor of Medicine\n"
    )
    result = parse_event(make_detail(text), [], now=NOW, days_ahead=180)

    assert result.event is not None
    assert result.event.start_datetime.isoformat().startswith("2026-06-18T14:00:00")
    assert result.event.end_datetime.isoformat().startswith("2026-06-18T18:30:00")
    assert result.event.speaker == "Hening Lin, PhD"
    assert result.event.topic == "Protein Acylation in Cancer and Inflammation"
    assert result.event.location == (
        "Robert H. Lurie Medical Research Center, "
        "303 E. Superior St., Chicago, Hughes Auditorium"
    )


def test_parse_excludes_public_patient_event() -> None:
    text = (FIXTURES / "public_event.txt").read_text(encoding="utf-8")
    detail = make_detail(
        text,
        url="https://www.cancer.northwestern.edu/events/public/cancer-connections/",
    )
    result = parse_event(detail, [], now=NOW, days_ahead=180)

    assert result.event is None
    assert result.skipped


def test_pdf_conflicting_date_requires_review() -> None:
    text = (FIXTURES / "professional_event.txt").read_text(encoding="utf-8")
    pdf = PdfDocument(
        source_url="https://www.cancer.northwestern.edu/docs/event-docs/2026/agenda.pdf",
        final_url="https://www.cancer.northwestern.edu/docs/event-docs/2026/agenda.pdf",
        sha256="abc",
        text="Oncology Review Symposium\nFriday, August 21, 2026\nProgram: 9:00 a.m. - 5:10 p.m.",
        extractable_text=True,
        size_bytes=100,
        content_type="application/pdf",
    )

    result = parse_event(make_detail(text), [pdf], now=NOW, days_ahead=180)

    assert result.event is None
    assert result.reviews
    assert "conflicts" in result.reviews[0].reason
