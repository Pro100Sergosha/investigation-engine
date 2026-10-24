import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from dataset import dedup, paragraphs, questions, shard, stats  # noqa: E402

from engine.models import ParsedDoc  # noqa: E402

ROWS = [
    {
        "_id": "q1",
        "question": "Were Scott Derrickson and Ed Wood of the same nationality?",
        "answer": "yes",
        "type": "comparison",
        "level": "hard",
        "supporting_facts": [["Scott Derrickson", 0], ["Ed Wood", 0], ["Ed Wood", 1]],
        "context": [
            ["Scott Derrickson", ["Scott Derrickson is an American director.", " He lives in LA."]],
            ["Ed Wood", ["Ed Wood was an American filmmaker."]],
        ],
    },
    {
        "_id": "q2",
        "question": "Which director lives in LA?",
        "answer": "Scott Derrickson",
        "type": "bridge",
        "level": "easy",
        "supporting_facts": [["Scott Derrickson", 1]],
        "context": [
            # Exact duplicate of q1's paragraph: kept once.
            ["Scott Derrickson", ["Scott Derrickson is an American director.", " He lives in LA."]],
            # Same title, different text: the first text (from q1) wins.
            ["Ed Wood", ["Ed Wood is a 1994 film."]],
            ["Empty", ["", " "]],
        ],
    },
    {
        "_id": "q3",
        "question": "Which album had the song Lucifer?",
        "answer": "Lucifer",
        "type": "bridge",
        "level": "medium",
        "supporting_facts": [["Shinee", 0]],
        "context": [["Shinee", ['Their album "Lucifer', '" was a hit.', " It sold well."]]],
    },
]


def test_sentence_join_keeps_original_spacing():
    texts = {doc.title: doc.text for doc in paragraphs(ROWS)}
    assert texts["Scott Derrickson"] == "Scott Derrickson is an American director. He lives in LA."
    assert texts["Shinee"] == 'Their album "Lucifer" was a hit. It sold well.'


def test_paragraph_fields():
    doc = paragraphs(ROWS)[0]
    assert doc.source == "hotpotqa:Scott Derrickson"
    assert doc.doc_type == "jsonl"
    assert doc.metadata == {"dataset": "hotpotqa"}


def test_dedup_rules():
    unique, counts = dedup(paragraphs(ROWS))
    assert [d.title for d in unique] == ["Scott Derrickson", "Ed Wood", "Shinee"]
    assert unique[1].text == "Ed Wood was an American filmmaker."  # first text wins
    assert counts == {"exact_duplicates": 1, "title_conflicts": 1, "empty": 1}


def test_same_text_under_other_title_is_a_duplicate():
    a = ParsedDoc("hotpotqa:A", "A", "jsonl", "same  text")
    b = ParsedDoc("hotpotqa:B", "B", "jsonl", "same text")  # equal after normalize
    unique, counts = dedup([a, b])
    assert unique == [a]
    assert counts["exact_duplicates"] == 1


def test_stats_add_up():
    docs = paragraphs(ROWS)
    unique, counts = dedup(docs)
    s = stats(ROWS, len(docs), len(unique), counts)
    assert s["paragraphs_seen"] == 6
    dropped = s["exact_duplicates"] + s["title_conflicts"] + s["empty"]
    assert s["unique_documents"] + dropped == s["paragraphs_seen"]
    assert s["by_type"] == {"comparison": 1, "bridge": 2}
    assert s["meets_50k"] is False


def test_shard_sizes_and_lines():
    docs = [ParsedDoc(f"hotpotqa:{i}", str(i), "jsonl", f"text {i}", {}) for i in range(1201)]
    shards = shard(docs, 500)
    lines = [text.splitlines() for text in shards]
    assert [len(x) for x in lines] == [500, 500, 201]
    for line in lines[2]:
        assert set(json.loads(line)) == {"source", "title", "doc_type", "text", "metadata"}


def test_questions_gold_titles_deduped_and_prefixed():
    q = questions(ROWS)[0]
    assert q["supporting_titles"] == ["hotpotqa:Scott Derrickson", "hotpotqa:Ed Wood"]
    assert set(q) == {"_id", "question", "answer", "type", "level", "supporting_titles"}
