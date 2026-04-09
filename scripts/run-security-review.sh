#!/usr/bin/env bash
# Run Claude Code Security Review (https://github.com/anthropics/claude-code-security-review)
# locally against a PR. Requires: ANTHROPIC_API_KEY, optional GITHUB_TOKEN.
#
# Usage:
#   export ANTHROPIC_API_KEY=your_key
#   ./scripts/run-security-review.sh [PR_NUMBER]
#   # If PR_NUMBER omitted, uses PR 3 (chore/security-review-workflow).
set -e
REPO="zuluwill/Societyspeaks"
PR="${1:-3}"
WORK_DIR="${WORK_DIR:-$HOME/code/audit}"
REVIEW_DIR="${REVIEW_DIR:-/tmp/claude-code-security-review}"
OUTPUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/security-review-results"

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Error: ANTHROPIC_API_KEY is not set."
  echo "Set it with: export ANTHROPIC_API_KEY=your_key"
  exit 1
fi

if [ ! -d "$REVIEW_DIR" ]; then
  echo "Cloning claude-code-security-review into $REVIEW_DIR ..."
  git clone --depth 1 https://github.com/anthropics/claude-code-security-review.git "$REVIEW_DIR"
fi

cd "$REVIEW_DIR"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r claudecode/requirements.txt -q
fi

mkdir -p "$OUTPUT_DIR"
echo "Running security review for $REPO#$PR (output: $OUTPUT_DIR)"
.venv/bin/python -m claudecode.evals.run_eval "$REPO#$PR" --verbose --output-dir "$OUTPUT_DIR" --work-dir "$WORK_DIR"
