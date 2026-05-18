from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from lurie_calendar.models import CALENDAR_TIMEZONE, DetailPage, ParsedEvent, PdfDocument, ReviewItem

CHICAGO = ZoneInfo(CALENDAR_TIMEZONE)

MONTH_RE = (
    r"January|February|March|April|May|June|July|August|September|October|November|December"
)
DATE_RE = re.compile(
    rf"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    rf"(?P<month>{MONTH_RE})\s+(?P<day>\d{{1,2}}),\s+(?P<year>20\d{{2}})",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"(?P<sh>\d{1,2})(?::(?P<sm>\d{2}))?\s*"
    r"(?P<sampm>a\.?m\.?|p\.?m\.?|am|pm)?\s*"
    r"(?:-|–|—|\bto\b)\s*"
    r"(?P<eh>\d{1,2})(?::(?P<em>\d{2}))?\s*"
    r"(?P<eampm>a\.?m\.?|p\.?m\.?|am|pm)"
    r"(?:\s*(?:Central Time|CT|CST|CDT))?",
    re.IGNORECASE,
)
SPEAKER_RE = re.compile(
    r"\b([A-Z][A-Za-z'.-]+(?:[ \t]+[A-Z][A-Za-z'.-]+){1,4},[ \t]*"
    r"(?:MD|PhD|DO|RN|MS|MSc|MPH|MBA|DMin|BCC|LCSW)(?:,\s*(?:MD|PhD|DO|RN|MS|MSc|MPH|MBA|DMin|BCC|LCSW))*)"
)

POSITIVE_TERMS = (
    "professional education",
    "grand rounds",
    "basic research seminar",
    "seminar series",
    "symposium",
    "conference",
    "oncology review",
    "cme",
    "continuing medical education",
    "accreditation",
    "credit designation",
    "target audience",
    "clinicians",
    "physicians",
    "scientists",
    "healthcare professionals",
    "research",
    "clinical best practices",
    "lecture",
    "keynote",
)
NEGATIVE_TERMS = (
    "support group",
    "patient support",
    "community members",
    "patients, caregivers",
    "caregivers and families",
    "wellness",
    "fundraiser",
    "walk & 5k",
    "mindfulness",
    "resource fair",
)


@dataclass(frozen=True)
class Evidence:
    source_name: str
    source_url: str
    title: str | None
    event_date: date | None
    start_time: time | None
    end_time: time | None
    excerpt: str


@dataclass(frozen=True)
class DateCandidate:
    value: date
    excerpt: str
    score: int


@dataclass
class ParseResult:
    event: ParsedEvent | None
    reviews: list[ReviewItem]
    skipped: bool = False


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _excerpt_around(text: str, match: re.Match[str] | None, radius: int = 120) -> str:
    if match is None:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _month_number(name: str) -> int:
    return datetime.strptime(name[:3], "%b").month


def _preferred_year_from_url(source_url: str) -> int | None:
    match = re.search(r"\b(20\d{2})\b", source_url)
    if match:
        return int(match.group(1))
    return None


def _date_candidates(
    text: str,
    preferred_year: int | None,
    fallback_title: str | None,
) -> list[DateCandidate]:
    candidates: list[DateCandidate] = []
    for match in DATE_RE.finditer(text):
        excerpt = _excerpt_around(text, match)
        if "©" in excerpt or "copyright" in excerpt.lower():
            continue
        value = date(
            int(match.group("year")),
            _month_number(match.group("month")),
            int(match.group("day")),
        )
        score = 0
        if preferred_year and value.year == preferred_year:
            score += 10
        if fallback_title:
            score += 2 * len(_tokens(fallback_title) & _tokens(excerpt))
        if value.year < 2024:
            score -= 5
        candidates.append(DateCandidate(value=value, excerpt=excerpt, score=score))
    return candidates


def _extract_date(
    text: str,
    preferred_year: int | None = None,
    fallback_title: str | None = None,
) -> tuple[date | None, str]:
    candidates = _date_candidates(text, preferred_year, fallback_title)
    if not candidates:
        return None, ""
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    best = candidates[0]
    return best.value, best.excerpt


def _text_contains_title_tokens(text: str, fallback_title: str | None) -> bool:
    title_tokens = _tokens(fallback_title)
    if not title_tokens:
        return False
    text_tokens = _tokens(text)
    overlap = len(title_tokens & text_tokens) / max(len(title_tokens), 1)
    return overlap >= 0.5


