import hashlib
import json

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from engine import llm

SYSTEM = "You answer with tools."
MESSAGES = [{"role": "user", "content": [{"text": "Who founded Acme?"}]}]
TOOLS = [{"toolSpec": {"name": "search", "inputSchema": {"json": {"type": "object"}}}}]


def _error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Converse")


def _response(text: str = "ok") -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
    }


class FakeBedrock:
    """Plays back a script: an exception is raised, a dict is returned. Records requests."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []

    def converse(self, **request):
        self.requests.append(request)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def fake(monkeypatch):
    """Install a fake client with an empty script, no sleeping, and no database."""
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    client = FakeBedrock()
    monkeypatch.setattr(llm, "_bedrock", client)
    return client


def _ask(**kwargs) -> dict:
    return llm.converse(SYSTEM, MESSAGES, use_cache=False, **kwargs)


def test_retry_then_success(fake):
    fake.script = [_error("ThrottlingException"), ReadTimeoutError(endpoint_url="x"), _response()]
    result = _ask(model=llm.HAIKU_GLOBAL)
    assert len(fake.requests) == 3
    assert result["model"] == llm.HAIKU_GLOBAL
    assert result["message"] == {"role": "assistant", "content": [{"text": "ok"}]}
    assert result["usage"]["inputTokens"] == 10
    assert result["cached"] is False


def test_eu_failure_goes_straight_to_the_global_pool(fake):
    fake.script = [_error("ServiceUnavailableException"), _response("from global")]
    result = _ask(tools=TOOLS)
    assert [r["modelId"] for r in fake.requests] == [llm.HAIKU, llm.HAIKU_GLOBAL]
    assert result["model"] == llm.HAIKU_GLOBAL
    # Still Claude: the prompt-cache point stays.
    assert fake.requests[-1]["system"][-1] == {"cachePoint": {"type": "default"}}


def test_fallback_to_gpt_oss_after_global_retries(fake):
    fake.script = [_error("ServiceUnavailableException")] * 5 + [_response("from gpt-oss")]
    result = _ask(tools=TOOLS)
    assert [r["modelId"] for r in fake.requests] == (
        [llm.HAIKU] + [llm.HAIKU_GLOBAL] * 4 + [llm.GPT_OSS]
    )
    assert result["model"] == llm.GPT_OSS
    # Same request apart from the model and the Claude-only cachePoint.
    assert fake.requests[-1]["messages"] == MESSAGES
    assert fake.requests[-1]["toolConfig"] == {"tools": TOOLS}


def test_no_fallback_for_the_judge(fake):
    fake.script = [_error("ThrottlingException")] * 4
    with pytest.raises(ClientError):
        _ask(model=llm.QWEN)
    assert {r["modelId"] for r in fake.requests} == {llm.QWEN}


def test_validation_error_is_not_retried(fake):
    fake.script = [_error("ValidationException")]
    with pytest.raises(ClientError):
        _ask()
    assert len(fake.requests) == 1


def test_cache_point_for_claude_only(fake):
    fake.script = [_response(), _response()]
    _ask(tools=TOOLS)
    _ask(tools=TOOLS, model=llm.GPT_OSS)
    claude, gpt_oss = fake.requests
    assert claude["system"] == [{"text": SYSTEM}, {"cachePoint": {"type": "default"}}]
    assert gpt_oss["system"] == [{"text": SYSTEM}]
    assert "cachePoint" not in str(gpt_oss)


def test_reasoning_blocks_are_dropped(fake):
    response = _response()
    response["output"]["message"]["content"].insert(
        0, {"reasoningContent": {"reasoningText": {"text": "thinking..."}}}
    )
    fake.script = [response]
    assert _ask(model=llm.GPT_OSS)["message"]["content"] == [{"text": "ok"}]


def test_cache_key_ignores_dict_order_and_sees_every_parameter():
    base = dict(model=llm.HAIKU, system=SYSTEM, messages=MESSAGES, tools=TOOLS, max_tokens=100)
    reordered = [{"content": [{"text": "Who founded Acme?"}], "role": "user"}]
    assert llm.cache_key(**base) == llm.cache_key(**{**base, "messages": reordered})
    changes = {
        "model": llm.GPT_OSS,
        "system": SYSTEM + " ",
        "messages": [{"role": "user", "content": [{"text": "Who founded Acme"}]}],
        "tools": None,
        "max_tokens": 101,
    }
    for name, value in changes.items():
        assert llm.cache_key(**base) != llm.cache_key(**{**base, name: value}), name


def test_tool_choice_changes_the_cache_key_and_none_keeps_the_old_key():
    base = dict(model=llm.HAIKU, system=SYSTEM, messages=MESSAGES, tools=TOOLS, max_tokens=100)
    # The key as computed before tool_choice existed: rows already in llm_cache stay valid.
    before = {**base, "temperature": llm.TEMPERATURE}
    canonical = json.dumps(before, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert llm.cache_key(**base) == hashlib.sha256(canonical.encode()).hexdigest()
    forced = llm.cache_key(**base, tool_choice={"tool": {"name": "search"}})
    assert forced != llm.cache_key(**base)


def test_tool_choice_goes_into_tool_config(fake):
    fake.script = [_response()]
    _ask(tools=TOOLS, tool_choice={"tool": {"name": "search"}})
    assert fake.requests[0]["toolConfig"] == {
        "tools": TOOLS,
        "toolChoice": {"tool": {"name": "search"}},
    }


def test_history_cache_point_for_claude_only_on_a_copy(fake):
    fake.script = [_response(), _response()]
    _ask(cache_history=True)
    _ask(cache_history=True, model=llm.GPT_OSS)
    claude, gpt_oss = fake.requests
    assert claude["messages"][-1]["content"][-1] == {"cachePoint": {"type": "default"}}
    assert gpt_oss["messages"] == MESSAGES
    assert MESSAGES[0]["content"] == [{"text": "Who founded Acme?"}]  # the caller's list


def test_deadline_stops_retries_and_fallback(fake, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    fake.script = [_error("ThrottlingException")]
    # The first attempt is the caller's decision; after it no whole attempt fits any more, so
    # neither a retry nor the fallback starts.
    with pytest.raises(ClientError):
        _ask(deadline=llm.ATTEMPT_SECONDS - 1)
    assert len(fake.requests) == 1

    fake.script = [_error("ThrottlingException")] * 5 + [_response()]
    assert _ask(deadline=1000)["model"] == llm.GPT_OSS  # plenty of time: retries + fallbacks


def test_cache_hit_skips_the_model_and_only_gpt_oss_is_not_cached(fake, monkeypatch):
    stored: dict = {}

    def run(sql, **params):
        if sql.startswith("SELECT"):
            return [[stored[params["key"]]]] if params["key"] in stored else []
        stored[params["key"]] = json.loads(params["response"])
        return []

    monkeypatch.setattr(llm.db, "run", run)
    fake.script = [_response()]
    first = llm.converse(SYSTEM, MESSAGES)
    second = llm.converse(SYSTEM, MESSAGES)
    assert len(fake.requests) == 1
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["message"] == first["message"]

    fake.script = [_error("ThrottlingException")] * 5 + [_response()]
    llm.converse(SYSTEM, [{"role": "user", "content": [{"text": "other"}]}])
    assert len(stored) == 1  # gpt-oss answered: not stored under the Haiku key

    fake.script = [_error("ThrottlingException"), _response()]
    llm.converse(SYSTEM, [{"role": "user", "content": [{"text": "third"}]}])
    assert len(stored) == 2  # the global pool is the same model: stored


def test_database_down_still_answers(fake, monkeypatch):
    def run(sql, **params):
        raise OSError("connection refused")

    monkeypatch.setattr(llm.db, "run", run)
    fake.script = [_response()]
    assert llm.converse(SYSTEM, MESSAGES)["cached"] is False
