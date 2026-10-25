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
GPT_OSS = "openai.gpt-oss-120b-1:0"  # fallback when Haiku keeps failing
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


def converse(
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = HAIKU,
    max_tokens: int = 2048,
    use_cache: bool = True,
) -> dict:
    """One Converse call: answer from llm_cache, or call `model` (falling back from Haiku).

    `messages` and `tools` are in Converse format (`{"role", "content": [blocks]}`,
    `[{"toolSpec": ...}]`). Returns
    {"message": {"role": "assistant", "content": [blocks]},  # text / toolUse blocks
     "stop_reason": "end_turn" | "tool_use" | "max_tokens" | ...,
     "usage": {"inputTokens", "outputTokens", "totalTokens", ...cache token counts if any},
     "model": the model that answered (GPT_OSS after a fallback),
     "cached": True if served from llm_cache (usage is then the original call's, cost 0)}.
    `message` can be appended to `messages` as is for the next turn, to either model:
    reasoningContent blocks (gpt-oss) are removed. It may have no blocks at all when
    stop_reason is "max_tokens"; do not send such a message back.
    Raises botocore ClientError for a bad request or when every retry and the fallback failed.
    """
    key = cache_key(model, system, messages, tools, max_tokens)
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return {**hit, "cached": True}

    try:
        response = _call_with_retries(_request(model, system, messages, tools, max_tokens))
        answered_by = model
    except (ClientError, BotoCoreError) as error:
        if model != HAIKU or not _retryable(error):
            raise
        print(f"llm fallback to {GPT_OSS}: {error}")
        response = _call_with_retries(_request(GPT_OSS, system, messages, tools, max_tokens))
        answered_by = GPT_OSS

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
    # A fallback answer is not cached: the key names Haiku, and a rerun should ask Haiku again.
    if use_cache and answered_by == model:
        _cache_put(key, model, result)
    return {**result, "cached": False}


def cache_key(
    model: str, system: str, messages: list[dict], tools: list[dict] | None, max_tokens: int
) -> str:
    """sha256 of everything that determines the answer, as canonical JSON (sorted keys)."""
    request = {
        "model": model,
        "system": system,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _request(
    model: str, system: str, messages: list[dict], tools: list[dict] | None, max_tokens: int
) -> dict:
    """Converse keyword arguments. Only Claude gets a cachePoint: other models reject it."""
    system_blocks: list[dict] = [{"text": system}]
    if model.startswith("eu.anthropic."):
        # Claude renders tools before the system prompt, so this one point covers both.
        system_blocks.append({"cachePoint": {"type": "default"}})
    request = {
        "modelId": model,
        "system": system_blocks,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": TEMPERATURE},
    }
    if tools:
        request["toolConfig"] = {"tools": tools}
    return request


def _call_with_retries(request: dict) -> dict:
    """Call Converse; on a retryable error wait and try again, then re-raise the last error."""
    for delay in (*_DELAYS, None):
        try:
            return _bedrock.converse(**request)
        except (ClientError, BotoCoreError) as error:
            if delay is None or not _retryable(error):
                raise
            print(f"llm retry in {delay} s: {request['modelId']}: {error}")
            # Jitter, so callers throttled together do not all come back at the same moment.
            time.sleep(delay + random.uniform(0, 1))
    raise AssertionError("unreachable: the last attempt returns or raises")


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
