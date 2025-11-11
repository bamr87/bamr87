#!/usr/bin/env bash
set -euo pipefail

# updates each submodule to remote latest and commits parent if pointers changed
echo "Updating submodules (init, fetch, update)..."
git submodule sync --recursive
git submodule update --init --recursive --remote

echo "Checking for changes in parent repo (submodule pointer updates)..."
if ! git diff --quiet --exit-code; then
  echo "Submodule pointer(s) changed. Creating commit and pushing..."
  git add .
  git commit -m "ci: update submodule pointers"
  git push
else
  echo "No submodule pointer changes detected. Nothing to commit."
fi
