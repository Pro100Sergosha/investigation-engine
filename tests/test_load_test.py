import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from load_test import percentiles, summarize  # noqa: E402


def test_percentiles_in_milliseconds():
    seconds = [i / 1000 for i in range(1, 101)]  # 1..100 ms
    assert percentiles(seconds) == {"p50": 50, "p95": 95, "p99": 99}
    assert percentiles([0.2]) == {"p50": 200, "p95": 200, "p99": 200}
    assert percentiles([]) == {"p50": 0, "p95": 0, "p99": 0}


def test_summarize_counts_throttles_apart_from_errors_and_times_only_successes():
    results = [(200, 0.1, b""), (200, 0.3, b""), (429, 0.01, b""), (502, 90.0, b""), (0, 100, b"")]
    summary = summarize(results, wall=2.0)
    assert summary["ok"] == 2
    assert summary["throttled"] == 1
    assert summary["errors"] == 2  # the 502 and the connection failure
    assert summary["error_rate"] == 0.6
    assert summary["req_per_s"] == 2.5
    assert summary["p99"] <= 300  # the slow failures do not count as latency
