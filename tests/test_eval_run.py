"""Tests for eval/run.py: question validation, scoring, judge parsing, pacing, cost; no network."""

import json

import pytest

from engine import agent, llm, search
from engine.models import Answer, Claim, Hit
from eval import run

GOOD = [
    {
        "id": "hp-1",
        "question": "Who directed X?",
        "type": "multi_hop",
        "answer": "Ann",
        "gold_sources": ["hotpotqa:X", "hotpotqa:Ann"],
    },
    {
        "id": "hp-unanswerable-1",
        "question": "What did X cost?",
        "type": "unanswerable",
        "answer": None,
        "gold_sources": [],
    },
    {
        "id": "acme-1",
        "question": "Why did payments fail?",
        "type": "contradictory",
        "answer": None,
        "gold_sources": ["upload:a.pdf", "upload:b.md"],
    },
]


def write(tmp_path, lines, name="q.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_good_files_in_order_skipping_blank_lines(tmp_path):
    first = write(tmp_path, [json.dumps(GOOD[0]), "", json.dumps(GOOD[1])], "a.jsonl")
    second = write(tmp_path, [json.dumps(GOOD[2])], "b.jsonl")
    assert run.load_questions([first, second]) == GOOD


def test_committed_question_set_is_valid():
    questions = run.load_questions([run.QUESTIONS])
    assert len(questions) >= 20


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"type": "trivia"}, "unknown type"),
        ({"type": "unanswerable"}, "unanswerable question has answer null"),
        ({"gold_sources": []}, "needs gold_sources"),
        ({"answer": 3}, "answer must be"),
        ({"question": " "}, "question must be"),
    ],
)
def test_bad_question_names_the_line(tmp_path, change, message):
    path = write(tmp_path, [json.dumps(GOOD[1]), json.dumps(GOOD[0] | change)])
    with pytest.raises(ValueError, match=f"q.jsonl:2: .*{message}"):
        run.load_questions([path])


def test_duplicate_id_across_files_fails(tmp_path):
    first = write(tmp_path, [json.dumps(GOOD[0])], "a.jsonl")
    second = write(tmp_path, [json.dumps(GOOD[0])], "b.jsonl")
    with pytest.raises(ValueError, match="b.jsonl:1: duplicate id 'hp-1'"):
        run.load_questions([first, second])


def test_bad_json_and_missing_field_fail(tmp_path):
    with pytest.raises(ValueError, match="q.jsonl:1: bad JSON"):
        run.load_questions([write(tmp_path, ['{"id": "x",'])])
    missing = {k: v for k, v in GOOD[0].items() if k != "gold_sources"}
    with pytest.raises(ValueError, match="q.jsonl:1: a question is an object"):
        run.load_questions([write(tmp_path, [json.dumps(missing)])])


def hit(source):
    return Hit(chunk_id=0, document_id=0, title="", source=source, text="", score=0.0)


def test_retrieval_sweep_scores_sources_of_every_strategy_and_mode(monkeypatch):
    calls = []

    def fake_search(query, k, strategy, mode):
        calls.append((query, k, strategy, mode))
        if mode == "dense":  # gold "hotpotqa:Ann" at rank 2, "hotpotqa:X" at rank 7
            return [hit(s) for s in ["o", "hotpotqa:Ann", "o", "o", "o", "o", "hotpotqa:X"]]
        if mode == "hybrid":
            raise RuntimeError("database gone")
        return [hit("hotpotqa:X"), hit("hotpotqa:X")]  # one of two gold docs, twice

    monkeypatch.setattr(search, "search", fake_search)
    monkeypatch.setattr(run.time, "sleep", lambda seconds: None)
    records = run.run_retrieval(GOOD)

    assert [r["id"] for r in records] == ["hp-1", "acme-1"]  # unanswerable skipped
    # 2 questions x 6 searches, plus 2 retries of each failing hybrid search (2 x 2 of them).
    assert len(calls) == 2 * 6 + 2 * 2 * 2 and {c[1] for c in calls} == {10}
    dense = records[0]["runs"]["structured/dense"]
    assert (dense["recall@5"], dense["recall@10"], dense["rr"]) == (0.5, 1.0, 0.5)
    mmr = records[0]["runs"]["fixed/mmr"]
    assert (mmr["recall@5"], mmr["recall@10"], mmr["rr"]) == (0.5, 0.5, 1.0)
    assert "error" in records[0]["runs"]["fixed/hybrid"]

    summary = run.summarize_retrieval(records)
    assert summary["fixed/hybrid"] == {
        "n": 0,
        "errors": 2,
        "recall@5": None,
        "recall@10": None,
        "mrr": None,
        "by_type": {},
    }
    assert summary["fixed/dense"]["n"] == 2
    assert summary["fixed/dense"]["by_type"]["multi_hop"]["mrr"] == 0.5
    assert summary["fixed/dense"]["by_type"]["contradictory"]["mrr"] == 0.0