def _evidence_title(
    text: str,
    source_name: str,
    fallback_title: str | None,
) -> str | None:
    if source_name == "html" and fallback_title:
        return fallback_title
    if source_name == "pdf" and _text_contains_title_tokens(text, fallback_title):
        return fallback_title
    return _title_from_text(text, fallback_title)


def _normal_ampm(value: str | None) -> str | None:
    if not value:
        return None
    compact = value.lower().replace(".", "")
    if compact.startswith("a"):
        return "am"
    if compact.startswith("p"):
        return "pm"
    return None


def _to_time(hour_raw: str, minute_raw: str | None, ampm: str | None) -> time:
    hour = int(hour_raw)
    minute = int(minute_raw or "0")
    if ampm == "am":
        if hour == 12:
            hour = 0
    elif ampm == "pm" and hour != 12:
        hour += 12
    return time(hour=hour, minute=minute)


def _time_candidate_score(label: str, snippet: str) -> int:
    combined = f"{label} {snippet}".lower()
    score = 0
    for term in ("program", "symposium", "lecture", "seminar", "grand rounds", "keynote"):
        if term in combined:
            score += 5
    for term in ("registration", "breakfast", "exhibits", "login", "connection", "reception", "poster", "award"):
        if term in combined:
            score -= 5
    if "central" in combined or "ct" in combined:
        score += 1
    return score


@dataclass(frozen=True)
class TimeCandidate:
    score: int
    start: time
    end: time
    label: str
    excerpt: str


def _label_for_time_match(
    lines: list[str],
    index: int,
    context: str,
    match: re.Match[str],
    previous_match_end: int,
) -> str:
    inline_label = context[previous_match_end : match.start()].strip(" :-\t")
    if inline_label:
        return inline_label[-80:]
    return lines[index - 1] if index > 0 else ""


def _time_candidates(text: str) -> list[TimeCandidate]:
    candidates: list[TimeCandidate] = []
    lines = _lines(text)
    for index, line in enumerate(lines):
        contexts = [line]
        if index + 1 < len(lines):
            contexts.append(f"{line} {lines[index + 1]}")
        for context in contexts:
            previous_match_end = 0
            for match in TIME_RANGE_RE.finditer(context):
                end_ampm = _normal_ampm(match.group("eampm"))
                start_ampm = _normal_ampm(match.group("sampm")) or end_ampm
                start = _to_time(match.group("sh"), match.group("sm"), start_ampm)
                end = _to_time(match.group("eh"), match.group("em"), end_ampm)
                if end <= start and match.group("sampm") is None and end_ampm == "pm":
                    start = _to_time(match.group("sh"), match.group("sm"), "am")
                label = _label_for_time_match(lines, index, context, match, previous_match_end)
                snippet = f"{label} {match.group(0)}"
                score = _time_candidate_score(label, snippet)
                candidates.append(TimeCandidate(score, start, end, label, snippet.strip()))
                previous_match_end = match.end()
    return candidates


def _extract_time_range(text: str) -> tuple[time | None, time | None, str]:
    candidates = _time_candidates(text)
    if not candidates:
        return None, None, ""
    candidates.sort(key=lambda item: item.score, reverse=True)
    best = candidates[0]
    return best.start, best.end, best.excerpt


def _extend_end_time_for_full_event(title: str, text: str, start: time, end: time) -> time:
    combined = f"{title}\n{text}".lower()
    if not any(term in combined for term in ("poster session", "symposium", "conference")):
        return end

    related_terms = (
        "symposium",
        "program",
        "awards presentation",
        "reception",
        "poster session",
        "scientific poster session",
    )
    excluded_terms = ("breakfast", "registration", "exhibits")
    latest = end
    for candidate in _time_candidates(text):
        label = candidate.label.lower()
        if any(term in label for term in excluded_terms):
            continue
        if candidate.start < start:
            continue
        if any(term in label for term in related_terms) and candidate.end > latest:
            latest = candidate.end
    return latest


def _title_from_text(text: str, fallback: str | None = None) -> str | None:
    for line in _lines(text)[:12]:
        lower = line.lower()
        if lower.startswith(("register", "skip to", "feinberg home", "home >")):
            continue
        if len(line) > 6 and not DATE_RE.search(line) and not TIME_RANGE_RE.search(line):
            return line
    return fallback


def extract_evidence(text: str, source_name: str, source_url: str, fallback_title: str | None) -> Evidence:
    event_date, date_excerpt = _extract_date(
        text,
        preferred_year=_preferred_year_from_url(source_url),
        fallback_title=fallback_title,
    )
    start_time, end_time, time_excerpt = _extract_time_range(text)
    title = _evidence_title(text, source_name, fallback_title)
    excerpt = "\n".join(part for part in (title or "", date_excerpt, time_excerpt) if part)
    return Evidence(
        source_name=source_name,
        source_url=source_url,
        title=title,
        event_date=event_date,
        start_time=start_time,
        end_time=end_time,
        excerpt=excerpt[:1200],
    )


