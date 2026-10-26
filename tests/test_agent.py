"""Tests for agent.py: the loop with fake llm.converse and search.search, no network."""

import copy

import pytest
from botocore.exceptions import ClientError

from engine import agent, llm, search
from engine.models import Hit

USAGE = {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}


def _hit(chunk_id: int, document_id: int = 1) -> Hit:
    return Hit(chunk_id, document_id, f"Doc {document_id}", f"test:{document_id}", "text", 0.5)


def _tool_call(name: str, args: dict, use_id: str = "t1") -> dict:
    return {"toolUse": {"toolUseId": use_id, "name": name, "input": args}}


def _reply(*blocks: dict, stop: str = "tool_use") -> dict:
    return {
        "message": {"role": "assistant", "content": list(blocks)},
        "stop_reason": stop,
        "usage": USAGE,
        "model": llm.HAIKU,
        "cached": False,
    }


def _final(citations: list, answer: str = "Paris", status: str = "answered") -> dict:
    claims = [{"text": "Paris is the capital.", "citations": citations}]
    return _tool_call("final_answer", {"status": status, "answer": answer, "claims": claims})


class FakeLLM:
    """Plays back replies (an exception is raised) and records each call's arguments."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, system, messages, **kwargs):
        # A deep copy: the agent appends to its history after the call.
        self.calls.append({"messages": copy.deepcopy(messages), **kwargs})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def fake(monkeypatch):
    """Fake LLM (script set by each test) and a search that returns chunk 10 + query length."""
    model = FakeLLM()
    searches = []

    def fake_search(query, k=10, strategy="structured", mode="mmr"):
        searches.append({"query": query, "k": k, "strategy": strategy, "mode": mode})
        return [_hit(10), _hit(20 + len(searches), document_id=2)]

    monkeypatch.setattr(llm, "converse", model)
    monkeypatch.setattr(search, "search", fake_search)
    model.searches = searches
    return model


def test_search_then_final_answer(fake):
    fake.script = [
        _reply({"text": "Searching."}, _tool_call("search", {"query": "capital"})),
        _reply(_final([10, 22])),
    ]
    answer = agent.ask("What is the capital?", strategy="fixed", mode="dense")
    assert answer.status == "answered" and answer.answer == "Paris"
    assert answer.claims[0].citations == [10, 22]  # 22 came from the tool's search
    # Seed search, then the model's: both with the evaluated configuration.
    assert [(s["query"], s["strategy"], s["mode"]) for s in fake.searches] == [
        ("What is the capital?", "fixed", "dense"),
        ("capital", "fixed", "dense"),
    ]
    # The seeded hits are in the first user message; the second call sees the tool result.
    assert '"chunk_id": 21' in fake.calls[0]["messages"][0]["content"][0]["text"]
    result = fake.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert result["toolUseId"] == "t1" and '"chunk_id": 22' in result["content"][0]["text"]
    assert [e["step"] for e in answer.trace] == ["search", "llm", "search", "llm", "grounding"]


def test_llm_trace_entries_carry_model_cached_usage(fake):
    fake.script = [_reply(_final([10]))]
    answer = agent.ask("q")
    llm_entries = [e for e in answer.trace if e["step"] == "llm"]
    assert llm_entries and all(
        e["model"] == llm.HAIKU and e["cached"] is False and e["usage"] == USAGE
        for e in llm_entries
    )


def test_model_is_passed_to_every_call(fake):
    fake.script = [_reply(_tool_call("search", {"query": "a"})), _reply(_final([10]))]
    agent.ask("q", model=llm.GPT_OSS)
    assert [call["model"] for call in fake.calls] == [llm.GPT_OSS, llm.GPT_OSS]
    fake.script = [_reply(_final([10]))]
    agent.ask("q")
    assert fake.calls[-1]["model"] == llm.HAIKU


def test_last_step_forces_final_answer(fake):
    fake.script = [
        _reply(_tool_call("search", {"query": "a"})),
        _reply(_final([10])),
    ]
    agent.ask("q", max_steps=2)
    free, forced = fake.calls
    assert free["tools"] == agent.TOOLS and free["tool_choice"] is None
    assert free["cache_history"] is True
    assert forced["tools"] == [agent.FINAL_ANSWER_TOOL]
    assert forced["tool_choice"] == {"tool": {"name": "final_answer"}}
    assert forced["cache_history"] is False


def test_max_steps_1_is_single_shot(fake):
    fake.script = [_reply(_final([21]))]
    answer = agent.ask("q", max_steps=1)
    assert len(fake.calls) == 1 and len(fake.searches) == 1
    assert fake.calls[0]["tool_choice"] == {"tool": {"name": "final_answer"}}
    assert answer.status == "answered" and answer.claims[0].citations == [21]


def test_text_instead_of_tool_call_is_reprompted(fake):
    fake.script = [_reply({"text": "Paris."}, stop="end_turn"), _reply(_final([10]))]
    answer = agent.ask("q")
    assert answer.status == "answered"
    history = fake.calls[1]["messages"]
    assert history[-2]["role"] == "assistant" and history[-1]["role"] == "user"
    assert history[-1]["content"] == [{"text": agent._NO_TOOL_CALL}]
    assert {"step": "reprompt", "reason": "text instead of a tool call"} in answer.trace


def test_malformed_final_answer_is_sent_back(fake):
    bad = _tool_call("final_answer", {"status": "answered", "claims": "Paris"}, use_id="bad")
    fake.script = [_reply(bad), _reply(_final([10]))]
    answer = agent.ask("q")
    assert answer.status == "answered"
    result = fake.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert result["toolUseId"] == "bad" and result["content"][0]["text"].startswith("Error:")


def test_claims_sent_as_a_json_string_are_decoded(fake):
    claims = '[{"text": "Paris is the capital.", "citations": [10]}]'
    final = _tool_call("final_answer", {"status": "answered", "answer": "Paris", "claims": claims})
    fake.script = [_reply(final)]
    answer = agent.ask("q")
    assert len(fake.calls) == 1 and answer.claims[0].citations == [10]


def test_empty_reply_on_max_tokens_is_not_appended(fake):
    fake.script = [_reply(stop="max_tokens"), _reply(_final([10]))]
    agent.ask("q")
    history = fake.calls[1]["messages"]
    assert len(history) == 1 and history[0]["role"] == "user"  # no empty assistant turn
    assert history[0]["content"][-1] == {"text": agent._EMPTY_REPLY}


def test_deadline_reached_abstains_without_another_call(fake, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])

    def slow(reply):
        def call(system, messages, **kwargs):
            clock[0] += 50  # 80 - 50 = 30 s left: less than one attempt
            return reply

        return call

    monkeypatch.setattr(llm, "converse", slow(_reply(_tool_call("search", {"query": "a"}))))
    answer = agent.ask("q")
    assert answer.status == "insufficient" and answer.answer == ""
    assert [e["step"] for e in answer.trace] == ["search", "llm", "search", "deadline"]


def test_little_time_left_forces_final_answer(fake, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])
    fake.script = [_reply(_final([10]))]
    fast_search = search.search

    def slow_search(*args, **kwargs):
        # ask() set its deadline at 0; the seed search leaves less than FORCE_BELOW_SECONDS.
        clock[0] = agent.DEADLINE_SECONDS - agent.FORCE_BELOW_SECONDS + 1
        return fast_search(*args, **kwargs)

    monkeypatch.setattr(search, "search", slow_search)
    agent.ask("q")  # max_steps=6, yet the first call is the last one
    assert fake.calls[0]["tool_choice"] == {"tool": {"name": "final_answer"}}


def test_bedrock_error_abstains(fake, capsys):
    error = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "Converse")
    fake.script = [error]
    answer = agent.ask("q")
    assert answer.status == "insufficient" and answer.claims == []
    assert (
        answer.trace[-1]["step"] == "error" and "ThrottlingException" in answer.trace[-1]["error"]
    )
    assert "Bedrock error" in capsys.readouterr().out


def test_citation_of_unretrieved_chunk_is_dropped(fake):
    fake.script = [_reply(_final([10, 999]))]
    answer = agent.ask("q")
    assert answer.claims[0].citations == [10]


def test_search_k_is_clamped(fake):
    fake.script = [
        _reply(
            _tool_call("search", {"query": "a", "k": 500}, "t1"),
            _tool_call("search", {"query": "b", "k": 0}, "t2"),
            _tool_call("search", {"query": "c", "k": "7"}, "t3"),
        ),
        _reply(_final([10])),
    ]
    agent.ask("q")
    assert [s["k"] for s in fake.searches] == [agent.SEARCH_K, search.CANDIDATES, 1, agent.SEARCH_K]
    # Three tool calls, three results in one user turn.
    assert len(fake.calls[1]["messages"][-1]["content"]) == 3


def test_get_document_chunks_are_citable_and_truncated(fake, monkeypatch):
    big = "x" * (agent.DOCUMENT_CHARS - 10)
    chunks = [
        {"chunk_id": 70 + i, "document_id": 7, "title": "T", "source": "s", "text": text, "ord": i}
        for i, text in enumerate(["first", big, "the third passage"])  # 8,012 chars in all
    ]
    monkeypatch.setattr(search, "document_chunks", lambda doc_id, strategy: chunks)
    fake.script = [_reply(_tool_call("get_document", {"document_id": 7})), _reply(_final([71, 72]))]
    answer = agent.ask("q")
    assert answer.claims[0].citations == [71]  # 72 was cut off, so it was never shown
    text = fake.calls[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert "truncated: 1 more" in text
