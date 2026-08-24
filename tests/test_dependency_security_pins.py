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


def test_dependabot_does_not_open_cryptography_resolve_ceiling_prs():
    """atproto caps <47; patched wheel is the install-script override only."""
    pip_block = _read(".github/dependabot.yml").split("package-ecosystem: npm", 1)[0]
    assert 'dependency-name: "cryptography"' in pip_block


def test_dependabot_does_not_let_known_majors_starve_the_weekly_slot_limit():
    """Version majors we will not merge as drive-bys must not occupy open-pull-requests-limit."""
    pip_block = _read(".github/dependabot.yml").split("package-ecosystem: npm", 1)[0]
    for name in (
        "stripe",
        "redis",
        "flask-limiter",
        "cachelib",
        "setuptools",
        "posthog",
        "openai",
        "anthropic",
        "greenlet",
    ):
        assert f'dependency-name: "{name}"' in pip_block, (
            f"Dependabot must ignore {name} majors/bound-widens so patch PRs can land"
        )
    assert 'versions: [">=7.37.6"]' in pip_block
    assert 'exclude-patterns:' in pip_block
    assert '"posthog"' in pip_block.split("exclude-patterns:", 1)[1][:200]


def test_github_actions_use_current_setup_majors_and_bust_pip_cache_on_install_script():
    workflows = list((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "expected workflow files"
    for path in workflows:
        src = path.read_text(encoding="utf-8")
        assert "actions/setup-python@v6" not in src, path
        assert "actions/setup-node@v6" not in src, path
        if "actions/setup-python@" in src:
            assert "actions/setup-python@v7" in src, path
            assert "scripts/install_python_deps.sh" in src, (
                f"{path} must include the install script in pip cache keys"
            )
        if "actions/setup-node@" in src:
            assert "actions/setup-node@v7" in src, path


def test_unbounded_transitives_of_limiter_and_redis_are_capped():
    """flask-limiter declares limits>=3.13; redis 5.3 declares PyJWT>=2.9 — both unbounded."""
    pins = _requirement_pins(_read("requirements.txt"))
    assert "limits>=5.8.0,<6" in pins
    assert "PyJWT>=2.9.0,<3" in pins
    assert "flask-limiter==3.12" in pins
    assert "redis==5.3.1" in pins
    assert "sentry-sdk==2.68.0" in pins
    assert "msgspec>=0.18.6,<0.22" in pins
    assert "greenlet>=3.2.2,<4" in pins
    assert any(p.startswith("posthog>=") and "<7.37.6" in p for p in pins), pins
    assert any(p.startswith("openai>=") and p.endswith(",<3") for p in pins), pins
    anthropic_pins = [p for p in pins if p.lower().startswith("anthropic>=")]
    assert len(anthropic_pins) == 1, anthropic_pins
    assert "<0." in anthropic_pins[0], anthropic_pins[0]
    ceiling = anthropic_pins[0].split(",")[-1]
    assert not ceiling.startswith("<1"), (
        f"anthropic ceiling must stay on 0.x until a dedicated 1.x review; got {ceiling}"
    )
    assert SETUPTOOLS_PIN in pins


def test_security_audit_runs_on_main_when_the_install_path_changes():
    source = _read(".github/workflows/security.yml")
    assert "branches: [main]" in source
    push_idx = source.index("push:")
    pr_idx = source.index("pull_request:")
    assert push_idx < pr_idx, "push-to-main must be a first-class trigger, not only PRs"
