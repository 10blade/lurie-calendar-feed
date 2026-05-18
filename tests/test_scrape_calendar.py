from pathlib import Path

from lurie_calendar.scrape_calendar import (
    extract_links_from_html,
    extract_professional_feed_links,
    is_candidate_event_detail,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_professional_event_detail_links() -> None:
    html = (FIXTURES / "professional_index.html").read_text(encoding="utf-8")
    links = extract_links_from_html(html, "https://www.cancer.northwestern.edu/events/index.html")
    event_links = [link.url for link in links if is_candidate_event_detail(link.url, link.text)]

    assert event_links == [
        "https://www.cancer.northwestern.edu/events/professional/oncology-review/"
    ]


def test_extracts_js_professional_feed_rows() -> None:
    html = """
    <section class="eventsWrapper">
      <h2 class="clear">May 2026</h2>
      <div class="event">
        <div class="eventDate">
          <span class="day">Tuesday</span><span class="monthday">May 19</span>
        </div>
        <div class="eventDetail">
          <label>Lurie Cancer Center Basic Research Seminar</label>
          <h3><a href="https://lcc.northwestern.edu/mail/2026/flyers/2026-05-19-BR-Piunti.pdf">Chromatin Deregulation in Pediatric Cancers</a></h3>
          <p class="subTitle">Andrea Piunti, PhD, University of Chicago</p>
        </div>
        <div class="eventLocation"><p>Robert H. Lurie Medical Research Center<br>Searle Seminar Room</p></div>
      </div>
    </section>
    """

    links = extract_professional_feed_links(
        html,
        "https://www.cancer.northwestern.edu/events/getEvents.php?q=lcc-e-professional",
    )

    assert len(links) == 1
    assert links[0].url.endswith("2026-05-19-BR-Piunti.pdf")
    assert links[0].title == "Chromatin Deregulation in Pediatric Cancers"
    assert "Tuesday, May 19, 2026" in (links[0].context_text or "")
    assert "Basic Research Seminar" in (links[0].context_text or "")
