import ast
from pathlib import Path


STATEMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "discussions" / "statements.py"
)


def _tree() -> ast.Module:
    return ast.parse(STATEMENTS_PATH.read_text(encoding="utf-8"))


def _get_function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found in {STATEMENTS_PATH.name}")


def test_vote_statement_reads_idempotency_header():
    source = STATEMENTS_PATH.read_text(encoding="utf-8")
    assert "Idempotency-Key" in source
    assert "vote-idempotency:" in source


def test_vote_statement_hashes_payload_for_idempotency():
    func = _get_function("_vote_request_hash")
    source = ast.get_source_segment(STATEMENTS_PATH.read_text(encoding="utf-8"), func) or ""
    assert "hashlib.sha256" in source
    assert "sort_keys=True" in source
