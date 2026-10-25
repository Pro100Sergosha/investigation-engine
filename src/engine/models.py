"""Shared data contracts between workstreams. Every stream depends on these: change by agreement."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ParsedDoc:
    """Output of any parser (stream C) and of the bulk loader (stream A).

    `text` is plain text: paragraphs separated by one blank line, headings on their own line
    prefixed with `#` (one per level, as in Markdown). Parsers that cannot see headings (PDF)
    emit paragraphs only. The structure-aware chunker relies on this shape.
    """

    source: str  # source identity, unique per document: "upload:<filename>", "hotpotqa:<title>"
    title: str
    doc_type: str  # pdf | docx | html | md | jsonl
    text: str
    metadata: dict = field(default_factory=dict)  # date, services, ...


@dataclass
class Hit:
    """One search result (stream A -> stream B)."""

    chunk_id: int
    document_id: int
    title: str
    source: str
    text: str
    score: float


@dataclass
class Claim:
    """One statement of an answer, or one contradiction between sources."""

    text: str
    citations: list[int]  # chunk ids, must be among retrieved hits


@dataclass
class Answer:
    """Final answer (stream B -> streams D, E)."""

    status: Literal["answered", "insufficient", "conflicting"]
    claims: list[Claim]
    # The direct answer in a few words ("Paris", "yes"), "" when insufficient. Claims carry the
    # evidence; this field is what EM/F1 compare with HotpotQA's short gold answers.
    answer: str = ""
    contradictions: list[Claim] = field(default_factory=list)  # each cites >= 2 chunks
    trace: list[dict] = field(default_factory=list)  # agent steps for UI/debug
