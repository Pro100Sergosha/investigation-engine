"""Evaluation metrics: pure functions over one question; the runner averages them over a set."""

from collections.abc import Hashable, Sequence

# Gold labels are document sources ("hotpotqa:<title>", "acme:<file>"), not database ids:
# ids change on every reload, sources do not.


def recall_at_k(retrieved: Sequence[Hashable], gold: set[Hashable], k: int) -> float:
    """Share of gold documents found among the first `k` retrieved items (duplicates allowed:
    one item per retrieved chunk). Raises ValueError if `gold` is empty (unanswerable questions
    are scored by abstention, not recall) or k < 1."""
    raise NotImplementedError


def reciprocal_rank(retrieved: Sequence[Hashable], gold: set[Hashable]) -> float:
    """1 / rank of the first retrieved item in `gold` (rank starts at 1), 0.0 if none.
    MRR is the mean of this over questions. Raises ValueError if `gold` is empty."""
    raise NotImplementedError


def normalize_answer(text: str) -> str:
    """SQuAD/HotpotQA normalization: lowercase, drop punctuation, drop articles a/an/the,
    collapse whitespace."""
    raise NotImplementedError


def exact_match(prediction: str, gold: str) -> float:
    """1.0 if the normalized strings are equal, else 0.0."""
    raise NotImplementedError


def f1(prediction: str, gold: str) -> float:
    """Token F1 over normalized words, counting repeated words (multiset overlap), as in the
    HotpotQA script. If either side normalizes to empty, 1.0 when both are empty, else 0.0."""
    raise NotImplementedError


def citation_precision(cited: Sequence[Hashable], gold: set[Hashable]) -> float | None:
    """Share of cited items (document sources of cited chunks) that are in `gold`.
    None when nothing is cited, so the runner can skip it instead of counting 0 or 1."""
    raise NotImplementedError


def abstention_precision_recall(
    predicted: Sequence[bool], actual: Sequence[bool]
) -> tuple[float, float]:
    """Precision and recall of abstaining ("insufficient") over a question set: `predicted[i]`
    is whether the system abstained, `actual[i]` whether the question is unanswerable.
    Precision is 0.0 when nothing was abstained, recall 0.0 when nothing is unanswerable.
    Raises ValueError if the lengths differ."""
    raise NotImplementedError
