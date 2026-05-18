from pathlib import Path

from lurie_calendar.scrape_detail import detail_from_html


FIXTURES = Path(__file__).parent / "fixtures"


def test_detail_finds_anchor_and_embedded_pdfs() -> None:
    html = (FIXTURES / "detail_with_pdfs.html").read_text(encoding="utf-8")
    detail = detail_from_html(
        html,
        "https://www.cancer.northwestern.edu/events/professional/oncology-review/",
        check_pdf_redirects=False,
    )

    assert detail.title == "Oncology Review Symposium"
    assert detail.registration_url == "https://northwestern.cloud-cme.com/course"
    assert detail.pdf_urls == [
        "https://www.cancer.northwestern.edu/docs/event-docs/2026/embedded.pdf",
        "https://www.cancer.northwestern.edu/docs/event-docs/2026/object.pdf",
        "https://www.cancer.northwestern.edu/docs/event-docs/2026/oncology-review-agenda.pdf",
    ]
