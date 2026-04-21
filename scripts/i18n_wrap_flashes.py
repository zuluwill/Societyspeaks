"""One-off transformer: wrap user-facing string literals in flash() / jsonify({'error'|'message': ...}) calls with gettext.

Usage:
    python3 scripts/i18n_wrap_flashes.py --dry-run app/auth/routes.py
    python3 scripts/i18n_wrap_flashes.py --apply app/auth/routes.py app/daily/routes.py ...

Rules:
- Wraps string literals only. Never wraps variables, `str(e)`, or already-wrapped `_(...)` calls.
- Converts f-strings to `_('literal with %(var)s', var=var)` form.
- Adds `from flask_babel import gettext as _` if missing (or extends existing import).
- Idempotent: rerunning is a no-op.
- Target calls:
    flash(LITERAL_OR_FSTRING, ...)
    jsonify({'error': LITERAL, 'message': LITERAL, ...})  [whitelist keys]
    abort(CODE, description=LITERAL)
"""
from __future__ import annotations
import argparse
import codecs
import re
import sys
from pathlib import Path

import libcst as cst
from libcst import matchers as m


JSONIFY_TRANSLATABLE_KEYS = {"message", "error_message", "detail", "description", "error"}
# Codes like 'csrf_failed' stay English (wrapped by `_looks_like_code()` filter).
JSONIFY_CODE_KEYS = {"code", "reason"}


def _valid_placeholder(name: str) -> bool:
    return re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) is not None


def _decode_text_part(raw: str) -> str:
    """Decode backslash escapes in an f-string text part to the real string value."""
    try:
        return raw.encode("latin-1", "backslashreplace").decode("unicode_escape")
    except Exception:
        return raw


def fstring_to_gettext(fstring: cst.FormattedString) -> cst.Call | None:
    """Convert an f-string to _('literal with %(var)s', var=var).

    Returns None if the f-string uses expressions too complex for simple extraction
    (e.g. method calls, arithmetic). In that case, caller should leave the f-string alone.
    """
    fmt_parts: list[str] = []
    kwargs: dict[str, cst.BaseExpression] = {}
    used_names: set[str] = set()

    for part in fstring.parts:
        if isinstance(part, cst.FormattedStringText):
            # decode escape sequences from raw source, then escape literal %
            decoded = _decode_text_part(part.value)
            fmt_parts.append(decoded.replace("%", "%%"))
        elif isinstance(part, cst.FormattedStringExpression):
            # Only allow simple names or attribute/name accesses as placeholders
            expr = part.expression
            if isinstance(expr, cst.Name) and _valid_placeholder(expr.value):
                key = expr.value
            elif isinstance(expr, cst.Attribute) and isinstance(expr.attr, cst.Name):
                # e.g. {user.email} → placeholder `email` (fall back to generic name if collision)
                key = expr.attr.value
            else:
                # too complex — bail out
                return None

            # Handle duplicate placeholders (use same key)
            if key in kwargs:
                existing = kwargs[key]
                # If existing kwarg points to a different expression, disambiguate
                if cst.Module(body=[]).code_for_node(existing) != cst.Module(body=[]).code_for_node(expr):
                    # make unique name
                    n = 2
                    while f"{key}{n}" in kwargs:
                        n += 1
                    key = f"{key}{n}"
                    kwargs[key] = expr
                    used_names.add(key)
            else:
                kwargs[key] = expr
                used_names.add(key)

            # Respect any format spec (rare — treat :d as %d style). Safest: ignore and always use %(key)s.
            # A conversion like !r would also be lost. Skip those for safety.
            if part.conversion or part.format_spec:
                return None

            fmt_parts.append(f"%({key})s")

    literal = "".join(fmt_parts)
    # Build: _('literal', name=name, ...)  — use repr() so escapes are correct
    literal_src = _py_string_literal(literal)
    args = [cst.Arg(cst.SimpleString(literal_src))]
    for k, v in kwargs.items():
        args.append(cst.Arg(value=v, keyword=cst.Name(k), equal=cst.AssignEqual(whitespace_before=cst.SimpleWhitespace(""), whitespace_after=cst.SimpleWhitespace(""))))
    return cst.Call(func=cst.Name("_"), args=args)


def _py_string_literal(s: str) -> str:
    """Return a Python source string literal for s, preferring single quotes."""
    # repr prefers single quotes unless the string contains a single quote and no double quote
    r = repr(s)
    # repr produces 'abc' or "abc" — both are valid Python SimpleString source.
    return r


