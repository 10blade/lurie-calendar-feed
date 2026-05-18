from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import traceback
from typing import Any

import httpx

from lurie_calendar.ics_writer import CALENDAR_NAME, write_calendar
from lurie_calendar.models import (
    ReviewItem,
    apply_stable_uids,
    event_from_json,
    event_to_json,
    review_to_json,
)
from lurie_calendar.parse_event import parse_event
from lurie_calendar.pdf_extract import PdfExtractionError, download_and_extract_pdf
from lurie_calendar.scrape_calendar import build_client, discover_event_links
from lurie_calendar.scrape_detail import fetch_detail


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def write_status_page(
    path: Path,
    *,
    run_time: datetime,
    published_count: int,
    review_count: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{CALENDAR_NAME}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; max-width: 760px; line-height: 1.55; color: #202124; }}
    h1 {{ font-size: 1.8rem; }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: .5rem 1rem; }}
    dt {{ font-weight: 700; }}
    .warning {{ border-left: 4px solid #7a0019; padding-left: 1rem; background: #fff7f7; }}
  </style>
</head>
<body>
  <h1>{CALENDAR_NAME}</h1>
  <p><a href="lurie-professional-events.ics">Subscribe to the iCalendar feed</a></p>
  <dl>
    <dt>Last successful run</dt><dd>{run_time.astimezone(UTC).isoformat()}</dd>
    <dt>Published events</dt><dd>{published_count}</dd>
    <dt>Review required</dt><dd>{review_count}</dd>
  </dl>
  <p class="warning">This is an unofficial personal calendar feed generated from public Robert H. Lurie Comprehensive Cancer Center event pages. Confirm event details with the official source before attending.</p>
</body>
</html>
"""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(html, encoding="utf-8")
    tmp_path.replace(path)


def run_summary(
    *,
    run_time: datetime,
    discovered_count: int,
    published_count: int,
    review_count: int,
    skipped_count: int,
    errors: list[str],
) -> str:
    lines = [
        "# Lurie calendar scraper run",
        "",
        f"- Run time: {run_time.astimezone(UTC).isoformat()}",
        f"- Discovered event links: {discovered_count}",
        f"- Published events: {published_count}",
        f"- Review required: {review_count}",
        f"- Skipped as out-of-scope/out-of-window: {skipped_count}",
    ]
    if errors:
        lines.extend(["", "## Errors", *[f"- {error}" for error in errors]])
    return "\n".join(lines) + "\n"


def _review_for_error(reason: str, url: str, scraped_at: datetime, exc: BaseException) -> ReviewItem:
    return ReviewItem(
        reason=reason,
        source_url=url,
        detail_url=url,
        scraped_at=scraped_at,
        raw_source_excerpt=str(exc),
    )


def update_command(args: argparse.Namespace) -> int:
    base_dir = Path.cwd()
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    artifacts_dir = base_dir / "artifacts" / run_id
    cache_dir = base_dir / ".cache" / "lurie_calendar" / "pdfs"
    data_dir = base_dir / "data"
    docs_dir = base_dir / "docs"
    logs_dir = base_dir / "logs"
    errors: list[str] = []
    reviews: list[ReviewItem] = []
    parser_log: list[dict[str, Any]] = []
    skipped_count = 0

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    client = build_client(timeout=args.timeout)
    try:
        links = discover_event_links(client, artifacts_dir=artifacts_dir)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Failed to discover event links: {exc}")
        write_markdown(
            logs_dir / "last_run_summary.md",
            run_summary(
                run_time=now,
                discovered_count=0,
                published_count=0,
                review_count=0,
                skipped_count=0,
                errors=errors,
            ),
        )
        (artifacts_dir / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 2

    pdf_discovery: dict[str, list[str]] = {}
    parsed_events = []
    for link in links:
        try:
            detail = fetch_detail(
                client,
                link.url,
                source_url=link.source_url,
                artifacts_dir=artifacts_dir,
            )
        except (httpx.HTTPError, ValueError) as exc:
            reviews.append(_review_for_error("Could not fetch event detail page", link.url, now, exc))
            parser_log.append({"url": link.url, "status": "detail_fetch_failed", "error": str(exc)})
            continue

        pdf_discovery[detail.detail_url] = detail.pdf_urls
        pdf_documents = []
        pdf_failed = False
        for pdf_url in detail.pdf_urls:
            try:
                pdf_documents.append(download_and_extract_pdf(client, pdf_url, cache_dir=cache_dir))
            except (httpx.HTTPError, PdfExtractionError, ValueError) as exc:
                pdf_failed = True
                parser_log.append(
                    {
                        "url": detail.detail_url,
                        "pdf_url": pdf_url,
                        "status": "pdf_extract_failed",
                        "error": str(exc),
                    }
                )
                reviews.append(
                    ReviewItem(
                        reason="Could not download or extract linked PDF; manual review required",
                        source_url=detail.source_url,
                        detail_url=detail.detail_url,
                        pdf_url=pdf_url,
                        title=detail.title,
                        scraped_at=now,
                        raw_source_excerpt=str(exc),
                    )
                )
        if pdf_failed:
            continue

        result = parse_event(detail, pdf_documents, now=now, days_ahead=args.days_ahead)
        reviews.extend(result.reviews)
        if result.skipped:
            skipped_count += 1
            parser_log.append({"url": detail.detail_url, "status": "skipped"})
        if result.event is not None:
            parsed_events.append(result.event)
            parser_log.append(
                {
                    "url": detail.detail_url,
                    "status": "published_candidate",
                    "title": result.event.title,
                    "start_datetime": result.event.start_datetime.isoformat(),
                }
            )
        for review in result.reviews:
            parser_log.append(
                {
                    "url": detail.detail_url,
                    "status": "review_required",
                    "reason": review.reason,
                    "title": review.title,
                }
            )

    write_json(artifacts_dir / "discovered_pdf_urls.json", pdf_discovery)
    write_json(artifacts_dir / "parser_log.json", parser_log)
    if not parsed_events:
        errors.append("Source pages loaded, but zero future professional events were parsed.")
        write_json(data_dir / "review_required.json", [review_to_json(item) for item in reviews])
        write_markdown(
            logs_dir / "last_run_summary.md",
            run_summary(
                run_time=now,
                discovered_count=len(links),
                published_count=0,
                review_count=len(reviews),
                skipped_count=skipped_count,
                errors=errors,
            ),
        )
        (artifacts_dir / "parser_failure.txt").write_text("\n".join(errors), encoding="utf-8")
        return 3

    output_events = apply_stable_uids(parsed_events, data_dir / "stable_uids.json", now=now)
    confirmed_events = [event for event in output_events if event.status == "CONFIRMED"]
    write_json(data_dir / "lurie_events.json", [event_to_json(event) for event in output_events])
    write_json(data_dir / "review_required.json", [review_to_json(item) for item in reviews])
    write_calendar(output_events, docs_dir / "lurie-professional-events.ics", now=now)
    write_status_page(
        docs_dir / "index.html",
        run_time=now,
        published_count=len(confirmed_events),
        review_count=len(reviews),
    )
    write_markdown(
        logs_dir / "last_run_summary.md",
        run_summary(
            run_time=now,
            discovered_count=len(links),
            published_count=len(confirmed_events),
            review_count=len(reviews),
            skipped_count=skipped_count,
            errors=errors,
        ),
    )
    return 0


def validate_command(args: argparse.Namespace) -> int:
    path = Path(args.json_path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON list of events")

    required = {
        "stable_uid",
        "source_url",
        "title",
        "start_datetime",
        "end_datetime",
        "timezone",
        "confidence",
        "scraped_at",
        "raw_source_excerpt",
    }
    for index, item in enumerate(payload):
        missing = sorted(required - set(item))
        if missing:
            raise ValueError(f"Event {index} is missing required fields: {', '.join(missing)}")
        event = event_from_json(item)
        if event.timezone != "America/Chicago":
            raise ValueError(f"Event {index} has unexpected timezone: {event.timezone}")
        if event.end_datetime <= event.start_datetime:
            raise ValueError(f"Event {index} ends before it starts: {event.title}")
        if not 0 <= event.confidence <= 1:
            raise ValueError(f"Event {index} confidence must be between 0 and 1")
    print(f"Validated {len(payload)} events from {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish the Lurie professional events calendar feed.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="Fetch, parse, and publish the calendar feed.")
    update.add_argument("--days-ahead", type=int, default=180)
    update.add_argument("--timeout", type=float, default=30.0)
    update.set_defaults(func=update_command)

    validate = subparsers.add_parser("validate", help="Validate a generated lurie_events.json file.")
    validate.add_argument("json_path")
    validate.set_defaults(func=validate_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
