"""DEPRECATED — do not run this script.

Translatable strings are now extracted automatically from templates and Python
source via pybabel. The canonical i18n workflow is:

  # 1. Extract strings from source into a .pot template
  pybabel extract -F babel.cfg -o messages.pot .

  # 2. Merge new/changed strings into all locale .po files
  pybabel update -d translations -i messages.pot

  # 3. Fill in empty msgstr values, then compile
  pybabel compile -d translations

After step 2, audit for empty msgstr and fuzzy entries:
  grep -rn 'msgstr ""' translations/*/LC_MESSAGES/messages.po
  grep -rn '^#, fuzzy' translations/*/LC_MESSAGES/messages.po

The compile step is also run automatically by .github/workflows/i18n-compile.yml.
"""
import sys

print(__doc__)
sys.exit(1)
