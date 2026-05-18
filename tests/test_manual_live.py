from datetime import UTC, datetime
import os

import pytest

from lurie_calendar.parse_event import parse_event
from lurie_calendar.scrape_calendar import build_client, discover_event_links
from lurie_calendar.scrape_detail import fetch_detail


@pytest.mark.skipif(
    os.environ.get("LURIE_LIVE_TEST") != "1",
    reason="Manual live integration test. Set LURIE_LIVE_TEST=1 to run.",
)
def test_live_discovery_and_first_detail_parse(tmp_path) -> None:
    with build_client() as client:
        links = discover_event_links(client, artifacts_dir=tmp_path)
        assert links
        detail = fetch_detail(client, links[0].url, artifacts_dir=tmp_path)
        result = parse_event(detail, [], now=datetime.now(UTC), days_ahead=365)
        assert result.event or result.reviews or result.skipped
