from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import httpx

from lurie_calendar.models import PdfDocument, content_sha256


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot be downloaded or parsed safely."""


def extract_text_from_pdf_bytes(
    pdf_bytes: bytes,
    reader_factory: Callable[[BytesIO], object] | None = None,
) -> str:
    if reader_factory is None:
        from pypdf import PdfReader

        reader_factory = PdfReader

    reader = reader_factory(BytesIO(pdf_bytes))
    pages = getattr(reader, "pages", [])
    chunks: list[str] = []
    for page in pages:
        extract_text = getattr(page, "extract_text", None)
        if extract_text is None:
            continue
        text = extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks)


def download_and_extract_pdf(
    client: httpx.Client,
    url: str,
    cache_dir: Path | None = None,
) -> PdfDocument:
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    content = response.content
    content_type = response.headers.get("content-type", "")
    if "application/pdf" not in content_type.lower() and not content.startswith(b"%PDF"):
        raise PdfExtractionError(f"URL did not return a PDF: {url}")

    sha256 = content_sha256(content)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{sha256}.pdf").write_bytes(content)

    try:
        text = extract_text_from_pdf_bytes(content)
    except Exception as exc:  # noqa: BLE001 - pypdf raises several parser-specific exceptions.
        raise PdfExtractionError(f"Could not extract PDF text from {url}: {exc}") from exc

    return PdfDocument(
        source_url=url,
        final_url=str(response.url),
        sha256=sha256,
        text=text,
        extractable_text=bool(text.strip()),
        size_bytes=len(content),
        content_type=content_type,
    )
