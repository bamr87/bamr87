#!/usr/bin/env bash
# ============================================================================
# File:          tools/pg-major-upgrade.sh
# Description:   Upgrade a compose service's Postgres across a MAJOR version
#                without losing its local data — backs up, dumps, recreates
#                the volume on the new layout, and restores.
# Author:        bamr87
# Created:       2026-09-21
# Last Modified: 2026-09-21
# Version:       1.0.0
# Usage:
#   tools/pg-major-upgrade.sh [--yes] [--service NAME] -- <docker compose args>
#   tools/pg-major-upgrade.sh --check -- <docker compose args>   # exit 3 if a volume is behind its image
#   tools/dash dev db-upgrade <project> [--yes] [--service NAME]      (via the fleet driver)
#
#   e.g.  tools/pg-major-upgrade.sh -- -p law-ai -f projects/law-ai/docker-compose.yml
# ============================================================================
#
# WHY THIS EXISTS
#
# A Postgres major bump orphans every existing local volume: the new server
# refuses data written by an older major ("database files are incompatible with
# server"), and Postgres 18 also moved its data directory, so the old mount path
# is a hard startup error. The fleet-wide image bump (docs/DOCKER.md) therefore
# needs an answer better than "delete your data".
#
# WHAT IT DOES — and the order matters, because each step must be recoverable
#   1. stop the service (releases the volume)
#   2. copy the RAW volume to `<volume>-pre<major>`     <- undo button, kept
#   3. pg_dumpall from a throwaway server of the OLD major, into
#      ~/.fleet-backups/                                 <- portable copy, kept
#   4. verify the dump is complete before anything is removed
#   5. remove the original volume, start the service on the NEW image + layout
#   6. restore the dump
#
# DRY RUN BY DEFAULT: without --yes it prints the plan and changes nothing.
#
# SCOPE: plain `postgres` images. TimescaleDB (and other extension images) are
# refused — restoring their dump needs the extension present in the OLD server,
# and guessing that image would be the kind of confident wrongness that eats data.

set -euo pipefail

YES=0
CHECK=0
SERVICE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)     YES=1; shift ;;
    --check)   CHECK=1; shift ;;
    --service) SERVICE="${2:?--service needs a name}"; shift 2 ;;
    --)        shift; break ;;
    -h|--help) sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         echo "pg-major-upgrade: unknown option '$1' (compose args go after --)" >&2; exit 2 ;;
  esac
