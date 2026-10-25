"""The question-answering agent: a tool-calling loop over search, ending in a grounded answer."""

from engine.models import Answer


def ask(
    question: str, strategy: str = "structured", mode: str = "mmr", max_steps: int = 6
) -> Answer:
    """Answer `question` from the corpus with cited claims, or abstain (ADR 0005).

    `strategy` and `mode` are passed to every `search.search` call (the evaluated
    configurations); `max_steps` caps the LLM calls, and `max_steps=1` is single-shot RAG: one
    search of the question, one forced `final_answer`.
    `Answer.trace` lists the steps in order. Entries with "step": "llm" always carry
    "model" (the model that answered), "cached" (bool) and "usage" (Converse token counts):
    the eval runner paces Haiku calls and reports cost from them. Other entries are free-form.
    Never raises for model misbehaviour or a timeout: returns status "insufficient" instead.
    """
    raise NotImplementedError("wave 3: agent loop")
