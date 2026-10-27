"""Load test of the public Function URL: latency percentiles, errors and throttles per route.

Standard library only (urllib + a thread pool), so it runs anywhere; the `load-test` job runs it
in CodeBuild, in the same Region as the Lambda. Only cheap routes are loaded: GET /health (the
Lambda alone), GET /documents (a page + count(*) over the corpus) and GET /documents/{id} (one
row with its text). POST /ask spends Bedrock credits and is never loaded: at most 3 sequential
calls, for a latency sample. There is no search route; search time from the Lambda is read off
`/ask` (llm-wiki/07, Performance).
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TIMEOUT = 100  # seconds: above the api Lambda's 90 s, so a Lambda timeout shows as its 502
# The second question is asked twice: the rerun's LLM steps come from llm_cache, so its
# server time is almost only searches and database reads (no new Haiku spend either).
QUESTIONS = [
    "Which change caused the card payment outage of March 12, 2026, and when was it rolled back?",
    "Which former Charlotte Hornets player later coached the WNBA team Charlotte Sting?",
]
MAX_ASK = 3  # ~$0.016 per uncached question (EVALUATION.md); a hard cap, not a default


def request(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, float, bytes]:
    """(status, seconds, body) of one request. 0 = no HTTP answer (timeout, connection error)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:  # 4xx/5xx still carry a status and a body
        status, payload = error.code, error.read()
    except (urllib.error.URLError, TimeoutError):
        status, payload = 0, b""
    return status, time.perf_counter() - start, payload


def percentiles(seconds: list[float]) -> dict[str, float]:
    """p50/p95/p99 in milliseconds (statistics.quantiles, inclusive: exact for small samples)."""
    if len(seconds) < 2:
        value = round(seconds[0] * 1000) if seconds else 0
        return {"p50": value, "p95": value, "p99": value}
    cuts = statistics.quantiles(seconds, n=100, method="inclusive")
    return {f"p{p}": round(cuts[p - 1] * 1000) for p in (50, 95, 99)}


def summarize(results: list[tuple[int, float, bytes]], wall: float) -> dict:
    """Counts and latency of one batch. 429 = throttled (reserved concurrency used up)."""
    ok = [seconds for status, seconds, _ in results if 200 <= status < 300]
    throttled = sum(status == 429 for status, _, _ in results)
    errors = len(results) - len(ok) - throttled
    return {
        "n": len(results),
        "ok": len(ok),
        "throttled": throttled,
        "errors": errors,
        "error_rate": round((errors + throttled) / len(results), 3) if results else 0.0,
        "req_per_s": round(len(results) / wall, 1) if wall else 0.0,
        **percentiles(ok),
    }


def load(targets: list[tuple[str, str]], total: int, concurrency: int) -> dict[str, dict]:
    """`total` GETs round-robin over (route, url) `targets`, `concurrency` at a time.

    Summary of all requests and per route; a route's req/s is its share of the throughput.
    """
    picked = [targets[i % len(targets)] for i in range(total)]
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(request, [url for _, url in picked]))
    wall = time.perf_counter() - start
    by_route: dict[str, list] = {}
    for (route, _), result in zip(picked, results, strict=True):
        by_route.setdefault(route, []).append(result)
    return {"all": summarize(results, wall)} | {
        route: summarize(rs, wall) for route, rs in by_route.items()
    }


def ask(base: str, question: str) -> dict:
    """One POST /ask: client seconds, server ms, and the server ms outside LLM calls."""
    status, seconds, payload = request(base + "ask", "POST", {"question": question})
    record = {"question": question[:60], "status": status, "client_ms": round(seconds * 1000)}
    if status == 200:
        trace = json.loads(payload)["trace"]
        llm = [entry for entry in trace if entry["step"] == "llm"]
        llm_ms = sum(entry["ms"] for entry in llm)
        record |= {
            "answer_status": json.loads(payload)["status"],
            "llm_calls": len(llm),
            "llm_cached": sum(entry["cached"] for entry in llm),
            "llm_ms": llm_ms,
            # Searches (query embedding + SQL + MMR), get_document reads and the cited chunks.
            "rest_ms": record["client_ms"] - llm_ms,
            "searches": sum(entry["step"] == "search" for entry in trace),
        }
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="Function URL, ending in /")
    parser.add_argument("--requests", type=int, default=200, help="requests per concurrency level")
    parser.add_argument("--concurrency", default="1,5,10", help="comma-separated levels")
    parser.add_argument(
        "--ask", type=int, default=0, help=f"sequential POST /ask calls, <= {MAX_ASK}"
    )
    args = parser.parse_args()
    if not 0 <= args.ask <= MAX_ASK:
        parser.error(f"--ask must be 0-{MAX_ASK}: /ask spends Bedrock credits")
    base = args.url if args.url.endswith("/") else args.url + "/"

    def show(name: str, value: dict) -> None:
        print(json.dumps({"phase": name, **value}), flush=True)

    # First requests: a cold Lambda if none was warm, a resuming Aurora if it was paused.
    for path in ("health", "documents?limit=1"):
        status, seconds, _ = request(base + path)
        show("first", {"path": path, "status": status, "ms": round(seconds * 1000)})

    status, _, payload = request(base + "documents?limit=10")
    ids = [doc["id"] for doc in json.loads(payload)["documents"]] if status == 200 else []
    # One target per route, then the stored documents: /documents/{id} reads different rows.
    targets = [("GET /health", base + "health"), ("GET /documents", base + "documents?limit=10")]
    targets += [("GET /documents/{id}", base + f"documents/{i}") for i in ids]
    for level in (int(c) for c in args.concurrency.split(",")):
        for route, summary in load(targets, args.requests, level).items():
            show(f"c={level}", {"route": route, **summary})

    # No Aurora resume phase: warm api instances keep their database connection open, so the
    # cluster does not pause while they live (measured 10-26). Resumes are read from the api
    # log instead (dashboard "Slow requests outside /ask").
    questions = [QUESTIONS[0], QUESTIONS[1], QUESTIONS[1]][: args.ask]
    for question in questions:
        show("ask", ask(base, question))


if __name__ == "__main__":
    main()