done
[[ $# -gt 0 ]] || { echo "pg-major-upgrade: compose args required after --  (e.g. -- -p proj -f docker-compose.yml)" >&2; exit 2; }
COMPOSE=(docker compose "$@")

say()  { printf '%s\n' "$*"; }
die()  { printf '\033[31mpg-major-upgrade: %s\033[0m\n' "$*" >&2; exit 1; }
# --check runs on EVERY `dash dev up`, so "this project has no Postgres" is the
# common case and must be silent; the upgrade path treats the same as an error.
skip() { [[ $CHECK -eq 1 ]] && exit 0; die "$*"; }

# --- 1. what does the compose file say? -----------------------------------
PY="$(command -v python3)"
PLAN="$("${COMPOSE[@]}" config --format json 2>/dev/null | "$PY" -c '
import json, sys, re
want = sys.argv[1]
d = json.load(sys.stdin)
project = d.get("name", "")
out = []
for name, svc in (d.get("services") or {}).items():
    img = svc.get("image", "")
    if not re.match(r"^(docker\.io/(library/)?)?postgres:", img) and "timescale" not in img:
        continue
    if want and name != want:
        continue
    env = svc.get("environment") or {}
    user = env.get("POSTGRES_USER", "postgres")
    vol = None; target = None
    for v in svc.get("volumes") or []:
        if v.get("type") == "volume" and v.get("target", "").startswith("/var/lib/postgresql"):
            vol = v.get("source"); target = v.get("target")
    out.append((name, img, user, vol or "", target or "", project))
for o in out:
    print("\t".join(o))
' "$SERVICE")"

[[ -n "$PLAN" ]] || skip "no Postgres service found${SERVICE:+ named '$SERVICE'} in that compose project"

# --- 2. what major is on disk vs what the image will run? ---------------------
# Sets SVC IMAGE PGUSER VOLSRC TARGET PROJECT NEW_MAJOR VOLUME OLD_MAJOR from one
# tab-separated PLAN row. OLD_MAJOR stays empty when there is no volume yet.
analyze() {
  IFS=$'\t' read -r SVC IMAGE PGUSER VOLSRC TARGET PROJECT <<<"$1"
  local tag="${IMAGE#*:}"
  # TimescaleDB tags carry the Postgres major as `-pgNN`; plain images lead with it.
  if [[ "$tag" =~ -pg([0-9]+) ]]; then NEW_MAJOR="${BASH_REMATCH[1]}"
  else NEW_MAJOR="$(printf '%s' "$tag" | sed -E 's/^([0-9]+).*/\1/')"; fi
  VOLUME="${PROJECT}_${VOLSRC}"
  OLD_MAJOR=""
  if [[ -n "$VOLSRC" ]] && docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    OLD_MAJOR="$(docker run --rm -v "$VOLUME":/v:ro alpine sh -c 'f=$(find /v -maxdepth 3 -name PG_VERSION 2>/dev/null | head -1); [ -n "$f" ] && cat "$f"' 2>/dev/null | tr -dc '0-9' || true)"
  fi
}

if [[ $CHECK -eq 1 ]]; then
  rc=0
  while IFS= read -r row; do
    analyze "$row"
    if [[ -n "$OLD_MAJOR" && -n "$NEW_MAJOR" && "$OLD_MAJOR" -lt "$NEW_MAJOR" ]]; then
      printf 'MISMATCH\t%s\t%s\t%s\t%s\n' "$SVC" "$OLD_MAJOR" "$NEW_MAJOR" \
        "$([[ "$IMAGE" == *timescale* ]] && echo manual || echo auto)"
      rc=3
    fi
  done <<<"$PLAN"
  exit $rc
fi

[[ "$(printf '%s\n' "$PLAN" | wc -l | tr -d ' ')" == "1" ]] \
  || die "several Postgres services — pick one with --service:$(printf '\n  %s' "$(printf '%s\n' "$PLAN" | cut -f1)")"

analyze "$PLAN"
[[ "$IMAGE" != *timescale* ]] || die "'$SVC' is a TimescaleDB image; restoring its dump needs the extension in the OLD server. Do this one by hand (see docs/DOCKER.md)."
[[ -n "$VOLSRC" ]] || die "'$SVC' has no named volume under /var/lib/postgresql — nothing persistent to migrate"
docker volume inspect "$VOLUME" >/dev/null 2>&1 || die "volume '$VOLUME' does not exist — nothing to migrate (a fresh 'up' will just work)"
[[ -n "$OLD_MAJOR" ]] || die "could not read PG_VERSION from volume '$VOLUME' (empty or not a Postgres cluster)"

say "service : $SVC   ($IMAGE)"
say "volume  : $VOLUME  (mounted at $TARGET)"
say "on disk : PostgreSQL $OLD_MAJOR   ->   image is $NEW_MAJOR"
if [[ "$OLD_MAJOR" == "$NEW_MAJOR" ]]; then
  say "nothing to do — the volume already holds major $NEW_MAJOR."; exit 0
fi
[[ "$OLD_MAJOR" -lt "$NEW_MAJOR" ]] || die "volume is NEWER ($OLD_MAJOR) than the image ($NEW_MAJOR); refusing to downgrade"

BACKUP_VOL="${VOLUME}-pre${OLD_MAJOR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DUMP_DIR="${FLEET_BACKUP_DIR:-$HOME/.fleet-backups}"
DUMP="$DUMP_DIR/${PROJECT}-${SVC}-pg${OLD_MAJOR}-${STAMP}.sql"

say
say "plan:"
say "  1. stop '$SVC'"
say "  2. copy raw volume -> $BACKUP_VOL                (kept: your undo button)"
say "  3. pg_dumpall from a throwaway postgres:$OLD_MAJOR-alpine -> $DUMP   (kept)"
say "  4. verify the dump, then remove '$VOLUME'"
say "  5. start '$SVC' on the new image, restore the dump"
if [[ $YES -ne 1 ]]; then
  say
  say "dry run — nothing changed. Re-run with --yes to perform it."
  exit 0
fi

# --- 3. do it ---------------------------------------------------------------
mkdir -p "$DUMP_DIR"
say; say "==> stopping $SVC"
"${COMPOSE[@]}" stop "$SVC" >/dev/null 2>&1 || true
"${COMPOSE[@]}" rm -f "$SVC" >/dev/null 2>&1 || true

say "==> backing up the raw volume to $BACKUP_VOL"
docker volume inspect "$BACKUP_VOL" >/dev/null 2>&1 && die "$BACKUP_VOL already exists — move or remove it first so a backup is never overwritten"
docker volume create "$BACKUP_VOL" >/dev/null
docker run --rm -v "$VOLUME":/from:ro -v "$BACKUP_VOL":/to alpine sh -c 'cp -a /from/. /to/'

say "==> dumping with a throwaway postgres:$OLD_MAJOR-alpine"
TMP="pgup-$$"
cleanup() { docker rm -f "$TMP" >/dev/null 2>&1 || true; }
trap cleanup EXIT
# The OLD major's data directory is the volume root, at the OLD mount path.
docker run -d --name "$TMP" -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v "$VOLUME":/var/lib/postgresql/data "postgres:${OLD_MAJOR}-alpine" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$TMP" pg_isready -U "$PGUSER" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$TMP" pg_isready -U "$PGUSER" >/dev/null 2>&1 || { docker logs "$TMP" 2>&1 | tail -5; die "old-major server did not come up — nothing removed; raw backup is at $BACKUP_VOL"; }
docker exec "$TMP" pg_dumpall -U "$PGUSER" >"$DUMP"
cleanup; trap - EXIT

say "==> verifying the dump before removing anything"
[[ -s "$DUMP" ]] || die "dump is empty — nothing removed; raw backup is at $BACKUP_VOL"
tail -3 "$DUMP" | grep -q 'PostgreSQL database cluster dump complete' \
  || die "dump looks truncated — nothing removed; raw backup is at $BACKUP_VOL, partial dump at $DUMP"
say "    $(wc -c <"$DUMP" | tr -d ' ') bytes, complete"

say "==> recreating '$VOLUME' on the new layout and starting $SVC"
docker volume rm "$VOLUME" >/dev/null
"${COMPOSE[@]}" up -d "$SVC" >/dev/null
CID="$("${COMPOSE[@]}" ps -q "$SVC")"
for _ in $(seq 1 90); do
  docker exec "$CID" pg_isready -U "$PGUSER" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$CID" pg_isready -U "$PGUSER" >/dev/null 2>&1 || die "new server did not come up; raw backup: $BACKUP_VOL, dump: $DUMP"

say "==> restoring"
# The bootstrap role already exists in the fresh cluster, so pg_dumpall's
# CREATE ROLE for it errors harmlessly; psql continues past errors by default.
docker exec -i "$CID" psql -q -U "$PGUSER" -d postgres <"$DUMP" >/dev/null 2>"$DUMP.restore.log" || true
ERRS="$(grep -c '^ERROR' "$DUMP.restore.log" 2>/dev/null || true)"

say
say "done: $SVC is on PostgreSQL $NEW_MAJOR."
say "  restore errors: ${ERRS:-0} (a few 'role already exists' lines are expected; see $DUMP.restore.log)"
say "  kept:  volume $BACKUP_VOL   and   $DUMP"
say "  once you are satisfied:  docker volume rm $BACKUP_VOL"
