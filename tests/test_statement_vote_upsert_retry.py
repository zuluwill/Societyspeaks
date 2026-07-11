"""
Regression contract tests for vote upsert behavior.

Two strategies, used deliberately:

  AST-level assertions  — used when the claim is structural ("key X is in dict Y
                          inside function Z").  These survive reformatting and
                          tolerate comments/docstrings that would fool a grep.

  Source-level grep     — used only when structural AST parsing adds no value
                          over a string search (e.g. checking a response literal
                          that is a single token unlikely to appear elsewhere).

No Flask import required; tests run in any minimal CI environment.
"""
import ast
from pathlib import Path

STATEMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "discussions" / "statements.py"
)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _tree() -> ast.Module:
    return ast.parse(STATEMENTS_PATH.read_text(encoding="utf-8"))


def _get_function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found in {STATEMENTS_PATH.name}")


def _dict_str_keys(d: ast.Dict) -> set:
    return {
        k.value
        for k in d.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _find_dict_assignment(func: ast.FunctionDef, var_name: str) -> ast.Dict:
    """Return the Dict node from the first `var_name = {...}` assignment in func."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == var_name for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise AssertionError(
        f"Dict assignment {var_name!r} not found in function {func.name!r}"
    )


def _calls_inside(root: ast.AST, callee: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(root)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == callee
    ]


# ---------------------------------------------------------------------------
# insert_values dict — AST assertions
# ---------------------------------------------------------------------------

def test_insert_values_contains_created_at():
    """
    created_at must be an explicit key in insert_values inside
    _upsert_statement_vote_row.  raw dialect insert() bypasses SQLAlchemy
    ORM column defaults, so omitting it produces NULL created_at rows.
    """
    func = _get_function("_upsert_statement_vote_row")
    keys = _dict_str_keys(_find_dict_assignment(func, "insert_values"))
    assert "created_at" in keys, (
        f"'created_at' missing from insert_values dict; found: {sorted(keys)}"
    )


def test_insert_values_contains_updated_at():
    func = _get_function("_upsert_statement_vote_row")
    keys = _dict_str_keys(_find_dict_assignment(func, "insert_values"))
    assert "updated_at" in keys


def test_set_values_does_not_overwrite_created_at():
    """
    created_at must NOT appear in set_values so that ON CONFLICT DO UPDATE
    preserves the original creation timestamp when a voter changes their vote.
    """
    func = _get_function("_upsert_statement_vote_row")
    keys = _dict_str_keys(_find_dict_assignment(func, "set_values"))
    assert "created_at" not in keys, (
        "'created_at' must not be in set_values — it would overwrite the "
        "original row timestamp on every vote-change UPDATE"
    )


# ---------------------------------------------------------------------------
# vote_statement retry structure — AST assertions
# ---------------------------------------------------------------------------

def test_vote_statement_calls_persist_upsert_at_least_twice():
    """vote_statement must call _persist_vote_with_upsert at least twice (initial + retry)."""
    func = _get_function("vote_statement")
    count = len(_calls_inside(func, "_persist_vote_with_upsert"))
    assert count >= 2, (
        f"Expected ≥2 calls to _persist_vote_with_upsert in vote_statement, found {count}"
    )


def test_retry_call_is_inside_integrity_error_handler():
    """
    The retry _persist_vote_with_upsert call must be structurally inside an
    except IntegrityError block, not just present somewhere in the function.
    """
    func = _get_function("vote_statement")

    integrity_handlers = [
        node for node in ast.walk(func)
        if isinstance(node, ast.ExceptHandler)
        and (
            (isinstance(node.type, ast.Name) and node.type.id == "IntegrityError")
            or (isinstance(node.type, ast.Attribute) and node.type.attr == "IntegrityError")
        )
    ]
    assert integrity_handlers, "No 'except IntegrityError' handler found in vote_statement"

    for handler in integrity_handlers:
        # Build a temporary module so ast.walk works on the handler body
        wrapper = ast.Module(body=handler.body, type_ignores=[])
        if _calls_inside(wrapper, "_persist_vote_with_upsert"):
            return  # found the retry inside the handler

    raise AssertionError(
        "No call to _persist_vote_with_upsert found inside an IntegrityError "
        "handler in vote_statement — retry must be structurally inside except block"
    )


# ---------------------------------------------------------------------------
# Counter delta helper — AST + source assertions
# ---------------------------------------------------------------------------

def test_apply_vote_counter_delta_uses_sql_not_python_arithmetic():
    """
    _apply_vote_counter_delta must issue a SQL UPDATE, not do Python
    read-modify-write on statement.vote_count_* attributes.
    """
    func = _get_function("_apply_vote_counter_delta")

    # Must contain a db.session.execute call
    execute_calls = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    assert execute_calls, "_apply_vote_counter_delta must call db.session.execute"

    # Must NOT directly assign to statement.vote_count_* attributes
    augassigns = [
        node for node in ast.walk(func)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Attribute)
        and "vote_count" in node.target.attr
    ]
    assert not augassigns, (
        "_apply_vote_counter_delta must not use += on vote_count_* "
        "(Python read-modify-write race); use SQL delta only"
    )


def test_apply_vote_counter_delta_uses_greatest_to_prevent_negatives():
    """GREATEST(0, ...) must guard against negative counter drift."""
    func = _get_function("_apply_vote_counter_delta")
    source = ast.get_source_segment(
        STATEMENTS_PATH.read_text(encoding="utf-8"), func
    ) or ""
    assert "GREATEST" in source, (
        "_apply_vote_counter_delta SQL must use GREATEST(0, ...) "
        "to prevent negative vote counts"
    )


# ---------------------------------------------------------------------------
# Conflict response contract — source grep (token is unique, grep is fine)
# ---------------------------------------------------------------------------

def test_vote_conflict_409_response_exists():
    """Stable API contract: double-conflict must return 409 with 'vote_conflict' key."""
    source = STATEMENTS_PATH.read_text(encoding="utf-8")
    assert "vote_conflict" in source
    assert "), 409" in source


# ---------------------------------------------------------------------------
# posthog_distinct_id stamping — AST assertions
# ---------------------------------------------------------------------------

def test_insert_values_contains_posthog_distinct_id():
    """Votes must stamp the PostHog identity at insert (mirrors game_run) so
    votes — mostly by intentionally-anonymous users — join to web sessions."""
    func = _get_function("_upsert_statement_vote_row")
    keys = _dict_str_keys(_find_dict_assignment(func, "insert_values"))
    assert "posthog_distinct_id" in keys, (
        f"'posthog_distinct_id' missing from insert_values dict; found: {sorted(keys)}"
    )


def test_set_values_never_unconditionally_writes_posthog_distinct_id():
    """A re-vote without a resolved identity must not wipe a stamped id:
    posthog_distinct_id may only enter set_values behind a truthiness guard,
    never in the initial dict literal."""
    func = _get_function("_upsert_statement_vote_row")
    keys = _dict_str_keys(_find_dict_assignment(func, "set_values"))
    assert "posthog_distinct_id" not in keys, (
        "posthog_distinct_id must not be in the unconditional set_values literal"
    )
    # And the guarded assignment must exist somewhere in the function.
    guarded = any(
        isinstance(node, ast.If)
        and any(
            isinstance(sub, ast.Assign)
            and any(
                isinstance(t, ast.Subscript)
                and isinstance(t.slice, ast.Constant)
                and t.slice.value == "posthog_distinct_id"
                for t in sub.targets
            )
            for sub in ast.walk(node)
        )
        for node in ast.walk(func)
    )
    assert guarded, "expected a guarded set_values['posthog_distinct_id'] assignment"


def test_persist_vote_resolves_identity_and_passes_it_through():
    """_persist_vote_with_upsert must resolve the request identity once and
    hand it to the row upsert."""
    func = _get_function("_persist_vote_with_upsert")
    src = ast.unparse(func)
    assert "resolve_request_distinct_id" in src
    assert "posthog_distinct_id=posthog_distinct_id" in src
