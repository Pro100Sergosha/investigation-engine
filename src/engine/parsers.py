"""Parsers: one file -> `ParsedDoc`, one JSONL shard -> many `ParsedDoc`."""

from pathlib import Path

from engine.models import ParsedDoc


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
    raise NotImplementedError


def read_jsonl(path: Path) -> list[ParsedDoc]:
    """Read a bulk shard: one JSON object per line with the `ParsedDoc` fields
    {"source", "title", "doc_type", "text", "metadata"} ("metadata" optional).

    Blank lines are skipped. Raises ValueError naming the line number on invalid JSON or a
    missing/non-string required field.
    """
    raise NotImplementedError
