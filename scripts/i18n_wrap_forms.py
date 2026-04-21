"""One-off transformer: wrap WTForms field labels + validator messages + choice labels
with lazy_gettext (aliased as _l) since forms are evaluated at import time.

Target patterns:
    StringField('Label', ...)                   → StringField(_l('Label'), ...)
    Length(min=5, message='msg')                 → Length(min=5, message=_l('msg'))
    choices=[('val', 'Label'), ...]              → choices=[('val', _l('Label')), ...]
    description='Markdown only...'               → description=_l('...')

Skips:
    - non-field calls
    - already-wrapped strings
    - machine-identifier-looking strings (snake_case, no spaces)
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import libcst as cst
from libcst import matchers as m


WTFORMS_FIELD_CLASSES = {
    "StringField", "TextAreaField", "IntegerField", "DecimalField", "BooleanField",
    "SelectField", "SelectMultipleField", "RadioField", "PasswordField", "HiddenField",
    "FileField", "MultipleFileField", "SubmitField", "DateField", "DateTimeField",
    "TimeField", "FloatField", "EmailField", "TelField", "URLField", "FieldList",
    "FormField",
}

VALIDATOR_CLASSES = {
    "DataRequired", "InputRequired", "Length", "EqualTo", "Email", "NumberRange",
    "URL", "UUID", "AnyOf", "NoneOf", "Regexp", "IPAddress", "MacAddress",
    "Optional", "ValidationError",
}

# kwargs on validators that hold user-facing strings
TRANSLATABLE_KWARGS = {"message", "description"}


_CODE_RX = re.compile(r"^[a-z][a-z0-9_]*$")


def _looks_like_code(s: str) -> bool:
    return bool(_CODE_RX.match(s))


def _already_wrapped(expr: cst.BaseExpression) -> bool:
    return isinstance(expr, cst.Call) and m.matches(
        expr.func,
        m.OneOf(m.Name("_"), m.Name("_l"), m.Name("gettext"), m.Name("lazy_gettext"), m.Name("ngettext")),
    )


def _wrap_lazy(expr: cst.BaseExpression) -> cst.Call | None:
    if _already_wrapped(expr):
        return None
    if isinstance(expr, cst.SimpleString):
        val = expr.evaluated_value
        if not val.strip() or _looks_like_code(val):
            return None
        return cst.Call(func=cst.Name("_l"), args=[cst.Arg(expr)])
    return None


class FormsTransformer(cst.CSTTransformer):
    def __init__(self):
        self.changed = False

    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.BaseExpression:
        func = updated.func
        func_name = None
        if isinstance(func, cst.Name):
            func_name = func.value
        elif isinstance(func, cst.Attribute) and isinstance(func.attr, cst.Name):
            func_name = func.attr.value

        if func_name in WTFORMS_FIELD_CLASSES:
            return self._wrap_field(updated)
        if func_name in VALIDATOR_CLASSES:
            return self._wrap_validator(updated)
        return updated

    def _wrap_field(self, call: cst.Call) -> cst.Call:
        new_args = []
        changed = False
        for i, arg in enumerate(call.args):
            # First positional = label
            if i == 0 and arg.keyword is None:
                wrapped = _wrap_lazy(arg.value)
                if wrapped is not None:
                    arg = arg.with_changes(value=wrapped)
                    changed = True
            # description kwarg
            elif arg.keyword and isinstance(arg.keyword, cst.Name) and arg.keyword.value == "description":
                wrapped = _wrap_lazy(arg.value)
                if wrapped is not None:
                    arg = arg.with_changes(value=wrapped)
                    changed = True
            # label kwarg (sometimes used instead of positional)
            elif arg.keyword and isinstance(arg.keyword, cst.Name) and arg.keyword.value == "label":
                wrapped = _wrap_lazy(arg.value)
                if wrapped is not None:
                    arg = arg.with_changes(value=wrapped)
                    changed = True
            # choices kwarg: list of tuples (val, label)
            elif arg.keyword and isinstance(arg.keyword, cst.Name) and arg.keyword.value == "choices":
                new_choices = self._wrap_choices(arg.value)
                if new_choices is not None:
                    arg = arg.with_changes(value=new_choices)
                    changed = True
            new_args.append(arg)
        if changed:
            self.changed = True
            return call.with_changes(args=new_args)
        return call

    def _wrap_validator(self, call: cst.Call) -> cst.Call:
        new_args = []
        changed = False
        for arg in call.args:
            if arg.keyword and isinstance(arg.keyword, cst.Name) and arg.keyword.value in TRANSLATABLE_KWARGS:
                wrapped = _wrap_lazy(arg.value)
                if wrapped is not None:
                    arg = arg.with_changes(value=wrapped)
                    changed = True
            new_args.append(arg)
        if changed:
            self.changed = True
            return call.with_changes(args=new_args)
        return call

    def _wrap_choices(self, node: cst.BaseExpression) -> cst.BaseExpression | None:
        # choices=[('val', 'Label'), ...] — we only handle literal list/tuple of 2-tuples
        if not isinstance(node, (cst.List, cst.Tuple)):
            return None
        changed = False
        new_elements = []
        for element in node.elements:
            if not isinstance(element, (cst.Element,)):
                new_elements.append(element)
                continue
            inner = element.value
            if isinstance(inner, cst.Tuple) and len(inner.elements) == 2:
                val_el = inner.elements[0]
                label_el = inner.elements[1]
                if isinstance(label_el.value, cst.SimpleString):
                    wrapped = _wrap_lazy(label_el.value)
                    if wrapped is not None:
                        new_label = label_el.with_changes(value=wrapped)
                        new_inner = inner.with_changes(elements=[val_el, new_label])
                        element = element.with_changes(value=new_inner)
                        changed = True
            new_elements.append(element)
        if changed:
            return node.with_changes(elements=new_elements)
        return None


def ensure_lazy_gettext_import(tree: cst.Module) -> cst.Module:
    class ImportChecker(cst.CSTVisitor):
        def __init__(self):
            self.has_l_alias = False
            self.flask_babel_import = False

        def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
            if node.module and isinstance(node.module, cst.Name) and node.module.value == "flask_babel":
                self.flask_babel_import = True
                if hasattr(node.names, "__iter__"):
                    for alias in node.names:
                        if isinstance(alias, cst.ImportAlias):
                            as_name = alias.asname.name if alias.asname else alias.name
                            if isinstance(as_name, cst.Name) and as_name.value == "_l":
                                self.has_l_alias = True

    checker = ImportChecker()
    tree.visit(checker)
    if checker.has_l_alias:
        return tree

    new_alias = cst.ImportAlias(
        name=cst.Name("lazy_gettext"),
        asname=cst.AsName(name=cst.Name("_l")),
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
                for alias in existing:
                    as_name = alias.asname.name if alias.asname else alias.name
                    if isinstance(as_name, cst.Name) and as_name.value == "_l":
                        return updated
                existing.append(new_alias)
                return updated.with_changes(names=existing)
            return updated

    adder = ImportAdder()
    new_tree = tree.visit(adder)
    if adder.done:
        return new_tree

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
    return new_tree.with_changes(body=body)


def process(path: Path, apply: bool) -> bool:
    source = path.read_text()
    tree = cst.parse_module(source)
    transformer = FormsTransformer()
    new_tree = tree.visit(transformer)
    if transformer.changed:
        new_tree = ensure_lazy_gettext_import(new_tree)
    new_source = new_tree.code
    if new_source == source:
        return False
    if apply:
        path.write_text(new_source)
        print(f"[applied] {path}")
    else:
        import difflib
        diff = list(difflib.unified_diff(source.splitlines(keepends=True), new_source.splitlines(keepends=True), fromfile=str(path), tofile=str(path), n=1))
        sys.stdout.write("".join(diff[:120]))
        print(f"\n[dry-run] would modify {path}")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+", type=Path)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    for path in args.paths:
        process(path, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