def is_professional_event(detail: DetailPage, combined_text: str) -> bool:
    parsed = urlparse(detail.detail_url)
    path = parsed.path.lower()
    text = f"{detail.title or ''}\n{combined_text}".lower()
    positive_score = sum(1 for term in POSITIVE_TERMS if term in text)
    negative_score = sum(1 for term in NEGATIVE_TERMS if term in text)
    if "/events/professional/" in path:
        return negative_score < 3 or positive_score >= 2
    if "/events/public/" in path:
        return positive_score >= 4 and negative_score == 0
    return positive_score >= 3 and negative_score < 2


def _series(title: str, text: str) -> str | None:
    combined = f"{title}\n{text}".lower()
    if "grand rounds" in combined:
        return "Grand Rounds"
    if "basic research seminar" in combined:
        return "Basic Research Seminar Series"
    if "seminar series" in combined:
        return "Seminar Series"
    if "oncology review" in combined:
        return "Oncology Review"
    if "symposium" in combined:
        return title if "symposium" in title.lower() else "Symposium"
    if "conference" in combined:
        return title if "conference" in title.lower() else "Conference"
    return None


def _topic(title: str, text: str) -> str | None:
    keynote_topic = _keynote_topic(text)
    if keynote_topic:
        return keynote_topic
    lines = _lines(text)
    title_seen = False
    for line in lines[:30]:
        if line == title:
            title_seen = True
            continue
        if not title_seen:
            continue
        lower = line.lower()
        if lower.startswith(("register", "join us", "event details", "image:", "additional information")):
            continue
        if any(
            term in lower
            for term in (
                "northwestern memorial hospital",
                "lurie medical research center",
                "feinberg pavilion",
                "hughes auditorium",
                "target audience",
                "conference fees",
            )
        ):
            continue
        if re.search(r"\b\d{2,5}\s+[A-Z0-9]", line):
            continue
        if DATE_RE.search(line) or TIME_RANGE_RE.search(line):
            continue
        if 12 <= len(line) <= 140:
            return line
    return title


def _keynote_topic(text: str) -> str | None:
    lines = _lines(text)
    for index, line in enumerate(lines):
        if line.lower().strip(":") != "keynote":
            continue
        for item in lines[index + 1 : index + 5]:
            if SPEAKER_RE.search(item):
                return None
            if 8 <= len(item) <= 160 and not DATE_RE.search(item) and not TIME_RANGE_RE.search(item):
                return item
    return None


def _speaker(text: str) -> str | None:
    keynote_match = re.search(r"KEYNOTE:\s*([^\n]+)", text, re.IGNORECASE)
    if keynote_match:
        name = keynote_match.group(1).strip()
        if name:
            return name
    lines = _lines(text)
    for index, line in enumerate(lines):
        if line.lower().strip(":") != "keynote":
            continue
        for item in lines[index + 1 : index + 8]:
            match = SPEAKER_RE.search(item)
            if match:
                return match.group(1).strip()
    matches = []
    for match in SPEAKER_RE.finditer(text):
        speaker = match.group(1).strip()
        if speaker not in matches:
            matches.append(speaker)
        if len(matches) == 3:
            break
    return "; ".join(matches) if matches else None


def _speaker_affiliation(text: str, speaker: str | None) -> str | None:
    if not speaker:
        return None
    lines = _lines(text)
    first_name = speaker.split(",", 1)[0]
    for index, line in enumerate(lines):
        if first_name in line:
            following = lines[index + 1 : index + 4]
            affiliation = " ".join(
                item
                for item in following
                if not DATE_RE.search(item) and not TIME_RANGE_RE.search(item)
            )
            return affiliation[:240] or None
    return None


def _location(text: str) -> str | None:
    lines = _lines(text)
    for index, line in enumerate(lines):
        if line.lower().rstrip(":") == "location":
            collected: list[str] = []
            for item in lines[index + 1 : index + 6]:
                lower = item.lower()
                if lower.startswith(("topics", "confirmed speakers", "register", "conference fees")):
                    break
                collected.append(item)
            return ", ".join(collected) if collected else None
    for index, line in enumerate(lines):
        lower = line.lower()
        if "virtual event" in lower or "online via zoom" in lower:
            return line
        if "northwestern memorial hospital" in lower or "lurie medical research center" in lower:
            return _collect_location_lines(lines[index : index + 5])
        if "feinberg pavilion" in lower or "hughes auditorium" in lower:
            return _collect_location_lines(lines[index : index + 4])
    return None


