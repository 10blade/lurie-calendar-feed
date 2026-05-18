from io import BytesIO

from lurie_calendar.pdf_extract import extract_text_from_pdf_bytes


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, stream: BytesIO) -> None:
        assert stream.read() == b"%PDF-test"
        self.pages = [FakePage("Page one"), FakePage("Page two")]


def test_extract_text_from_pdf_bytes_uses_local_reader() -> None:
    text = extract_text_from_pdf_bytes(b"%PDF-test", reader_factory=FakeReader)

    assert text == "Page one\n\nPage two"
