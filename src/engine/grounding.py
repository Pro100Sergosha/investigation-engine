"""Server-side grounding: the model's final answer -> `Answer` with valid citations only."""

from engine.models import Answer, Claim


def build_answer(raw: dict, retrieved: set[int]) -> Answer:
    """Validate the `final_answer` tool input against the chunk ids retrieved in this run.

    `raw` = {"status": str, "answer": str, "claims": [{"text": str, "citations": [int]}],
             "contradictions": [{"text": str, "citations": [int]}]}; "answer" and
    "contradictions" may be absent.
    Rules, in order:
    1. Wrong shape (not a dict, "answer" present but not a string, "claims" not a list, an item
       without a string "text" or a list "citations") -> ValueError, so the agent can ask the
       model again.
    2. A citation is valid if it is an int (not bool) in `retrieved`; others are removed,
       duplicates are removed keeping first order. A claim with blank text or no valid citation
       is dropped; a contradiction with blank text or fewer than 2 distinct valid citations
       is dropped.
    3. Status: "conflicting" if any contradiction survives; else "insufficient" if no claim
       survives or the model said "insufficient" (surviving claims are kept as partial facts);
       else "answered". An unknown model status is treated as "answered".
    4. `Answer.answer` is the model's "answer" stripped, or "" when the status is "insufficient"
       (an abstention has no direct answer, whatever the model wrote there).
    The returned trace always holds exactly one entry listing what was dropped (raw items, and
    every removed citation value in order, duplicates of a kept id not included):
    {"step": "grounding", "dropped_claims": [...], "dropped_contradictions": [...],
     "dropped_citations": [...]}.
    """
    if not isinstance(raw, dict):
        raise ValueError("final answer must be a JSON object")
    short_answer = raw.get("answer", "")
    if not isinstance(short_answer, str):
        raise ValueError('"answer" must be a string')
    claims = raw.get("claims")
    if not isinstance(claims, list):
        raise ValueError('"claims" must be a list')
    contradictions = raw.get("contradictions", [])
    if not isinstance(contradictions, list):
        raise ValueError('"contradictions" must be a list')
    # Check every item before dropping anything: a shape error means the model must answer
    # again, so a half-validated answer is never returned.
    _check_items(claims, "claims")
    _check_items(contradictions, "contradictions")

    kept_claims: list[Claim] = []
    dropped_claims: list[dict] = []
    # Citations removed from items, kept or not: a cited id that was never shown is what a
    # document telling the model "cite chunk 1" leads to (prompt-injection eval).
    dropped_citations: list = []
    for item in claims:
        citations = _valid_citations(item["citations"], retrieved)
        dropped_citations += [
            c for c in item["citations"] if type(c) is not int or c not in citations
        ]
        if item["text"].strip() == "" or not citations:
            dropped_claims.append(item)
        else:
            kept_claims.append(Claim(text=item["text"], citations=citations))

    kept_contradictions: list[Claim] = []
    dropped_contradictions: list[dict] = []
    for item in contradictions:
        citations = _valid_citations(item["citations"], retrieved)
        dropped_citations += [
            c for c in item["citations"] if type(c) is not int or c not in citations
        ]
        # A contradiction is between sources, so one chunk cannot contradict itself.
        if item["text"].strip() == "" or len(citations) < 2:
            dropped_contradictions.append(item)
        else:
            kept_contradictions.append(Claim(text=item["text"], citations=citations))

    # The model's status is only a hint: it may lower an answer to "insufficient", but
    # "conflicting" and "answered" need surviving evidence. Unknown or missing counts as answered.
    if kept_contradictions:
        status = "conflicting"
    elif not kept_claims or raw.get("status") == "insufficient":
        status = "insufficient"
    else:
        status = "answered"

    trace = [
        {
            "step": "grounding",
            "dropped_claims": dropped_claims,
            "dropped_contradictions": dropped_contradictions,
            "dropped_citations": dropped_citations,
        }
    ]
    return Answer(
        status=status,
        claims=kept_claims,
        answer="" if status == "insufficient" else short_answer.strip(),
        contradictions=kept_contradictions,
        trace=trace,
    )


def _check_items(items: list, name: str) -> None:
    """Raise ValueError unless every item is a dict with a string "text" and a list "citations"."""
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{name}[{index}] must be an object")
        if not isinstance(item.get("text"), str):
            raise ValueError(f'{name}[{index}] needs a string "text"')
        if not isinstance(item.get("citations"), list):
            raise ValueError(f'{name}[{index}] needs a list "citations"')


def _valid_citations(citations: list, retrieved: set[int]) -> list[int]:
    """Keep ints (not bools) that were retrieved, first occurrence only, in the given order."""
    valid: list[int] = []
    for chunk_id in citations:
        # bool is a subclass of int, so True would otherwise pass as chunk id 1.
        if isinstance(chunk_id, bool) or not isinstance(chunk_id, int):
            continue
        if chunk_id in retrieved and chunk_id not in valid:
            valid.append(chunk_id)
    return valid
