from datetime import date
from pathlib import Path

from lurie_calendar.models import DiscoveredLink
from lurie_calendar.scrape_calendar import (
    _unique_links,
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
    listing = links[0].listing
    assert listing is not None
    assert listing.title == "Chromatin Deregulation in Pediatric Cancers"
    assert listing.event_date == date(2026, 5, 19)
    assert listing.series == "Lurie Cancer Center Basic Research Seminar"
    assert listing.speaker == "Andrea Piunti, PhD, University of Chicago"
    assert listing.location == "Robert H. Lurie Medical Research Center, Searle Seminar Room"


def test_feed_row_and_site_link_to_same_page_are_deduplicated() -> None:
    # Live feed (Oct 2026) links the nursing conference as http://cancer...index.html,
    # while the Lurie site links it as https://www.cancer.../nursing/.
    feed_html = """
    <section class='eventsWrapper'><h2 class='clear'>November 2026</h2>
      <div class="event">
        <div class="eventDate"><span class='day'>Friday</span><span class='monthday'>Nov 20</span></div>
        <div class="eventDetail">
          <label>Lurie Cancer Center Professional Education Events</label>
          <h3><a href="http://cancer.northwestern.edu/events/professional/nursing/index.html">29th Annual Oncology Nursing Conference</a></h3>
          <p class='subTitle'>Innovation with Heart: The Science and Soul of Oncology Nursing</p>
        </div>
        <div class="eventLocation"><p>Northwestern Memorial Hospital<br/>Feinberg Pavilion, 3rd Floor<br/>251 E. Huron St.<br/></p></div>
      </div>
    </section>
    """
    feed_links = extract_professional_feed_links(
        feed_html,
        "https://www.cancer.northwestern.edu/events/getEvents.php?q=lcc-e-professional",
    )
    site_link = DiscoveredLink(
        url="https://www.cancer.northwestern.edu/events/professional/nursing/",
        text="Oncology Nursing Conference",
        source_url="https://www.cancer.northwestern.edu/events/index.html",
    )

    unique = _unique_links([site_link, *feed_links])

    assert len(unique) == 1
    assert unique[0].listing is not None
    assert unique[0].listing.title == "29th Annual Oncology Nursing Conference"
    assert unique[0].listing.location == (
        "Northwestern Memorial Hospital, Feinberg Pavilion, 3rd Floor, 251 E. Huron St."
    )
