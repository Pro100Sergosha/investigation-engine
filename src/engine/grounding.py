"""Server-side grounding: the model's final answer -> `Answer` with valid citations only."""

from engine.models import Answer


def build_answer(raw: dict, retrieved: set[int]) -> Answer:
    """Validate the `final_answer` tool input against the chunk ids retrieved in this run.

    `raw` = {"status": str, "claims": [{"text": str, "citations": [int]}],
             "contradictions": [{"text": str, "citations": [int]}]}; "contradictions" may be absent.
    Rules, in order:
    1. Wrong shape (not a dict, "claims" not a list, an item without a string "text" or a list
       "citations") -> ValueError, so the agent can ask the model again.
    2. A citation is valid if it is an int (not bool) in `retrieved`; others are removed,
       duplicates are removed keeping first order. A claim with blank text or no valid citation
       is dropped; a contradiction with fewer than 2 distinct valid citations is dropped.
    3. Status: "conflicting" if any contradiction survives; else "insufficient" if no claim
       survives or the model said "insufficient" (surviving claims are kept as partial facts);
       else "answered". An unknown model status is treated as "answered".
    The returned trace always holds exactly one entry listing what was dropped (raw items):
    {"step": "grounding", "dropped_claims": [...], "dropped_contradictions": [...]}.
    """
    raise NotImplementedError
