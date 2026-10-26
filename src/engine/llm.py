"""LLM calls: Bedrock Converse with retry, fallback, prompt caching and a Postgres cache."""

import hashlib
import json
import random
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

from engine import config, db

HAIKU = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"  # the agent (ADR 0017)
# The same model through the global pool: its own quota, but requests may leave the EU.
HAIKU_GLOBAL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
GPT_OSS = "openai.gpt-oss-120b-1:0"  # last fallback when both Haiku pools keep failing
QWEN = "qwen.qwen3-235b-a22b-2507-v1:0"  # evaluation judge

TEMPERATURE = 0  # same request, same answer: the cache and the eval rely on it

# Errors that say "try again later", not "your request is wrong". ValidationException and
# AccessDeniedException are bugs or IAM problems: a retry would fail the same way.
_RETRYABLE_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
}
# Tried in order when a model fails with a retryable error. The eu.* pool gets no retries of its
# own: on 2026-10-26 it answered ServiceUnavailableException for every call while global.*
# worked, and three retries there would cost ~10 s of every call for nothing.
_FALLBACKS = {HAIKU: (HAIKU_GLOBAL, GPT_OSS)}

# Seconds to wait before retries 1, 2, 3 (plus up to 1 s of jitter each): at most 10 s of
# waiting per model. Haiku allows 10 requests/min, one every 6 s, so 7 s usually gets a slot;
# longer waits would not fit an agent run inside the api Lambda's 90 s.
_DELAYS = (1, 2, 4)

# Our loop does the retries (it needs to know when to fall back), so botocore makes one attempt.
# A 30 s read timeout keeps one stuck call from eating the whole 90 s Lambda.
_bedrock = boto3.client(
    "bedrock-runtime",
    region_name=config.REGION,
    config=Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1}),
)
# The longest one attempt can take (connect + read timeout). With a deadline, no retry and no
# fallback starts unless this much time is left, so a call never runs past it (ADR 0025).
ATTEMPT_SECONDS = 35


def converse(
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = HAIKU,
    max_tokens: int = 2048,
    use_cache: bool = True,
    tool_choice: dict | None = None,
    deadline: float | None = None,
    cache_history: bool = False,
) -> dict:
    """One Converse call: answer from llm_cache, or call `model` (Haiku falls back to the
    global pool, then to gpt-oss).

    `messages` and `tools` are in Converse format (`{"role", "content": [blocks]}`,
    `[{"toolSpec": ...}]`). `tool_choice` is Converse `toolChoice`, e.g.
    `{"tool": {"name": "final_answer"}}`; gpt-oss accepts it but ignores it (measured), so to
    force a tool offer only that tool. `deadline` is a `time.monotonic()` value: a retry or the
    fallback starts only if a whole attempt (`ATTEMPT_SECONDS`) still fits before it, so a call
    that starts with that much time left ends by the deadline. `cache_history` adds a Claude
    prompt-cache point after the last message, for a conversation that goes on (the agent loop);
    a one-off call would pay the cache-write premium for nothing. Returns
    {"message": {"role": "assistant", "content": [blocks]},  # text / toolUse blocks
     "stop_reason": "end_turn" | "tool_use" | "max_tokens" | ...,
     "usage": {"inputTokens", "outputTokens", "totalTokens", ...cache token counts if any},
     "model": the model that answered (HAIKU_GLOBAL or GPT_OSS after a fallback),
     "cached": True if served from llm_cache (usage is then the original call's, cost 0)}.
    `message` can be appended to `messages` as is for the next turn, to either model:
    reasoningContent blocks (gpt-oss) are removed. It may have no blocks at all when
    stop_reason is "max_tokens"; do not send such a message back.
    Raises botocore ClientError for a bad request or when every retry and the fallback failed
    (or the deadline left no time for them).
    """
    key = cache_key(model, system, messages, tools, max_tokens, tool_choice)
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return {**hit, "cached": True}

    def request(model_id: str) -> dict:
        return _request(model_id, system, messages, tools, max_tokens, tool_choice, cache_history)

    candidates = [model, *_FALLBACKS.get(model, ())]
    for index, candidate in enumerate(candidates):
        delays = () if candidate in _FALLBACKS else _DELAYS
        try:
            response = _call_with_retries(request(candidate), deadline, delays)
            answered_by = candidate
            break
        except (ClientError, BotoCoreError) as error:
            last = index == len(candidates) - 1
            if last or not _retryable(error) or not _time_left(deadline, wait=0):
                raise
            print(f"llm fallback to {candidates[index + 1]}: {error}")

    # gpt-oss returns its chain of thought as reasoningContent blocks without a signature;
    # Claude rejects such blocks in history, so they are dropped to keep turns portable.
    content = response["output"]["message"]["content"]
    content = [block for block in content if "reasoningContent" not in block]
    result = {
        "message": {"role": "assistant", "content": content},
        "stop_reason": response["stopReason"],
        "usage": response["usage"],
        "model": answered_by,
    }
    # The key names Haiku: a gpt-oss answer is not cached, so a rerun asks Haiku again. The global
    # pool runs the same model at temperature 0, so its answer is as good as one from eu.*.
    if use_cache and answered_by in (model, HAIKU_GLOBAL):
        _cache_put(key, model, result)
    return {**result, "cached": False}


