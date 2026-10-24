import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from comment_pr import LIMIT, MARKER, body  # noqa: E402


def test_body_starts_with_marker_and_shows_status():
    text = body("Resources\n[+] AWS::Lambda::Function", succeeded=False, build_url="u")
    assert text.startswith(MARKER)
    assert "FAILED" in text
    assert "[+] AWS::Lambda::Function" in text


def test_body_truncates_long_diff():
    text = body("x" * (LIMIT + 10), succeeded=True, build_url="u")
    assert "truncated" in text
    assert len(text) < 65_536
