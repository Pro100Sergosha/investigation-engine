import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from schema import handler, statements  # noqa: E402


def test_schema_splits_into_idempotent_statements():
    parts = statements((ROOT / "sql" / "schema.sql").read_text())
    assert parts[0] == "CREATE EXTENSION IF NOT EXISTS vector"
    assert len(parts) == 6
    for part in parts:
        assert ";" not in part and "--" not in part
        assert "IF NOT EXISTS" in part


def test_statements_drop_comment_lines():
    assert statements("-- a; b\nSELECT 1;\n\n  -- c\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_delete_keeps_the_data():
    # Delete makes no AWS call: without credentials it would fail if it tried.
    assert handler({"RequestType": "Delete"}, None) == {"PhysicalResourceId": "schema"}