def test_retrieval_retries_a_throttled_search(monkeypatch):
    attempts = []

    def fake_search(query, k, strategy, mode):
        attempts.append(mode)
        if len(attempts) == 1:
            raise RuntimeError("ThrottlingException")
        return [hit("hotpotqa:Ann")]

    waits = []
    monkeypatch.setattr(search, "search", fake_search)
    monkeypatch.setattr(run.time, "sleep", waits.append)
    record = run._retrieve(GOOD[0], "fixed", "dense")
    assert "error" not in record and record["rr"] == 1.0
    assert waits == [run.SEARCH_RETRY_SECONDS]


def llm_step(model=llm.HAIKU, cached=False, tokens_in=1000, tokens_out=100):
    usage = {"inputTokens": tokens_in, "outputTokens": tokens_out}
    return {"step": "llm", "model": model, "cached": cached, "usage": usage}


def test_answer_run_records_sources_usage_metrics_and_paces(monkeypatch):
    asked = []

    def fake_ask(question, strategy, mode, max_steps):
        asked.append((strategy, mode, max_steps))
        if question.startswith("Why"):
            raise RuntimeError("boom")
        if question.startswith("What did"):
            return Answer(status="insufficient", claims=[], trace=[llm_step(cached=True)])
        trace = [llm_step(), {"step": "search"}, llm_step(model=llm.GPT_OSS)]
        claims = [Claim("Ann directed X.", [11, 12]), Claim("Gone.", [99])]
        return Answer(status="answered", claims=claims, answer="Ann", trace=trace)

    def fake_chunks(ids):
        known = {11: "hotpotqa:X", 12: "hotpotqa:Other"}
        return [{"chunk_id": i, "source": known[i]} for i in ids if i in known]

    judged = []

    def fake_converse(system, messages, model, max_tokens):
        judged.append(model)
        text = 'Verdict: {"correct": true, "reason": "same person"}'
        usage = {"inputTokens": 200, "outputTokens": 20}
        return {"message": {"content": [{"text": text}]}, "model": model, "cached": False,
                "usage": usage}  # fmt: skip

    monkeypatch.setattr(agent, "ask", fake_ask)
    monkeypatch.setattr(search, "get_chunks", fake_chunks)
    monkeypatch.setattr(llm, "converse", fake_converse)
    pauses = []
    records = run.run_answers(GOOD, run.ANSWER_CONFIGS["single-shot"], sleep=pauses.append)

    assert asked == [("fixed", "mmr", 1)] * 3
    answered, abstained, failed = records
    assert answered["cited_sources"] == ["hotpotqa:X", "hotpotqa:Other"]
    assert answered["claims"][1] == {"text": "Gone.", "citations": [99], "sources": []}
    assert answered["models"] == {llm.HAIKU: 1, llm.GPT_OSS: 1}
    assert answered["uncached_haiku_calls"] == 1 and answered["fallback"] is True
    assert (answered["em"], answered["f1"]) == (1.0, 1.0)
    assert answered["citation_precision"] == 0.5
    assert answered["judge_correct"] is True and judged == [llm.QWEN]
    assert abstained["judge_correct"] is None and abstained["em"] is None  # no gold answer
    assert abstained["uncached_haiku_calls"] == 0
    assert "boom" in failed["error"]
    assert pauses[1] == 0.0 and pauses[0] > 5 and pauses[2] > 5  # error: assume max_steps calls

    summary = run.summarize_answers(records)
    assert summary["errors"] == 1 and summary["judge_failures"] == 0
    assert summary["abstention"] == {"precision": 1.0, "recall": 1.0}
    assert summary["fallback_share"] == 0.5
    assert summary["input_tokens"] == 3000  # cached tokens count, they are what the answer used
    haiku = (1000 * 1.10 + 100 * 5.50) / 1e6
    gpt_oss = (1000 * 0.15 + 100 * 0.60) / 1e6
    judge = (200 * 0.22 + 20 * 0.88) / 1e6
    assert summary["cost_usd"] == round(haiku + gpt_oss + judge, 4)
    assert "| single-shot | 3 | 1 | 0 |" in run.markdown("single-shot", summary)


