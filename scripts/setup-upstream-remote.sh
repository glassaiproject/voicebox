#!/usr/bin/env bash
set -euo pipefail

UPSTREAM="${1:-https://github.com/jamiepine/voicebox.git}"

if git remote get-url upstream >/dev/null 2>&1; then
  echo "Remote 'upstream' already exists:"
  git remote get-url upstream
  exit 0
fi

git remote add upstream "$UPSTREAM"
echo "Added remote upstream -> $UPSTREAM"
