"""Shared data contracts between workstreams. Every stream depends on these: change by agreement."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ParsedDoc:
    """Output of any parser (stream C) and of the bulk loader (stream A)."""

    source: str  # file path or dataset id, preserved as source identity
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
    text: str
    score: float


@dataclass
class Claim:
    text: str
    citations: list[int]  # chunk ids, must be among retrieved hits


@dataclass
class Answer:
    """Final answer (stream B -> streams D, E)."""

    status: Literal["answered", "insufficient", "conflicting"]
    claims: list[Claim]
    contradictions: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)  # agent steps for UI/debug
