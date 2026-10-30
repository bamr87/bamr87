#!/usr/bin/env bash
# =============================================================================
# tools/jev/merge-regen.sh — the `jev-regen` git merge driver.
#
# A generated file has no meaningful merge: neither side is authored, and the
# only correct content is whatever its generator produces from the merged
# INPUTS. Resolving one by hand — or by any three-way diff — produces a file
# that looks plausible, passes review, and is wrong until the next regeneration
# silently rewrites it.
#
# So this driver does the only honest thing: it keeps OURS verbatim, records the
# path in .git/jev-regen-pending, and reports the merge as clean. Nothing is
# lost, because nothing in a generated file is a source. The recorded path is
# the to-do list: regenerate, then commit. CI re-runs every generator and fails
# on drift, so a forgotten regeneration is caught by the gate rather than by a
# reader of the wrong file.
#
# Git calls it as:  merge-regen.sh %O %A %B %P
#   %O  the common ancestor's version   (unused — there is nothing to reconcile)
#   %A  OURS, and the file git takes the result from
#   %B  theirs
#   %P  the pathname in the working tree
#
# Enable it once per clone (git cannot configure a driver from .gitattributes;
# an unconfigured driver falls back to the default text merge, which is exactly
# the hand-merge this avoids, so this is worth doing):
#
#   git config merge.jev-regen.name   "keep ours, regenerate"
#   git config merge.jev-regen.driver "tools/jev/merge-regen.sh %O %A %B %P"
#
# Doc: docs/JEV.md · tools/jev/README.md
# =============================================================================
set -euo pipefail

ours="${2:-}"
path="${4:-unknown}"

if [ -z "$ours" ] || [ ! -f "$ours" ]; then
  echo "jev-regen: no 'ours' version to keep for ${path}" >&2
  exit 1
fi

# A `jev-main-only` file belongs to main: take THEIRS (%B — main, when main is
# merged into a branch) so the branch stops carrying a diff to it. The post-merge
# job on main regenerates it (docs/JEV.md "Main-only generated files").
theirs="${3:-}"
if [ -n "$theirs" ] && [ -f "$theirs" ] && \
   [ "$(git check-attr jev-main-only -- "$path" 2>/dev/null | awk -F': ' '{print $3}')" = "set" ]; then
  cp "$theirs" "$ours"
  echo "jev-regen: took main's copy of ${path} (main-only, regenerated on main)" >&2
  exit 0
fi

git_dir="$(git rev-parse --git-dir 2>/dev/null || echo .git)"
printf '%s\n' "$path" >> "${git_dir}/jev-regen-pending"

echo "jev-regen: kept ours for ${path} — regenerate it before committing" >&2
exit 0