def _collect_location_lines(lines: list[str]) -> str | None:
    collected: list[str] = []
    for item in lines:
        lower = item.lower()
        if lower.startswith(
            (
                "target audience",
                "topics",
                "confirmed speakers",
                "register",
                "symposium:",
                "program:",
                "awards presentation:",
                "reception",
                "poster session:",
            )
        ):
            break
        if DATE_RE.search(item) or TIME_RANGE_RE.search(item):
            continue
        collected.append(item)
    return ", ".join(collected) if collected else None


def _format_mode(text: str, location: str | None) -> str | None:
    combined = f"{text}\n{location or ''}".lower()
    has_virtual = any(term in combined for term in ("virtual", "zoom", "online"))
    has_in_person = any(term in combined for term in ("in person", "chicago", "auditorium", "pavilion"))
    if has_virtual and has_in_person:
        return "hybrid"
    if has_virtual:
        return "virtual"
    if has_in_person:
        return "in_person"
    return None


def _registration_text(url: str | None) -> str:
    return f"\nRegistration: {url}" if url else ""


def _tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    stop = {"the", "and", "for", "with", "lurie", "cancer", "center", "event"}
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in stop}


def _title_conflicts(left: str | None, right: str | None) -> bool:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    return overlap < 0.25


def _conflict_review(
    detail: DetailPage,
    scraped_at: datetime,
    reason: str,
    html_evidence: Evidence,
    pdf_evidence: Evidence,
) -> ReviewItem:
    return ReviewItem(
        reason=reason,
        source_url=detail.source_url,
        detail_url=detail.detail_url,
        pdf_url=pdf_evidence.source_url,
        title=detail.title,
        scraped_at=scraped_at,
        raw_source_excerpt=f"HTML:\n{html_evidence.excerpt}\n\nPDF:\n{pdf_evidence.excerpt}",
        payload={"pdf_url": pdf_evidence.source_url},
    )


def _check_conflicts(
    detail: DetailPage,
    scraped_at: datetime,
    html_evidence: Evidence,
    pdf_evidences: list[Evidence],
) -> list[ReviewItem]:
    reviews: list[ReviewItem] = []
    for pdf_evidence in pdf_evidences:
        if html_evidence.event_date and pdf_evidence.event_date:
            if html_evidence.event_date != pdf_evidence.event_date:
                reviews.append(
                    _conflict_review(
                        detail,
                        scraped_at,
                        "PDF date conflicts with webpage date",
                        html_evidence,
                        pdf_evidence,
                    )
                )
        if html_evidence.start_time and pdf_evidence.start_time:
            if _pdf_time_conflict_is_reliable(pdf_evidence) and (
                html_evidence.start_time != pdf_evidence.start_time
                or html_evidence.end_time != pdf_evidence.end_time
            ):
                reviews.append(
                    _conflict_review(
                        detail,
                        scraped_at,
                        "PDF time conflicts with webpage time",
                        html_evidence,
                        pdf_evidence,
                    )
                )
        if _title_conflicts(html_evidence.title, pdf_evidence.title):
            reviews.append(
                _conflict_review(
                    detail,
                    scraped_at,
                    "PDF title conflicts with webpage title",
                    html_evidence,
                    pdf_evidence,
                )
            )
    return reviews


def _pdf_time_conflict_is_reliable(pdf_evidence: Evidence) -> bool:
    excerpt = pdf_evidence.excerpt.lower()
    explicit_event_time_labels = (
        "event time",
        "program:",
        "symposium:",
        "conference:",
        "lecture:",
        "seminar:",
        "grand rounds:",
    )
    excluded_agenda_item_labels = (
        "breakfast",
        "registration",
        "exhibits",
        "reception",
        "poster",
        "award",
        "break",
    )
    return any(label in excerpt for label in explicit_event_time_labels) and not any(
        label in excerpt for label in excluded_agenda_item_labels
    )