def cache_key(
    model: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int,
    tool_choice: dict | None = None,
) -> str:
    """sha256 of everything that determines the answer, as canonical JSON (sorted keys).

    `tool_choice` enters the key only when set, so keys stored before it existed stay valid.
    """
    request = {
        "model": model,
        "system": system,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    if tool_choice is not None:
        request["tool_choice"] = tool_choice
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _request(
    model: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int,
    tool_choice: dict | None = None,
    cache_history: bool = False,
) -> dict:
    """Converse keyword arguments. Only Claude gets cachePoints: other models reject them."""
    system_blocks: list[dict] = [{"text": system}]
    is_claude = ".anthropic." in model  # eu.* or global.*
    if is_claude:
        # Claude renders tools before the system prompt, so this one point covers both.
        system_blocks.append({"cachePoint": {"type": "default"}})
    if is_claude and cache_history:
        # A second point after the last message: the next turn reads this prefix back. Below
        # Haiku 4.5's 4,096-token minimum it is ignored at no cost. Built on a copy, so the
        # caller's history and the cache key stay as they are.
        last = messages[-1]
        cached_last = {**last, "content": [*last["content"], {"cachePoint": {"type": "default"}}]}
        messages = [*messages[:-1], cached_last]
    request = {
        "modelId": model,
        "system": system_blocks,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": TEMPERATURE},
    }
    if tools:
        request["toolConfig"] = {"tools": tools}
        if tool_choice is not None:
            request["toolConfig"]["toolChoice"] = tool_choice
    return request


def _call_with_retries(
    request: dict, deadline: float | None = None, delays: tuple[int, ...] = _DELAYS
) -> dict:
    """Call Converse; on a retryable error wait `delays` and try again, then re-raise the last
    error. With a `deadline`, a retry happens only if a whole attempt still fits after the wait.
    """
    for delay in (*delays, None):
        try:
            return _bedrock.converse(**request)
        except (ClientError, BotoCoreError) as error:
            # + 1: the jitter below adds up to 1 s to the wait.
            if delay is None or not _retryable(error) or not _time_left(deadline, delay + 1):
                raise
            print(f"llm retry in {delay} s: {request['modelId']}: {error}")
            # Jitter, so callers throttled together do not all come back at the same moment.
            time.sleep(delay + random.uniform(0, 1))
    raise AssertionError("unreachable: the last attempt returns or raises")


def _time_left(deadline: float | None, wait: float) -> bool:
    """True if, after waiting `wait` seconds, a whole attempt still ends before `deadline`."""
    return deadline is None or time.monotonic() + wait + ATTEMPT_SECONDS <= deadline


def _retryable(error: Exception) -> bool:
    if isinstance(error, ClientError):
        return error.response["Error"]["Code"] in _RETRYABLE_CODES
    # Read timeouts and dropped connections (HTTPClientError), connect timeouts and DNS errors.
    return isinstance(error, HTTPClientError | BotoConnectionError)


# The cache only saves money and time: if Postgres fails, log one line and call the model
# anyway. ponytail: broad except on purpose, any cache failure must not fail the answer.
def _cache_get(key: str) -> dict | None:
    try:
        rows = db.run("SELECT response FROM llm_cache WHERE prompt_hash = :key", key=key)
    except Exception as error:
        print(f"llm cache read failed: {error}")
        return None
    return rows[0][0] if rows else None


def _cache_put(key: str, model: str, result: dict) -> None:
    # ON CONFLICT DO NOTHING: a concurrent writer or db.run's retry stores nothing twice.
    try:
        db.run(
            "INSERT INTO llm_cache (prompt_hash, model, response)"
            " VALUES (:key, :model, CAST(:response AS jsonb))"
            " ON CONFLICT (prompt_hash) DO NOTHING",
            key=key,
            model=model,
            response=json.dumps(result),
        )
    except Exception as error:
        print(f"llm cache write failed: {error}")
