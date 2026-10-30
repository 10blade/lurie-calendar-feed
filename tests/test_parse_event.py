from datetime import UTC, date, datetime
from pathlib import Path

from lurie_calendar.ics_writer import summary_for_event
from lurie_calendar.models import DetailPage, FeedListing, PdfDocument
from lurie_calendar.parse_event import parse_event


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 5, 18, tzinfo=UTC)
NOW_FALL = datetime(2026, 10, 30, 21, tzinfo=UTC)
FEED_URL = "https://www.cancer.northwestern.edu/events/getEvents.php?q=lcc-e-professional"


def make_feed_detail(
    url: str, visible_text: str, listing: FeedListing, title: str | None = None
) -> DetailPage:
    return DetailPage(
        source_url=FEED_URL,
        detail_url=url,
        canonical_url=None,
        visible_text=visible_text,
        pdf_urls=[url] if url.endswith(".pdf") else [],
        registration_url=None,
        html="",
        title=title or listing.title,
        listing=listing,
    )


def make_pdf(url: str, text: str) -> PdfDocument:
    return PdfDocument(
        source_url=url,
        final_url=url,
        sha256="abc",
        text=text,
        extractable_text=True,
        size_bytes=100,
        content_type="application/pdf",
    )


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


def test_pdf_evidence_uses_pdf_year_when_template_contains_old_date() -> None:
    text = (FIXTURES / "professional_event.txt").read_text(encoding="utf-8")
    pdf = PdfDocument(
        source_url="https://www.cancer.northwestern.edu/docs/event-docs/2026/oncreview2026-agenda.pdf",
        final_url="https://www.cancer.northwestern.edu/docs/event-docs/2026/oncreview2026-agenda.pdf",
        sha256="abc",
        text=(
            "June 20, 2019 | Robert H. Lurie Medical Research Center\n"
            "2026 ONCOLOGY REVIEW\n"
            "Friday, July 17, 2026 | Northwestern Memorial Hospital\n"
            "9:00 a.m. Welcome & Opening Remarks\n"
            "5:10 p.m. Adjourn\n"
        ),
        extractable_text=True,
        size_bytes=100,
        content_type="application/pdf",
    )

    result = parse_event(make_detail(text), [pdf], now=NOW, days_ahead=180)

    assert result.event is not None
    assert result.event.title == "Oncology Review Symposium"


def test_parse_professional_feed_pdf_row() -> None:
    detail = DetailPage(
        source_url="https://www.cancer.northwestern.edu/events/getEvents.php?q=lcc-e-professional",
        detail_url="https://lcc.northwestern.edu/mail/2026/flyers/2026-05-19-BR-Piunti.pdf",
        canonical_url=None,
        visible_text=(
            "Chromatin Deregulation in Pediatric Cancers\n"
            "Source calendar: Lurie Cancer Center professional events feed\n"
            "Series: Lurie Cancer Center Basic Research Seminar\n"
            "Tuesday, May 19, 2026\n"
            "Speaker: Andrea Piunti, PhD, University of Chicago\n"
            "Location:\n"
            "Robert H. Lurie Medical Research Center Searle Seminar Room"
        ),
        pdf_urls=["https://lcc.northwestern.edu/mail/2026/flyers/2026-05-19-BR-Piunti.pdf"],
        registration_url=None,
        html="",
        title="Chromatin Deregulation in Pediatric Cancers",
    )
    pdf = PdfDocument(
        source_url="https://lcc.northwestern.edu/mail/2026/flyers/2026-05-19-BR-Piunti.pdf",
        final_url="https://lcc.northwestern.edu/mail/2026/flyers/2026-05-19-BR-Piunti.pdf",
        sha256="abc",
        text=(
            "Chromatin Deregulation in Pediatric Cancers\n"
            "Tuesday, May 19, 2026\n"
            "Seminar: 11:00 AM - 12:00 PM\n"
            "Andrea Piunti, PhD, University of Chicago"
        ),
        extractable_text=True,
        size_bytes=100,
        content_type="application/pdf",
    )

    result = parse_event(detail, [pdf], now=NOW, days_ahead=180)

    assert result.event is not None
    assert result.event.title == "Chromatin Deregulation in Pediatric Cancers"
    assert result.event.series == "Lurie Cancer Center Basic Research Seminar"
    assert result.event.start_datetime.isoformat().startswith("2026-05-19T11:00:00")
    assert result.event.speaker == "Andrea Piunti, PhD, University of Chicago"