def parse_event(
    detail: DetailPage,
    pdf_documents: list[PdfDocument],
    now: datetime,
    days_ahead: int,
) -> ParseResult:
    scraped_at = now.astimezone(UTC)
    reviews: list[ReviewItem] = []
    combined_pdf_text = "\n\n".join(pdf.text for pdf in pdf_documents if pdf.text.strip())
    combined_text = f"{detail.visible_text}\n\n{combined_pdf_text}"

    if not is_professional_event(detail, combined_text):
        return ParseResult(event=None, reviews=[], skipped=True)

    for pdf in pdf_documents:
        if not pdf.extractable_text:
            reviews.append(
                ReviewItem(
                    reason="Linked PDF has no extractable text; manual review required",
                    source_url=detail.source_url,
                    detail_url=detail.detail_url,
                    pdf_url=pdf.source_url,
                    pdf_sha256=pdf.sha256,
                    title=detail.title,
                    scraped_at=scraped_at,
                )
            )
    if reviews:
        return ParseResult(event=None, reviews=reviews)

    html_evidence = extract_evidence(detail.visible_text, "html", detail.detail_url, detail.title)
    pdf_evidences = [
        extract_evidence(pdf.text, "pdf", pdf.source_url, detail.title) for pdf in pdf_documents
    ]
    conflict_reviews = _check_conflicts(detail, scraped_at, html_evidence, pdf_evidences)
    if conflict_reviews:
        return ParseResult(event=None, reviews=conflict_reviews)

    evidences = [html_evidence, *pdf_evidences]
    title = next((item.title for item in evidences if item.title), None)
    event_date = next((item.event_date for item in evidences if item.event_date), None)
    start_time = next((item.start_time for item in evidences if item.start_time), None)
    end_time = next((item.end_time for item in evidences if item.end_time), None)

    if not title or not event_date or not start_time:
        reviews.append(
            ReviewItem(
                reason="Could not confidently parse required title/date/time",
                source_url=detail.source_url,
                detail_url=detail.detail_url,
                title=detail.title,
                scraped_at=scraped_at,
                raw_source_excerpt="\n\n".join(item.excerpt for item in evidences if item.excerpt),
            )
        )
        return ParseResult(event=None, reviews=reviews)

    if end_time is None:
        end_time = time(hour=(start_time.hour + 1) % 24, minute=start_time.minute)
    end_time = _extend_end_time_for_full_event(title, combined_text, start_time, end_time)

    start_dt = datetime.combine(event_date, start_time, tzinfo=CHICAGO)
    end_dt = datetime.combine(event_date, end_time, tzinfo=CHICAGO)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    local_now = now.astimezone(CHICAGO)
    if start_dt < local_now:
        return ParseResult(event=None, reviews=[], skipped=True)
    if start_dt > local_now + timedelta(days=days_ahead):
        return ParseResult(event=None, reviews=[], skipped=True)

    series = _series(title, combined_text)
    topic = _topic(title, detail.visible_text)
    speaker = _speaker(combined_text)
    speaker_affiliation = _speaker_affiliation(combined_text, speaker)
    location = _location(detail.visible_text)
    mode = _format_mode(combined_text, location)
    pdf_used = pdf_documents[0] if pdf_documents else None
    confidence = 0.82
    if detail.title:
        confidence += 0.04
    if pdf_documents:
        confidence += 0.04
    if detail.registration_url:
        confidence += 0.03
    confidence = min(confidence, 0.95)
    raw_excerpt = "\n\n".join(item.excerpt for item in evidences if item.excerpt)[:1600]
    pdf_description_line = f"\nPDF: {pdf_used.source_url}" if pdf_used else ""
    event_source_url = detail.canonical_url or detail.detail_url

    description = (
        f"{title}\n\n"
        f"Series: {series or 'Unknown'}\n"
        f"Speaker: {speaker or 'Unknown'}\n"
        f"Topic: {topic or 'Unknown'}\n"
        f"Source: {detail.detail_url}"
        f"{pdf_description_line}"
        f"{_registration_text(detail.registration_url)}\n"
        f"Scraped: {scraped_at.isoformat()}"
    )

    event = ParsedEvent(
        stable_uid=None,
        source_event_id=detail.source_event_id,
        source_url=event_source_url,
        detail_url=detail.detail_url,
        pdf_url=pdf_used.source_url if pdf_used else None,
        pdf_sha256=pdf_used.sha256 if pdf_used else None,
        title=title,
        series=series,
        speaker=speaker,
        speaker_affiliation=speaker_affiliation,
        topic=topic,
        start_datetime=start_dt,
        end_datetime=end_dt,
        timezone=CALENDAR_TIMEZONE,
        location=location,
        virtual_or_in_person=mode,
        registration_url=detail.registration_url,
        description=description,
        confidence=confidence,
        last_seen_at=scraped_at,
        scraped_at=scraped_at,
        raw_source_excerpt=raw_excerpt,
    )
    return ParseResult(event=event, reviews=[])
