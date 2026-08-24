"""Contracts so GHSA floors cannot silently drift out of the install path."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SETUPTOOLS_PIN = "setuptools>=83.0.0,<84"
NANOID_PIN = "3.3.18"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _non_comment_source(source: str) -> str:
    """Drop full-line comments so order checks do not match the header prose."""
    return "\n".join(
        line
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _requirement_pins(source: str) -> list[str]:
    return [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_setuptools_floor_is_shared_and_applied_before_requirements():
    """PYSEC-2026-3447 / GHSA-h35f-9h28-mq5c — patched FileList in 83.0.0."""
    requirements = _read("requirements.txt")
    script = _read("scripts/install_python_deps.sh")
    executable = _non_comment_source(script)
    pins = _requirement_pins(requirements)
    assert SETUPTOOLS_PIN in pins, (
        "requirements.txt must pin the setuptools floor so a naive "
        f"`pip install -r` cannot leave the image default; expected {SETUPTOOLS_PIN}"
    )
    assert f"SETUPTOOLS_FLOOR='{SETUPTOOLS_PIN}'" in script, (
        "install_python_deps.sh must use the same specifier as requirements.txt"
    )
    floor_install = '"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" --upgrade "$SETUPTOOLS_FLOOR"'
    req_install = '"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" -r requirements.txt'
    assert floor_install in executable
    assert req_install in executable
    assert executable.index(floor_install) < executable.index(req_install)
    assert "--ignore-vuln" not in executable


def test_cryptography_override_stays_only_in_the_install_script():
    """atproto still caps cryptography<47; patched wheel is a post-resolve override."""
    script = _read("scripts/install_python_deps.sh")
    pins = _requirement_pins(_read("requirements.txt"))
    assert "CRYPTOGRAPHY_OVERRIDE='cryptography>=50.0.0,<51'" in script
    assert "--force-reinstall" in script
    assert "--no-deps" in script
    assert "cryptography>=46.0.4,<47" in pins
    assert not any(p.startswith("cryptography>=50") for p in pins)


def test_security_workflow_asserts_floors_and_does_not_ignore_advisories():
    source = _read(".github/workflows/security.yml")
    executable = _non_comment_source(source)
    assert "--ignore-vuln" not in executable
    assert "pip-audit --skip-editable" in source
    assert '_parts("cryptography")' in source
    assert '_parts("setuptools")' in source
    assert "(50, 0, 0)" in source
    assert "(83, 0, 0)" in source
    assert "npm audit --audit-level=high" in source
    assert "npm ci" in source
    assert "package.json" in source
    assert "package-lock.json" in source


def test_nanoid_override_stays_on_patched_3x_not_esm_majors():
    """GHSA-2v37-7h3g-55p8 / CVE-2026-67213. postcss 8 needs nanoid 3.x."""
    package = json.loads(_read("package.json"))
    lock = json.loads(_read("package-lock.json"))
    assert package["overrides"]["nanoid"] == NANOID_PIN

    nano = lock["packages"]["node_modules/nanoid"]
    parts = tuple(int(p) for p in nano["version"].split("."))
    assert parts >= (3, 3, 18), (
        f"lockfile nanoid must be >=3.3.18 (GHSA-2v37), got {nano['version']}"
    )
    assert parts[0] == 3, (
        f"lockfile nanoid must stay on 3.x (postcss 8 / Tailwind 3); got {nano['version']}"
    )

    dependabot = _read(".github/dependabot.yml")
    assert 'dependency-name: "nanoid"' in dependabot
    assert "version-update:semver-major" in dependabot.split('dependency-name: "nanoid"', 1)[1][:400]
