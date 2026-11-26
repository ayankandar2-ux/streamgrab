#!/usr/bin/env bash
# Create the GitHub repository and push the current tree.
#
#   ./scripts/publish.sh [repo-name] [public|private]
#
# Requires GitHub CLI authentication:  gh auth login   (or export GH_TOKEN=...)
set -euo pipefail

REPO="${1:-streamgrab}"
VISIBILITY="${2:-public}"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: GitHub CLI (gh) is not installed." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "error: not authenticated with GitHub." >&2
  echo "       run: gh auth login    (or: export GH_TOKEN=<token>)" >&2
  exit 1
fi

if [ ! -d .git ]; then
  git init -b main
fi

git add -A
if ! git diff --cached --quiet; then
  git commit -m "streamgrab ${REPO} initial release"
fi

gh repo create "$REPO" "--$VISIBILITY" --source=. --remote=origin --push

echo "Published: $(gh repo view --json url -q .url)"
