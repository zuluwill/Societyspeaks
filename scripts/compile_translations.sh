#!/usr/bin/env bash
# Compile gettext .po → .mo for Flask-Babel (run in CI and before production deploy).
#
# Full i18n workflow after adding new UI strings:
#   1. pybabel extract -F babel.cfg -o messages.pot .
#   2. pybabel update --ignore-obsolete -d translations -i messages.pot
#      (--ignore-obsolete avoids #~ obsolete blocks that duplicate live msgids;
#       GNU gettext 0.26+ msgfmt -c rejects those duplicates.)
#   3. ANTHROPIC_API_KEY=... python3 scripts/translate_po_with_haiku.py  # fill empty msgstrs
#   4. ./scripts/compile_translations.sh  (this script)  # rebuild .mo files
#   5. python3 scripts/i18n_check.py  # sanity check placeholders / bindings
#   If legacy .po files still have #~ collisions, run: python3 scripts/strip_po_obsolete.py
#
# Deploy (scripts/build.sh) also runs step 4 automatically.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if ! command -v pybabel >/dev/null 2>&1; then
  echo "pybabel not found; install dependencies (pip install -r requirements.txt)" >&2
  exit 1
fi
pybabel compile -d translations
echo "OK: compiled catalogs under ${ROOT}/translations/"
