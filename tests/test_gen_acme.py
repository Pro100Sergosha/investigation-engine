import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gen_acme  # noqa: E402

from engine.parsers import parse  # noqa: E402

ACME = Path(__file__).resolve().parent.parent / "data" / "acme"
SPEC = gen_acme.load_spec()

TINY = {
    "id": "INC-901",
    "date": "2026-03-12",
    "services": ["payments-api", "ledger"],
    "title": "Postmortem: test outage",
    "summary": "A test.",
    "facts": ["impact began at 14:02 UTC", "1,240 merchants", "max_connections from 200 to 20"],
    "refs": ["CHG-1042"],
}
# A body as the model writes it: smart quotes, an en dash, a stray title and bold markers.
BODY = (
    "# Postmortem\n\n## Summary\n\n**Impact began at 14:02 UTC** and hit 1,240 merchants.\n\n"
    "## Root cause\n\n- CHG-1042 changed max_connections from 200 to 20 – the “pool” "
    "was exhausted.\n"
)


# Spec


def test_committed_spec_is_valid():
    assert gen_acme.validate(SPEC) == []


def _break_duplicate_id(spec):
    spec["documents"][1]["id"] = spec["documents"][0]["id"]


def _break_bad_id(spec):
    spec["documents"][0]["id"] = "INC 7/a"


def _break_unknown_ref(spec):
    spec["documents"][0]["refs"] = ["CHG-9999"]


def _break_contradiction_doc(spec):
    spec["contradictions"][0]["claims"][0]["doc"] = "INC-999"


def _break_contradiction_same_values(spec):
    claims = spec["contradictions"][0]["claims"]
    claims[1]["value"] = claims[0]["value"]


def _break_contradiction_not_a_fact(spec):
    spec["contradictions"][0]["claims"][0]["value"] = "23:59 UTC"


def _break_gold(spec):
    spec["questions"][0]["gold"] = ["RB-99"]


def _break_unanswerable_with_gold(spec):
    q = next(q for q in spec["questions"] if q["type"] == "unanswerable")
    q["gold"] = ["INC-301"]


def _break_gap_word_in_spec(spec):
    spec["documents"][0]["facts"].append("lost revenue")


@pytest.mark.parametrize(
    "break_spec",
    [
        _break_duplicate_id,
        _break_bad_id,
        _break_unknown_ref,
        _break_contradiction_doc,
        _break_contradiction_same_values,
        _break_contradiction_not_a_fact,
        _break_gold,
        _break_unanswerable_with_gold,
        _break_gap_word_in_spec,
    ],
)
def test_validate_reports_each_broken_rule(break_spec):
    spec = copy.deepcopy(SPEC)
    break_spec(spec)
    assert gen_acme.validate(spec)


def test_file_names_are_unique_and_upload_safe():
    names = [gen_acme.file_name(doc["id"]) for doc in SPEC["documents"]]
    assert len(set(names)) == len(names)
    assert gen_acme.file_name("INC-301") == "acme-inc-301.pdf"
    assert gen_acme.source("RB-03") == "upload:acme-rb-03.docx"


# Checks


def test_missing_facts_found_and_missing():
    text = "Impact began at 14:02 UTC."
    assert gen_acme.missing_facts(text, ["14:02 UTC", "CHG-1042"]) == ["CHG-1042"]


def test_missing_facts_ignores_case_and_line_breaks():
    # A PDF line break inside a fact, and "Approved by" at the start of a sentence.
    text = "The change was rolled back\nat 14:41 UTC. Approved by Oskar  Lind."
    assert (
        gen_acme.missing_facts(text, ["rolled back at 14:41 UTC", "approved by Oskar Lind"]) == []
    )


def test_problems_name_missing_facts_and_gap_words():
    gaps = [{"id": "G01", "what": "revenue lost", "forbidden": ["revenue"]}]
    problems = gen_acme.problems_in("CHG-1042 cost us Revenue.", TINY, gaps)
    assert "missing '1,240 merchants'" in problems
    assert "must not mention 'revenue'" in problems
    assert not any("CHG-1042" in p for p in problems)


def test_sanitize_makes_ascii():
    assert gen_acme.sanitize("“pool” – it’s 5×2 → Renée") == ('"pool" - it\'s 5x2 -> Renee')


