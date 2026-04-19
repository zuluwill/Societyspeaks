#!/usr/bin/env bash
# Compile gettext .po → .mo for Flask-Babel (run in CI and before production deploy).
# When UI strings in scripts/generate_po_files.py change, run: python3 scripts/generate_po_files.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if ! command -v pybabel >/dev/null 2>&1; then
  echo "pybabel not found; install dependencies (pip install -r requirements.txt)" >&2
  exit 1
fi
pybabel compile -d translations
echo "OK: compiled catalogs under ${ROOT}/translations/"
