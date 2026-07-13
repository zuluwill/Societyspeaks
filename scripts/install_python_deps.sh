#!/usr/bin/env bash
# Install runtime Python deps the same way production / CI do.
#
# atproto still declares cryptography<47 (MarshalX/atproto#688), so a plain
# `pip install -r requirements.txt` cannot resolve the patched OpenSSL wheel
# for GHSA-537c-gmf6-5ccf (fixed only in cryptography>=48.0.1). After the
# normal resolve we force-reinstall that wheel (--no-deps: cffi etc. already
# present). Drop the force-reinstall the moment atproto relaxes its upper bound.
#
# Used by: Dockerfile, Tests / Security audit / i18n / journey-links CI,
# scripts/build.sh, scripts/post-merge.sh. Keep this the single source of
# truth for the cryptography override pin — do not duplicate it elsewhere.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-python3}"

# Patched OpenSSL wheel for GHSA-537c-gmf6-5ccf. Single pin for Docker + CI.
CRYPTOGRAPHY_OVERRIDE='cryptography>=48.0.1,<50'

# --timeout/--retries: this script also runs from post-merge.sh on Render,
# where the network to PyPI is occasionally flaky; keep the resilience the
# inlined `pip install` calls used to have.
# PIP_NO_CACHE_DIR=1 (set in the Dockerfile) is honoured by pip automatically.
PIP_FLAGS=(--disable-pip-version-check --timeout 60 --retries 5)

"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" --upgrade pip
"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" -r requirements.txt
"$PYTHON_BIN" -m pip install "${PIP_FLAGS[@]}" --force-reinstall --no-deps \
  "$CRYPTOGRAPHY_OVERRIDE"
