"""Evaluation metrics: pure functions over one question; the runner averages them over a set."""

import re
import string
from collections import Counter
from collections.abc import Hashable, Sequence

# Gold labels are document sources ("hotpotqa:<title>", "acme:<file>"), not database ids:
# ids change on every reload, sources do not.

_PUNCTUATION = set(string.punctuation)
_ARTICLES = re.compile(r"\b(a|an|the)\b")
# HotpotQA comparison questions have these as answers; token overlap would be meaningless.
_YES_NO = {"yes", "no", "noanswer"}


def recall_at_k(retrieved: Sequence[Hashable], gold: set[Hashable], k: int) -> float:
    """Share of distinct gold documents found among the first `k` retrieved items (duplicates
    allowed: one item per retrieved chunk; a `k` larger than `retrieved` is fine). Raises
    ValueError if `gold` is empty (unanswerable questions are scored by abstention, not recall)
    or k < 1."""
    if not gold:
        raise ValueError("gold must not be empty")
    if k < 1:
        raise ValueError("k must be at least 1")
    found = gold & set(retrieved[:k])
    return len(found) / len(gold)


def reciprocal_rank(retrieved: Sequence[Hashable], gold: set[Hashable]) -> float:
    """1 / rank of the first retrieved item in `gold` (rank starts at 1), 0.0 if none.
    MRR is the mean of this over questions. Raises ValueError if `gold` is empty."""
    if not gold:
        raise ValueError("gold must not be empty")
    for position, item in enumerate(retrieved):
        if item in gold:
            return 1.0 / (position + 1)
    return 0.0


def normalize_answer(text: str) -> str:
    """SQuAD/HotpotQA normalization, in this order: lowercase, remove every character of
    `string.punctuation`, remove the whole words a/an/the, collapse whitespace to single spaces."""
    text = text.lower()
    text = "".join(ch for ch in text if ch not in _PUNCTUATION)
    text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def exact_match(prediction: str, gold: str) -> float:
    """1.0 if the normalized strings are equal, else 0.0."""
    return 1.0 if normalize_answer(prediction) == normalize_answer(gold) else 0.0


def f1(prediction: str, gold: str) -> float:
    """Token F1 over normalized words, counting repeated words (multiset overlap), as in the
    HotpotQA script. Special case from that script: if either side normalizes to "yes", "no" or
    "noanswer" and the two sides differ, the score is 0.0. Then, if either side normalizes to
    empty, 1.0 when both are empty, else 0.0."""
    pred_text = normalize_answer(prediction)
    gold_text = normalize_answer(gold)
    if pred_text != gold_text and (pred_text in _YES_NO or gold_text in _YES_NO):
        return 0.0
    pred_words = pred_text.split()
    gold_words = gold_text.split()
    if not pred_words or not gold_words:
        return 1.0 if not pred_words and not gold_words else 0.0
    overlap = sum((Counter(pred_words) & Counter(gold_words)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_words)
    recall = overlap / len(gold_words)
    return 2 * precision * recall / (precision + recall)


def citation_precision(cited: Sequence[Hashable], gold: set[Hashable]) -> float | None:
    """Share of distinct cited items (document sources of cited chunks) that are in `gold`;
    two cited chunks of the same document are one source. None when nothing is cited, so the
    runner can skip it instead of counting 0 or 1."""
    distinct = set(cited)
    if not distinct:
        return None
    return len(distinct & gold) / len(distinct)


def _precision_recall(predicted: Sequence[bool], actual: Sequence[bool]) -> tuple[float, float]:
    """Precision and recall of `predicted` against `actual`; 0.0 when the denominator is 0."""
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must have the same length")
    true_positives = sum(1 for p, a in zip(predicted, actual, strict=True) if p and a)
    predicted_count = sum(predicted)
    actual_count = sum(actual)
    precision = true_positives / predicted_count if predicted_count else 0.0
    recall = true_positives / actual_count if actual_count else 0.0
    return precision, recall


def abstention_precision_recall(
    predicted: Sequence[bool], actual: Sequence[bool]
) -> tuple[float, float]:
    """Precision and recall of abstaining ("insufficient") over a question set: `predicted[i]`
    is whether the system abstained, `actual[i]` whether the question is unanswerable.
    Precision is 0.0 when nothing was abstained, recall 0.0 when nothing is unanswerable.
    Raises ValueError if the lengths differ."""
    return _precision_recall(predicted, actual)


def contradiction_precision_recall(
    predicted: Sequence[bool], actual: Sequence[bool]
) -> tuple[float, float]:
    """Precision and recall of flagging contradictions over a question set: `predicted[i]` is
    whether the system returned status "conflicting", `actual[i]` whether the question has a
    planted contradiction. Recall is the detection rate; precision catches false alarms.
    Precision is 0.0 when nothing was flagged, recall 0.0 when nothing is planted.
    Raises ValueError if the lengths differ."""
    return _precision_recall(predicted, actual)