# Rendering


def test_blocks_drop_fences_bold_and_promote_stray_titles():
    assert gen_acme.blocks("```\n# Title\n**Bold** text\n* item\n### Sub\n```") == [
        ("h2", "Title"),
        ("p", "Bold text"),
        ("li", "item"),
        ("h3", "Sub"),
    ]


@pytest.mark.parametrize("prefix", ["INC", "CHG", "RB", "STS"])
def test_render_round_trips_through_the_parser(tmp_path, prefix):
    doc = {**TINY, "id": f"{prefix}-901"}
    path = gen_acme.render(doc, BODY, tmp_path)
    parsed = parse(path, gen_acme.source(doc["id"]))
    assert parsed.title == "Postmortem: test outage"
    assert parsed.metadata["services"] == ["payments-api", "ledger"]
    assert gen_acme.missing_facts(parsed.text, gen_acme.required_facts(doc)) == []
    assert '"pool"' in parsed.text  # sanitized, not dropped
    if prefix in ("INC", "RB"):  # PDF and DOCX carry the date in their metadata
        assert parsed.metadata["date"].startswith("2026-03-12")


def test_pdf_breaks_long_documents_into_pages(tmp_path):
    body = "\n".join(f"Paragraph {i} " + "word " * 40 for i in range(60)) + "\nlast fact 42"
    path = gen_acme.render({**TINY, "facts": ["last fact 42"], "refs": []}, body, tmp_path)
    parsed = parse(path, "upload:x.pdf")
    assert parsed.text.count("Paragraph") == 60
    assert "last fact 42" in parsed.text
    assert path.read_bytes().count(b"/Type /Page ") > 1


# Generation


def test_generate_retries_once_naming_the_missing_fact(tmp_path, monkeypatch):
    replies = ["Impact began at 14:02 UTC. See CHG-1042.", BODY]
    calls = []

    def converse(system, messages):
        calls.append(messages)
        text = replies[len(calls) - 1]
        return {
            "message": {"role": "assistant", "content": [{"text": text}]},
            "cached": False,
            "usage": {"inputTokens": 100, "outputTokens": 50},
            "model": "haiku",
        }

    monkeypatch.setattr(gen_acme.llm, "converse", converse)
    monkeypatch.setattr(gen_acme, "PACE_SECONDS", 0)
    stats = gen_acme._Stats()
    assert gen_acme.generate(TINY, SPEC, tmp_path, stats) == []
    assert len(calls) == 2
    feedback = calls[1][-1]["content"][0]["text"]
    assert "1,240 merchants" in feedback and "max_connections from 200 to 20" in feedback
    assert stats.calls == 2 and stats.output_tokens == 100


# Labels


def test_questions_have_the_runner_format():
    rows = gen_acme.questions(SPEC)
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        assert set(row) == {"id", "question", "type", "answer", "gold_sources"}
        assert row["type"] in gen_acme.QUESTION_TYPES
        assert all(s.startswith("upload:acme-") for s in row["gold_sources"])
        if row["type"] == "unanswerable":
            assert row["answer"] is None and row["gold_sources"] == []
        else:
            assert row["answer"] and row["gold_sources"]


def test_contradictory_question_labels_come_from_the_contradiction():
    row = next(r for r in gen_acme.questions(SPEC) if r["type"] == "contradictory")
    assert row["answer"] == "conflicting: 14:02 UTC (INC-301) vs 14:15 UTC (STS-301)"
    assert row["gold_sources"] == ["upload:acme-inc-301.pdf", "upload:acme-sts-301.html"]


def test_committed_labels_match_the_spec():
    """If this fails after a spec edit: `make acme-labels`."""
    assert (ACME / "GROUND_TRUTH.md").read_text(encoding="utf-8") == gen_acme.ground_truth(SPEC)
    lines = (ACME / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == gen_acme.questions(SPEC)


def test_committed_corpus_holds_every_fact_and_no_gap_word():
    """The committed files are the corpus: each one parses and still says what the spec says."""
    for doc in SPEC["documents"]:
        path = ACME / "files" / gen_acme.file_name(doc["id"])
        text = parse(path, gen_acme.source(doc["id"])).text
        assert gen_acme.problems_in(text, doc, SPEC["gaps"]) == [], doc["id"]
