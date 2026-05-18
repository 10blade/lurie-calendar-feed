from pathlib import Path

from lurie_calendar.scrape_calendar import extract_links_from_html, is_candidate_event_detail


FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_professional_event_detail_links() -> None:
    html = (FIXTURES / "professional_index.html").read_text(encoding="utf-8")
    links = extract_links_from_html(html, "https://www.cancer.northwestern.edu/events/index.html")
    event_links = [link.url for link in links if is_candidate_event_detail(link.url, link.text)]

    assert event_links == [
        "https://www.cancer.northwestern.edu/events/professional/oncology-review/"
    ]
