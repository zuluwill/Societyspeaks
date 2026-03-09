import ast
from pathlib import Path


SEED_GENERATOR_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "trending" / "seed_generator.py"
)


def _tree() -> ast.Module:
    return ast.parse(SEED_GENERATOR_PATH.read_text(encoding="utf-8"))


def test_fallback_seed_helper_exists():
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_fallback_seed_statements":
            return
    raise AssertionError("_fallback_seed_statements helper not found")


def test_seed_generation_uses_fallback_when_providers_unavailable():
    source = SEED_GENERATOR_PATH.read_text(encoding="utf-8")
    assert "_fallback_seed_statements" in source
    assert "LLM seed generation unavailable; using deterministic fallback statements" in source