def test_feed_flyer_with_only_a_start_time_gets_estimated_end() -> None:
    # Live flyer, Oct 2026: "Tuesday, November 3, 2026, 3:30 P.M." with no end time.
    url = "https://lcc.northwestern.edu/mail/2026/flyers/2026-11-03-driskill-Li.pdf"
    listing = FeedListing(
        title="Immunological Mechanisms of Cancer Defense",
        event_date=date(2026, 11, 3),
        series="Driskill Graduate Program Distinguished Lectures in Life Sciences",
        speaker="Ming Li, PhD, Memorial Sloan Kettering Cancer Center",
        location=(
            "Robert H. Lurie Medical Research Center, 303 E. Superior St., Chicago, "
            "Hughes Auditorium"
        ),
    )
    context = (
        "Immunological Mechanisms of Cancer Defense\n"
        "Source calendar: Lurie Cancer Center professional events feed\n"
        "Series: Driskill Graduate Program Distinguished Lectures in Life Sciences\n"
        "Tuesday, November 3, 2026\n"
        "Speaker: Ming Li, PhD, Memorial Sloan Kettering Cancer Center\n"
        "Location:\n"
        "Robert H. Lurie Medical Research Center 303 E. Superior St., Chicago Hughes Auditorium"
    )
    pdf = make_pdf(
        url,
        "Tuesday, November 3, 2026, 3:30 P.M.\n"
        "Hughes Auditorium (Reception to follow\n"
        "in the Ryan Family Atrium)\n"
        "Hosted by Caylee Silvers\n"
        "The Driskill Graduate Program\n"
        "Distinguished Lecturers in Life Sciences\n"
        "Immunological Mechanisms of\n"
        "Cancer Defense\n"
        "Ming Li, PhD\n",
    )

    result = parse_event(make_feed_detail(url, context, listing), [pdf], now=NOW_FALL, days_ahead=180)

    assert result.event is not None, result.reviews
    assert result.event.start_datetime.isoformat() == "2026-11-03T15:30:00-06:00"
    assert result.event.end_datetime.isoformat() == "2026-11-03T16:30:00-06:00"
    assert "end time is an estimate" in result.event.description
    assert result.event.title == "Immunological Mechanisms of Cancer Defense"
    assert result.event.topic == "Immunological Mechanisms of Cancer Defense"
    assert result.event.location == listing.location
    assert result.event.speaker_affiliation == "Memorial Sloan Kettering Cancer Center"
    assert summary_for_event(result.event) == (
        "Lurie Driskill Graduate Program Distinguished Lectures in Life Sciences: "
        "Immunological Mechanisms of Cancer Defense"
    )


