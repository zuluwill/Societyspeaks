#!/usr/bin/env bash
# Install runtime Python deps the same way production / CI do.
#
# atproto still declares cryptography<47 (MarshalX/atproto#688), so a plain
# `pip install -r requirements.txt` cannot resolve patched cryptography wheels
# (GHSA-537c-gmf6-5ccf needs >=48.0.1; GHSA-g6cj-pr64-35w5 / related need
# >=50.0.0). After the normal resolve we force-reinstall that wheel
# (--no-deps: cffi etc. already present). Drop the force-reinstall the moment
# atproto relaxes its upper bound.
#
# Used by: Dockerfile, Tests / Security audit / i18n / journey-links CI,
# scripts/build.sh, scripts/post-merge.sh. Keep this the single source of
# truth for the cryptography override pin — do not duplicate it elsewhere.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-python3}"

# Patched cryptography wheel (OpenSSL + PKCS#7 / name-constraints GHSAs).
# Single pin for Docker + CI. Dependabot still flags the <47 resolve pin in
# requirements.txt — that is expected until atproto relaxes; runtime uses this.
CRYPTOGRAPHY_OVERRIDE='cryptography>=50.0.0,<51'

# --timeout/--retries: this script also runs from post-merge.sh on Render,
# where the network to PyPI is occasionally flaky; keep the resilience the
# inlined `pip install` calls used to have.
# PIP_NO_CACHE_DIR=1 (set in the Dockerfile) is honoured by pip automatically.
PIP_FLAGS=(--disable-pip-version-check --timeout 60 --retries 5)

"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" --upgrade pip
"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" -r requirements.txt
"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" --force-reinstall --no-deps \
  "$CRYPTOGRAPHY_OVERRIDE"