def test_abstention_on_answerable_question_is_incorrect_without_a_judge_call(monkeypatch):
    monkeypatch.setattr(llm, "converse", lambda *a, **k: pytest.fail("judge called"))
    record = {"status": "insufficient", "answer": "", "claims": []}
    assert run.judge(GOOD[0], record)["judge_correct"] is False


def test_judge_failure_is_recorded_not_raised(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("throttled")

    monkeypatch.setattr(llm, "converse", broken)
    record = {"status": "answered", "answer": "Ann", "claims": [], "contradictions": []}
    verdict = run.judge(GOOD[0], record)
    assert verdict["judge_correct"] is None and "throttled" in verdict["judge_error"]


def test_judge_sees_status_and_contradictions():
    record = {
        "status": "conflicting",
        "answer": "14:02 UTC",
        "claims": [],
        "contradictions": [{"text": "INC-301 says 14:02 UTC, STS-301 says 14:15 UTC"}],
    }
    prompt = run.judge_prompt(GOOD[0], record)
    assert "System status: conflicting" in prompt and "STS-301 says 14:15 UTC" in prompt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"correct": false, "reason": "wrong year"}', {"correct": False, "reason": "wrong year"}),
        ('```json\n{"correct": true}\n```', {"correct": True, "reason": ""}),
        ("I think it is correct.", None),
        ('{"correct": "yes"}', None),
        ('{"correct": true', None),
    ],
)
def test_parse_verdict(text, expected):
    assert run.parse_verdict(text) == expected


def test_summary_means_skip_none_and_group_by_type():
    def rec(kind, status, em, judged, seconds):
        return {"type": kind, "status": status, "em": em, "f1": em, "judge_correct": judged,
                "citation_precision": None, "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0, "fallback": False, "seconds": seconds}  # fmt: skip

    records = [
        rec("multi_hop", "answered", 1.0, True, 1.0),
        rec("multi_hop", "answered", 0.0, None, 3.0),
        rec("unanswerable", "answered", None, None, 2.0),
        rec("contradictory", "conflicting", None, None, 10.0),
    ]
    summary = run.summarize_answers(records)
    assert summary["em"] == 0.5 and summary["judge_correct"] == 1.0
    assert summary["citation_precision"] is None
    assert summary["by_type"]["multi_hop"] == {
        "n": 2,
        "em": 0.5,
        "f1": 0.5,
        "judge_correct": 1.0,
        "citation_precision": None,
    }
    assert summary["abstention"] == {"precision": 0.0, "recall": 0.0}  # missed the unanswerable
    assert summary["contradiction"] == {"precision": 1.0, "recall": 1.0}
    assert (summary["latency_p50"], summary["latency_p95"]) == (2.0, 10.0)


def test_pause_spaces_uncached_haiku_calls_six_seconds_apart():
    assert run.pause(3, 5.0) == 13.0
    assert run.pause(1, 9.0) == 0.0
    assert run.pause(0, 0.0) == 0.0


def test_cost_skips_cached_calls_and_prices_unknown_models_as_haiku():
    calls = [
        llm_step(tokens_in=1_000_000, tokens_out=0),
        llm_step(cached=True),
        llm_step(model="some.new-model", tokens_in=0, tokens_out=1_000_000),
    ]
    assert run.cost(calls) == 1.10 + 5.50