def test_feed_title_replaces_page_furniture_in_summary() -> None:
    # Before the fix, summaries read "Lurie Grand Rounds: Source calendar: ..." because
    # the topic was guessed from the line after the title.
    url = "https://lcc.northwestern.edu/mail/2026/flyers/2026-11-09-GR-Hoffman.pdf"
    listing = FeedListing(
        title="New Treatment Options for Myelofibrosis",
        event_date=date(2026, 11, 9),
        series="Lurie Cancer Center & Hematology/Oncology Grand Rounds",
        speaker="Ronald Hoffman, MD, Icahn School of Medicine at Mount Sinai",
        location="Robert H. Lurie Medical Research Center, 303 E. Superior St., Chicago, Baldwin Auditorium",
    )
    context = (
        "New Treatment Options for Myelofibrosis\n"
        "Source calendar: Lurie Cancer Center professional events feed\n"
        "Series: Lurie Cancer Center & Hematology/Oncology Grand Rounds\n"
        "Monday, November 9, 2026"
    )
    pdf = make_pdf(
        url,
        "Monday, November 9, 2026\n"
        "12:00 p.m. - 1:00 p.m. Central Time\n"
        "IN PERSON (lunch provided)\n"
        "LURIE CANCER CENTER & HEMATOLOGY/ONCOLOGY GRAND ROUNDS\n"
        "New Treatment Options for Myelofibrosis\n",
    )

    result = parse_event(make_feed_detail(url, context, listing), [pdf], now=NOW_FALL, days_ahead=180)

    assert result.event is not None, result.reviews
    assert result.event.start_datetime.isoformat() == "2026-11-09T12:00:00-06:00"
    assert summary_for_event(result.event) == "Lurie Grand Rounds: New Treatment Options for Myelofibrosis"
    assert "Time note" not in result.event.description


def test_agenda_with_labels_after_times_uses_program_window() -> None:
    # Live nursing conference page, Oct 2026: each time is followed by its label.
    url = "https://www.cancer.northwestern.edu/events/professional/nursing/index.html"
    listing = FeedListing(
        title="29th Annual Oncology Nursing Conference",
        event_date=date(2026, 11, 20),
        series="Lurie Cancer Center Professional Education Events",
        speaker="Innovation with Heart: The Science and Soul of Oncology Nursing",
        location="Northwestern Memorial Hospital, Feinberg Pavilion, 3rd Floor, 251 E. Huron St.",
    )
    page_text = (
        "Oncology Nursing Conference\n"
        "November 20, 2026\n"
        "Register now for November 20\n"
        "Event Details\n"
        "Friday, November 20, 2026\n"
        "8:30 a.m. – 9:00 a.m.\n"
        "Check-in & Breakfast\n"
        "9:00 a.m. – 3:50 p.m.\n"
        "Program\n"
        "Agenda PDF\n"
        "Northwestern Memorial Hospital\n"
    )
    detail = make_feed_detail(url, page_text, listing, title="Oncology Nursing Conference")

    result = parse_event(detail, [], now=NOW_FALL, days_ahead=180)

    assert result.event is not None, result.reviews
    assert result.event.start_datetime.isoformat() == "2026-11-20T09:00:00-06:00"
    assert result.event.end_datetime.isoformat() == "2026-11-20T15:50:00-06:00"
    assert result.event.speaker is None
    assert "Subtitle: Innovation with Heart" in result.event.description
    assert summary_for_event(result.event) == "Lurie: 29th Annual Oncology Nursing Conference"


def test_noon_is_read_as_twelve_pm() -> None:
    text = (
        "Lurie Cancer Center Grand Rounds\n"
        "Monday, November 30, 2026\n"
        "Noon - 1:00 p.m.\n"
        "Robert H. Lurie Medical Research Center, Baldwin Auditorium\n"
    )
    detail = make_detail(
        text, url="https://www.cancer.northwestern.edu/events/professional/grand-rounds/"
    )

    result = parse_event(detail, [], now=NOW_FALL, days_ahead=180)

    assert result.event is not None, result.reviews
    assert result.event.start_datetime.isoformat() == "2026-11-30T12:00:00-06:00"
    assert result.event.end_datetime.isoformat() == "2026-11-30T13:00:00-06:00"


def test_lone_registration_time_is_not_used_as_event_time() -> None:
    text = (
        "Lurie Cancer Center Grand Rounds\n"
        "Monday, November 30, 2026\n"
        "Registration opens at 7:30 a.m.\n"
    )
    detail = make_detail(
        text, url="https://www.cancer.northwestern.edu/events/professional/grand-rounds/"
    )

    result = parse_event(detail, [], now=NOW_FALL, days_ahead=180)

    assert result.event is None
    assert result.reviews
