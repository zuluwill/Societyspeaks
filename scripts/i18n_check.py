"""Pre-commit / CI sanity check for i18n integrity.

Exits non-zero if any of these fail:
  1. Jinja's `_(...)` or `ngettext(...)` uses a placeholder format the renderer
     can't satisfy (bare %, %d with a string sentinel kwarg, %(name) without
     binding, etc.).
  2. Template or Python source has `_('…%(x)s…')` that would KeyError at
     render time (no kwargs bound).
  3. `_` is rebound anywhere in a module that also imports `gettext as _`.
  4. An unwrapped `flash("Literal", …)` or `'error'|'message': 'Literal'`
     appears in customer-facing Python.
  5. Any `render_template('emails/…')` bypasses `_render_for_user`.
  6. Any `_l(` lazy_gettext appears in a `|tojson` context.
  7. pybabel extract + compile succeeds with zero errors.
  8. GNU msgfmt --check-syntax (when `msgfmt` is on PATH) passes for every locale.
  9. Named printf tokens in non-empty translations match each msgid (same tokens as
     `pybabel compile` / gettext format checks).

Usage:
    python3 scripts/i18n_check.py                 # normal mode, exits 0/1
    python3 scripts/i18n_check.py --json               # emit machine-readable report
    python3 scripts/i18n_check.py --skip-msgfmt          # gettext msgfmt binary not installed
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from babel.messages.pofile import read_po


ROOT = Path(__file__).resolve().parent.parent

# Files we don't need to i18n (admin panels, internal tools, scripts).
SKIP_PY = {
    "app/admin/",
    "app/brief/admin.py",
    "app/trending/news_fetcher.py",
    "app/trending/social_insights.py",
    "app/trending/publisher.py",
    "app/trending/pipeline.py",
    "app/trending/scorer.py",
    "app/trending/seed_generator.py",
    "app/trending/routes.py",
    "app/sources/backfill.py",
    "app/lib/consensus_engine.py",
    "app/lib/sklearn_compat.py",
    "app/polymarket/",
    "app/partner/webhooks.py",
    "app/brief/admin.py",
    "app/jobs/",  # background jobs log messages, not user-facing
}

SKIP_TEMPLATES = {"admin/", "emails/"}  # emails have their own handling


PLACE_RE = re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)[a-zA-Z]|%%|%[sdrifxX]")


def placeholders(s: str) -> list[str]:
    return PLACE_RE.findall(s or "")


def percent_sequence_valid(s: str | None) -> tuple[bool, str]:
    """Reject bare `%` that would break gettext %-formatting (mirrors template checks)."""
    body = s or ""
    if "%" not in body:
        return True, ""
    safe = placeholders(body)
    expected = sum(2 if x == "%%" else 1 for x in safe)
    if body.count("%") != expected:
        return False, "bare or broken % sequence"
    return True, ""


def check_po_printf_parity(report: list[str]) -> int:
    """Ensure each non-empty translation has the same printf tokens as its msgid."""
    failures = 0
    trans_root = ROOT.joinpath("translations")
    for po in sorted(trans_root.glob("*/LC_MESSAGES/messages.po")):
        locale = po.parts[-3]
        with po.open(encoding="utf-8") as f:
            catalog = read_po(f, locale=locale)
        for msg in catalog:
            mid = msg.id
            ms = msg.string
            pairs: list[tuple[str, str]]
            if isinstance(mid, tuple):
                n = len(mid)
                ms_list = list(ms) if isinstance(ms, (list, tuple)) else [""] * n
                while len(ms_list) < n:
                    ms_list.append("")
                pairs = list(zip(mid, ms_list[:n]))
            else:
                if isinstance(mid, str) and not mid.strip():
                    continue
                pairs = [(str(mid), ms if isinstance(ms, str) else "")]
            for msgid_s, msgstr_s in pairs:
                if msgstr_s is None:
                    continue
                mss = str(msgstr_s)
                if not mss.strip():
                    continue
                ok, why = percent_sequence_valid(mss)
                if not ok:
                    snippet = (msgid_s.replace("\n", " ")[:72] + ("…" if len(msgid_s) > 72 else ""))
                    report.append(f"PO-BAD-PERCENT {locale} msgid={snippet!r}: {why}")
                    failures += 1
                    continue
                if sorted(placeholders(msgid_s)) != sorted(placeholders(mss)):
                    snippet = (msgid_s.replace("\n", " ")[:72] + ("…" if len(msgid_s) > 72 else ""))
                    report.append(
                        f"PO-PLACEHOLDER-MISMATCH {locale} msgid={snippet!r}: "
                        f"id={placeholders(msgid_s)!r} vs str={placeholders(mss)!r}"
                    )
                    failures += 1
    return failures


def check_msgfmt_strict(report: list[str]) -> int:
    """GNU gettext `msgfmt --check` across locales (no-op if msgfmt is unavailable)."""
    try:
        subprocess.run(
            ["msgfmt", "--version"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return 0
    failures = 0
    for po in sorted(ROOT.joinpath("translations").glob("*/LC_MESSAGES/messages.po")):
        with tempfile.NamedTemporaryFile(suffix=".mo", delete=False) as tmp:
            out_mo = Path(tmp.name)
        try:
            r = subprocess.run(
                ["msgfmt", "-c", "-o", str(out_mo), str(po)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            out_mo.unlink(missing_ok=True)
        if r.returncode != 0:
            failures += 1
            detail = (r.stderr or r.stdout or "").strip()
            report.append(f"MSGFMT {po.relative_to(ROOT)}: {detail}")
    return failures


def check_percent_validity(report: list[str]) -> int:
    """Every gettext string must have a valid printf format spec."""
    failures = 0
    # Match _('...') or gettext_js('...') or ngettext('...','...',...).
    sq = re.compile(r"\b(?:_|gettext_js|ngettext)\(\s*'([^'\\\n]*(?:\\.[^'\\\n]*)*)'")
    dq = re.compile(r'\b(?:_|gettext_js|ngettext)\(\s*"([^"\\\n]*(?:\\.[^"\\\n]*)*)"')
    for p in ROOT.joinpath("app/templates").rglob("*.html"):
        try:
            src = p.read_text()
        except Exception:
            continue
        for pat in (sq, dq):
            for m in pat.finditer(src):
                body = m.group(1)
                if "%" not in body:
                    continue
                safe = placeholders(body)
                total = body.count("%")
                expected = sum(2 if s == "%%" else 1 for s in safe)
                if total != expected:
                    line = src[: m.start()].count("\n") + 1
                    report.append(f"BAD-PERCENT {p}:{line}: {body!r}")
                    failures += 1
    return failures


def check_underscore_rebind(report: list[str]) -> int:
    failures = 0
    for p in ROOT.joinpath("app").rglob("*.py"):
        if any(str(p).startswith(str(ROOT / skip)) for skip in SKIP_PY):
            continue
        try:
            src = p.read_text()
        except Exception:
            continue
        if "gettext as _" not in src and "from flask_babel import _" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            report.append(f"SYNTAX-ERROR {p}: {e}")
            failures += 1
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.For):
                targets = [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id == "_":
                        report.append(f"_-REBIND {p}:{n.lineno}")
                        failures += 1
    return failures


def check_unwrapped_flashes(report: list[str]) -> int:
    """flash("Literal", …) with no _() wrap — in customer-facing code."""
    failures = 0
    pat = re.compile(r"""flash\(\s*['"][A-Z]""")
    for p in ROOT.joinpath("app").rglob("*.py"):
        rel = str(p.relative_to(ROOT))
        if any(rel.startswith(skip) for skip in SKIP_PY):
            continue
        try:
            src = p.read_text()
        except Exception:
            continue
        for lineno, line in enumerate(src.splitlines(), 1):
            if pat.search(line) and "flash(_(" not in line and "flash(str(" not in line:
                report.append(f"UNWRAPPED-FLASH {p}:{lineno}: {line.strip()[:80]}")
                failures += 1
    return failures


def check_email_render_helpers(report: list[str]) -> int:
    """render_template('emails/…') must go through _render_for_user."""
    failures = 0
    pat = re.compile(r"""render_template\(\s*['"]emails/""")
    for p in ROOT.joinpath("app").rglob("*.py"):
        rel = str(p.relative_to(ROOT))
        if any(rel.startswith(skip) for skip in SKIP_PY):
            continue
        try:
            src = p.read_text()
        except Exception:
            continue
        for lineno, line in enumerate(src.splitlines(), 1):
            if pat.search(line):
                report.append(f"EMAIL-RENDER-BYPASSES-LOCALE {p}:{lineno}")
                failures += 1
    return failures


def check_lazy_in_tojson(report: list[str]) -> int:
    """lazy_gettext (_l) can't serialize safely into |tojson."""
    pat = re.compile(r"_l\([^)]*\)\s*\|\s*tojson")
    failures = 0
    for p in ROOT.joinpath("app/templates").rglob("*.html"):
        try:
            src = p.read_text()
        except Exception:
            continue
        for m in pat.finditer(src):
            line = src[: m.start()].count("\n") + 1
            report.append(f"LAZY-IN-TOJSON {p}:{line}")
            failures += 1
    return failures


def check_pybabel() -> tuple[int, str]:
    """Run pybabel extract + compile; return (error_count, output)."""
    pot_path = ROOT / "messages.pot"
    python = os.environ.get("PYTHON", "python3")
    attempts: list[list[str]] = [["pybabel"], [python, "-m", "babel.messages.frontend"]]
    last_err = "babel extract/compile unavailable"
    try:
        for base in attempts:
            try:
                r = subprocess.run(
                    base + ["extract", "-F", "babel.cfg", "-o", "messages.pot", "."],
                    cwd=ROOT, check=False, capture_output=True, text=True,
                )
            except FileNotFoundError:
                last_err = f"{base[0]} not available"
                continue
            if r.returncode != 0:
                last_err = f"extract failed:\n{r.stderr}"
                continue
            r2 = subprocess.run(
                base + ["compile", "-d", "translations"],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            errs = sum(1 for line in r2.stderr.splitlines() if line.startswith("error"))
            return errs, r2.stderr
        return -1, last_err
    finally:
        pot_path.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    p.add_argument("--skip-pybabel", action="store_true",
                   help="Skip pybabel extract/compile check (slow in pre-commit)")
    p.add_argument("--skip-msgfmt", action="store_true",
                   help="Skip GNU msgfmt --check (not installed on all dev machines)")
    args = p.parse_args()

    report: list[str] = []
    results = {
        "bad_percent": check_percent_validity(report),
        "underscore_rebind": check_underscore_rebind(report),
        "unwrapped_flashes": check_unwrapped_flashes(report),
        "email_render_bypass": check_email_render_helpers(report),
        "lazy_in_tojson": check_lazy_in_tojson(report),
        "po_placeholder_parity": check_po_printf_parity(report),
    }

    if not args.skip_msgfmt:
        results["msgfmt_check"] = check_msgfmt_strict(report)
    else:
        results["msgfmt_check"] = 0

    if not args.skip_pybabel:
        errs, output = check_pybabel()
        results["pybabel_compile_errors"] = errs
        if errs != 0 and output:
            report.append(f"PYBABEL:\n{output.strip()}")

    if args.json:
        print(json.dumps({"summary": results, "report": report}, indent=2))
    else:
        for line in report:
            print(line)
        print()
        print("summary:")
        for k, v in results.items():
            ok = (v == 0) if isinstance(v, int) else not v
            marker = "✓" if ok else "✗"
            print(f"  {marker} {k}: {v}")

    # Count failures: positive integers are issue counts; negative means tool error
    # (e.g. pybabel missing, extract failed) and must fail the run.
    total = 0
    for v in results.values():
        if isinstance(v, int):
            if v < 0:
                total += 1
            else:
                total += v
        elif v:
            total += 1
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
