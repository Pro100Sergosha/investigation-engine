"""Parsers: one file -> `ParsedDoc`, one JSONL shard -> many `ParsedDoc`."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import docx
from pypdf import PdfReader

from engine.models import ParsedDoc

# Files are untrusted uploads. None of the libraries below executes scripts or fetches URLs;
# HTML links and images are simply not read.

_DOC_TYPES = {".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html", ".md": "md"}
_HEADING = re.compile(r"^(#{1,6}) +(.+)$", re.MULTILINE)
_SERVICES = re.compile(r"^Services:(.*)$", re.MULTILINE)
_JSONL_FIELDS = ("source", "title", "doc_type", "text")


def parse(path: Path, source: str) -> ParsedDoc:
    """Parse a .pdf, .docx, .html/.htm or .md file into the `ParsedDoc.text` shape.

    `source` is the document's identity given by the caller (e.g. "upload:<filename>"); the
    file name in S3 or /tmp is not stable enough to be one. `doc_type` comes from the suffix
    (case-insensitive). Title: first heading, else the HTML <title> / DOCX core title / PDF
    metadata title, else the file stem. Metadata: whatever the format offers among "date"
    (ISO 8601 string) and "author", plus "services" for Acme docs if the text has a
    "Services: a, b" line. HTML: <script>/<style> dropped, entities decoded, h1-h6 become
    `#` headings. Raises ValueError for an unsupported suffix or a file with no text.
    """
    doc_type = _DOC_TYPES.get(path.suffix.lower())
    if doc_type is None:
        raise ValueError(f"unsupported file type: {path.suffix or '(none)'}")

    if doc_type == "pdf":
        text, format_title, metadata = _read_pdf(path)
    elif doc_type == "docx":
        text, format_title, metadata = _read_docx(path)
    elif doc_type == "html":
        text, format_title, metadata = _read_html(path)
    else:
        text, format_title, metadata = path.read_text(encoding="utf-8"), "", {}

    text = _normalize(text)
    if not text:
        raise ValueError(f"no text in {path.name}")

    heading = _HEADING.search(text)
    title = heading.group(2).strip() if heading else (format_title.strip() or path.stem)

    services = _SERVICES.search(text)
    if services:
        names = [name.strip() for name in services.group(1).split(",")]
        metadata["services"] = [name for name in names if name]

    return ParsedDoc(source=source, title=title, doc_type=doc_type, text=text, metadata=metadata)


def read_jsonl(path: Path) -> list[ParsedDoc]:
    """Read a bulk shard: one JSON object per line with the `ParsedDoc` fields
    {"source", "title", "doc_type", "text", "metadata"} ("metadata" optional).

    Blank lines are skipped. Raises ValueError naming the line number on invalid JSON or a
    missing/non-string required field.
    """
    docs = []
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path.name} line {number}: invalid JSON: {e}") from e
            if not isinstance(record, dict):
                raise ValueError(f"{path.name} line {number}: not a JSON object")
            for key in _JSONL_FIELDS:
                if not isinstance(record.get(key), str):
                    raise ValueError(f"{path.name} line {number}: {key!r} missing or not a string")
            metadata = record.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError(f"{path.name} line {number}: 'metadata' is not an object")
            docs.append(
                ParsedDoc(
                    source=record["source"],
                    title=record["title"],
                    doc_type=record["doc_type"],
                    text=record["text"],
                    metadata=metadata,
                )
            )
    return docs


def _normalize(text: str) -> str:
    """Bring any extracted text to the shape: no trailing spaces, at most one blank line in a
    row, no blank lines at the start or end."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip()
        if line == "" and (not lines or lines[-1] == ""):
            continue  # skips leading blank lines and the 2nd+ blank line of a run
        lines.append(line)
    return "\n".join(lines).strip("\n")


def _read_pdf(path: Path) -> tuple[str, str, dict]:
    reader = PdfReader(path)
    # ponytail: pypdf rarely emits blank lines, so a page usually becomes one paragraph and the
    # paragraph boundaries inside it are lost. Lines are kept as lines: the chunker joins them
    # anyway, and a "Services:" line stays findable. Upgrade path: split on vertical gaps
    # between lines with a visitor_text callback.
    paragraphs = [page.extract_text() or "" for page in reader.pages]

    info = reader.metadata
    metadata = {}
    title = ""
    if info is not None:
        title = info.title or ""
        if info.author:
            metadata["author"] = info.author
        try:
            created = info.creation_date
        except ValueError:  # malformed date in an untrusted file: keep the text, drop the date
            created = None
        if created is not None:
            metadata["date"] = created.isoformat()
    return "\n\n".join(paragraphs), title, metadata


def _read_docx(path: Path) -> tuple[str, str, dict]:
    document = docx.Document(str(path))
    # ponytail: tables, headers, footers and text boxes are ignored; body paragraphs only.
    blocks = []
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())
        if not text:
            continue
        style = paragraph.style.name if paragraph.style is not None else ""
        level = 0
        if style == "Title":
            level = 1
        elif style.startswith("Heading ") and style[len("Heading ") :].isdigit():
            level = min(int(style[len("Heading ") :]), 6)
        blocks.append("#" * level + " " + text if level else text)

    props = document.core_properties
    metadata = {}
    if props.author:
        metadata["author"] = props.author
    if props.created is not None:
        metadata["date"] = props.created.isoformat()
    return "\n\n".join(blocks), props.title or "", metadata


def _read_html(path: Path) -> tuple[str, str, dict]:
    parser = _HtmlText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    return "\n\n".join(parser.blocks), " ".join("".join(parser.title).split()), {}


class _HtmlText(HTMLParser):
    """Collects visible text as blocks: a block tag ends the paragraph being collected."""

    _BLOCK_TAGS = {
        "p", "div", "li", "br", "tr", "ul", "ol", "table", "section", "article", "blockquote",
        "pre", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    }  # fmt: skip
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # entities arrive already decoded
        self.blocks: list[str] = []
        self.title: list[str] = []
        self._current: list[str] = []
        self._skip_depth = 0  # inside <script>/<style>
        self._in_head = False
        self._in_title = False
        self._heading_level = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag == "head":
            self._in_head = True
        elif tag == "body":
            self._in_head = False  # <head> may be left unclosed
        elif tag == "title":
            self._in_title = True
        elif tag in ("td", "th"):
            self._current.append(" ")  # cells of one row stay one paragraph, words apart
        if tag in self._BLOCK_TAGS:
            self._end_block()
        if tag in self._HEADING_TAGS:
            self._heading_level = int(tag[1])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "head":
            self._in_head = False
        elif tag == "title":
            self._in_title = False
        if tag in self._BLOCK_TAGS:
            self._end_block()
        if tag in self._HEADING_TAGS:
            self._heading_level = 0

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title.append(data)
        elif not self._in_head:
            self._current.append(data)

    def close(self) -> None:
        super().close()
        self._end_block()

    def _end_block(self) -> None:
        text = " ".join("".join(self._current).split())
        self._current = []
        if not text:
            return
        if self._heading_level:
            text = "#" * self._heading_level + " " + text
        self.blocks.append(text)