def string_literal_to_gettext(node: cst.BaseString) -> cst.Call | None:
    """Wrap a simple string literal in _(...). Skips f-strings (handled separately) and concat."""
    if isinstance(node, cst.SimpleString):
        val = node.evaluated_value
        # Skip empty strings
        if not val.strip():
            return None
        # Skip strings that look like machine identifiers (no spaces, no letters, all lowercase_snake)
        if _looks_like_code(val):
            return None
        return cst.Call(func=cst.Name("_"), args=[cst.Arg(node)])
    if isinstance(node, cst.ConcatenatedString):
        # "abc" "def" literal — rare; leave alone
        return None
    return None


_CODE_RX = re.compile(r"^[a-z][a-z0-9_]*$")


def _looks_like_code(s: str) -> bool:
    """Heuristic: looks like a programmatic identifier, not a sentence."""
    return bool(_CODE_RX.match(s))


class FlashJsonifyTransformer(cst.CSTTransformer):
    def __init__(self, wrap_dicts: bool = False):
        self.changed = False
        self.wrap_dicts = wrap_dicts

    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.BaseExpression:
        # flash(msg, category)
        if m.matches(updated.func, m.Name("flash")):
            return self._wrap_flash(updated)
        # jsonify({...})
        if m.matches(updated.func, m.Name("jsonify")):
            return self._wrap_jsonify(updated)
        # abort(code, description=...)
        if m.matches(updated.func, m.Name("abort")):
            return self._wrap_abort(updated)
        return updated

    def leave_Dict(self, original: cst.Dict, updated: cst.Dict) -> cst.Dict:
        if not self.wrap_dicts:
            return updated
        new_elements = []
        changed = False
        for element in updated.elements:
            if isinstance(element, cst.DictElement) and isinstance(element.key, cst.SimpleString):
                key_val = element.key.evaluated_value
                if key_val in JSONIFY_TRANSLATABLE_KEYS:
                    if not self._already_wrapped(element.value):
                        wrapped = string_literal_to_gettext(element.value)
                        if wrapped is None and isinstance(element.value, cst.FormattedString):
                            wrapped = fstring_to_gettext(element.value)
                        if wrapped is not None:
                            element = element.with_changes(value=wrapped)
                            changed = True
            new_elements.append(element)
        if changed:
            self.changed = True
            return updated.with_changes(elements=new_elements)
        return updated

    def _already_wrapped(self, expr: cst.BaseExpression) -> bool:
        return isinstance(expr, cst.Call) and m.matches(expr.func, m.OneOf(m.Name("_"), m.Name("_l"), m.Name("gettext"), m.Name("lazy_gettext"), m.Name("ngettext")))

    def _wrap_first_arg(self, call: cst.Call) -> cst.Call:
        if not call.args:
            return call
        first = call.args[0]
        expr = first.value

        if self._already_wrapped(expr):
            return call

        # Simple literal
        wrapped = string_literal_to_gettext(expr)
        if wrapped is None and isinstance(expr, cst.FormattedString):
            wrapped = fstring_to_gettext(expr)

        if wrapped is None:
            return call

        self.changed = True
        new_args = list(call.args)
        new_args[0] = first.with_changes(value=wrapped)
        return call.with_changes(args=new_args)

    def _wrap_flash(self, call: cst.Call) -> cst.Call:
        return self._wrap_first_arg(call)

    def _wrap_abort(self, call: cst.Call) -> cst.Call:
        # abort(code, description=msg) — wrap description kwarg
        new_args = []
        changed = False
        for arg in call.args:
            if arg.keyword and m.matches(arg.keyword, m.Name("description")):
                if not self._already_wrapped(arg.value):
                    wrapped = string_literal_to_gettext(arg.value)
                    if wrapped is None and isinstance(arg.value, cst.FormattedString):
                        wrapped = fstring_to_gettext(arg.value)
                    if wrapped is not None:
                        arg = arg.with_changes(value=wrapped)
                        changed = True
            new_args.append(arg)
        if changed:
            self.changed = True
            return call.with_changes(args=new_args)
        return call

    def _wrap_jsonify(self, call: cst.Call) -> cst.Call:
        if len(call.args) != 1:
            return call
        arg0 = call.args[0].value
        if not isinstance(arg0, cst.Dict):
            return call
        new_elements = []
        changed = False
        for element in arg0.elements:
            if isinstance(element, cst.DictElement) and isinstance(element.key, cst.SimpleString):
                key_val = element.key.evaluated_value
                if key_val in JSONIFY_TRANSLATABLE_KEYS:
                    if not self._already_wrapped(element.value):
                        wrapped = string_literal_to_gettext(element.value)
                        if wrapped is None and isinstance(element.value, cst.FormattedString):
                            wrapped = fstring_to_gettext(element.value)
                        if wrapped is not None:
                            element = element.with_changes(value=wrapped)
                            changed = True
            new_elements.append(element)
        if changed:
            self.changed = True
            new_dict = arg0.with_changes(elements=new_elements)
            new_args = [call.args[0].with_changes(value=new_dict)]
            return call.with_changes(args=new_args)
        return call


def ensure_gettext_import(tree: cst.Module) -> tuple[cst.Module, bool]:
    """Ensure `from flask_babel import gettext as _` (or similar) is present.

    If `from flask_babel import ...` already exists, extend it. Else add a new import
    after the last existing `from flask_babel` / `from flask ...` / other imports.
    """
    # Check if _ is already imported from flask_babel
    class ImportChecker(cst.CSTVisitor):
        def __init__(self):
            self.has_gettext_alias = False
            self.flask_babel_import: cst.ImportFrom | None = None

        def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
            if node.module and isinstance(node.module, cst.Name) and node.module.value == "flask_babel":
                self.flask_babel_import = node
                if isinstance(node.names, (list, tuple)) or hasattr(node.names, "__iter__"):
                    for alias in node.names:
                        if isinstance(alias, cst.ImportAlias):
                            as_name = alias.asname.name if alias.asname else alias.name
                            if isinstance(as_name, cst.Name) and as_name.value == "_":
                                self.has_gettext_alias = True

    checker = ImportChecker()
    tree.visit(checker)
    if checker.has_gettext_alias:
        return tree, False

    new_alias = cst.ImportAlias(
        name=cst.Name("gettext"),
        asname=cst.AsName(name=cst.Name("_")),
    )

    class ImportAdder(cst.CSTTransformer):
        def __init__(self):
            self.done = False

        def leave_ImportFrom(self, original: cst.ImportFrom, updated: cst.ImportFrom) -> cst.ImportFrom:
            if self.done:
                return updated
            if updated.module and isinstance(updated.module, cst.Name) and updated.module.value == "flask_babel":
                self.done = True
                existing = list(updated.names) if not isinstance(updated.names, cst.ImportStar) else []
                # Only add if not already present
                for alias in existing:
                    as_name = alias.asname.name if alias.asname else alias.name
                    if isinstance(as_name, cst.Name) and as_name.value == "_":
                        return updated
                existing.append(new_alias)
                return updated.with_changes(names=existing)
            return updated

    adder = ImportAdder()
    new_tree = tree.visit(adder)
    if adder.done:
        return new_tree, True

    # No existing flask_babel import — add one after the last top-level import
    body = list(new_tree.body)
    last_import_idx = -1
    for i, stmt in enumerate(body):
        if isinstance(stmt, cst.SimpleStatementLine):
            for small in stmt.body:
                if isinstance(small, (cst.Import, cst.ImportFrom)):
                    last_import_idx = i
                    break
    new_import = cst.SimpleStatementLine(
        body=[cst.ImportFrom(module=cst.Name("flask_babel"), names=[new_alias])]
    )
    body.insert(last_import_idx + 1, new_import)
    return new_tree.with_changes(body=body), True


def process(path: Path, apply: bool, wrap_dicts: bool = False) -> bool:
    source = path.read_text()
    tree = cst.parse_module(source)
    transformer = FlashJsonifyTransformer(wrap_dicts=wrap_dicts)
    new_tree = tree.visit(transformer)
    if transformer.changed:
        new_tree, _ = ensure_gettext_import(new_tree)
    new_source = new_tree.code
    if new_source == source:
        return False
    if apply:
        path.write_text(new_source)
        print(f"[applied] {path}")
    else:
        # print unified diff preview (first 40 lines)
        import difflib
        diff = list(difflib.unified_diff(source.splitlines(keepends=True), new_source.splitlines(keepends=True), fromfile=str(path), tofile=str(path), n=1))
        sys.stdout.write("".join(diff[:80]))
        print(f"\n[dry-run] would modify {path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+", type=Path)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    p.add_argument("--wrap-dicts", action="store_true", help="Also wrap message/error_message string values in any dict literal (not just inside jsonify).")
    args = p.parse_args()
    any_changed = False
    for path in args.paths:
        if process(path, apply=args.apply, wrap_dicts=args.wrap_dicts):
            any_changed = True
    return 0 if (any_changed or not args.dry_run) else 0


if __name__ == "__main__":
    sys.exit(main())
