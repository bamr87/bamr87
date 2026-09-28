#!/usr/bin/env bash
# ============================================================================
# File:          tools/fleet-dev.sh
# Description:   THE entry point for the fleet dev stack — launch, debug and
#                work on any submodule (or all of them) from the hub.
# Author:        bamr87
# Created:       2026-09-20
# Last Modified: 2026-09-20
# Version:       1.0.0
# Usage:
#   tools/fleet-dev.sh up [project...|--all]     start (default: hub)
#   tools/fleet-dev.sh up <project> --debug      ...with the repo's debugpy layer
#   tools/fleet-dev.sh down [project...|--all]   stop
#   tools/fleet-dev.sh build <project> [svc...]  build images
#   tools/fleet-dev.sh ps [project...]           what is running, with URLs
#   tools/fleet-dev.sh logs <project> [svc]      follow logs
#   tools/fleet-dev.sh exec <project> <svc> ...  run a command in a service
#   tools/fleet-dev.sh config <project>          resolved compose for one project
#   tools/fleet-dev.sh db-upgrade <project> [--service S] [--yes]
#                                                upgrade a Postgres MAJOR without losing data
#   tools/fleet-dev.sh smoke {record|check|show} [--project P]
#                                                exercise every container; record/assert the baseline
#   tools/fleet-dev.sh ports [project]           the allocation table
#   tools/fleet-dev.sh list                      projects and how they are hosted
# ============================================================================
#
# WHY A DRIVER AND NOT ONE COMPOSE FILE
#
# Compose `include:` merges everything into a single project namespace, and
# across 16 independent repos the service names collide hard: `jekyll` is
# claimed by 5 projects, `redis` by 4, `worker`/`frontend`/`web` by 3 each.
# One file would silently fuse law-ai's frontend with ai-seed's.
#
# So each submodule runs as its OWN compose project (`-p <name>`), and they
# interconnect over the external network `fleet-net`. That is the standard
# multi-repo pattern and it is what actually scales to ~40 repos: per-project
# namespacing, `down` on one leaves the others alone, containers auto-named
# `<project>-<service>-1`, and a submodule started from its own directory joins
# the same network.
#
# The hub owns WHERE things are published (compose/overrides/*.yml, generated
# from _data/ports.yml); each submodule stays authoritative for WHAT it builds
# and is never modified. See docs/FLEET-COMPOSE.md.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Resolve a python that actually has PyYAML. `python3` on a stock macOS with
# Homebrew is frequently a bare interpreter while /usr/bin/python3 carries it,
# so probing beats assuming — this script is the fleet's front door and must
# not die on a fresh checkout.
resolve_py() {
  local cand
  for cand in "${PYTHON:-}" python3 /usr/bin/python3 python; do
    [[ -n "$cand" ]] || continue
    command -v "$cand" >/dev/null 2>&1 || continue
    "$cand" -c 'import yaml' >/dev/null 2>&1 && { echo "$cand"; return 0; }
  done
  return 1
}
if ! PY="$(resolve_py)"; then
  printf '\033[31mfleet-dev: no python with PyYAML found.\033[0m\n' >&2
  printf '  fix: pip3 install --user pyyaml    (or run inside devenv)\n' >&2
  exit 2
fi

ENV_FILE="$ROOT/.env.fleet"
NETWORK="fleet-net"
DEBUG=0
EXTRA=()

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*" >&2; }
c_dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

die() { c_err "fleet-dev: $*"; exit 1; }

# --- registry access -------------------------------------------------------
# One python call per query rather than a yaml parser in bash. `host` tells us
# whether a project has a compose project of its own or runs inside devenv.
reg_query() {
  "$PY" - "$@" <<'PY'
import sys, os, yaml
root = os.environ["FLEET_ROOT"]
reg = yaml.safe_load(open(os.path.join(root, "_data/ports.yml"))) or {}
projects = reg.get("projects") or {}
what = sys.argv[1]

if what == "compose-projects":
    for name, spec in projects.items():
        if (spec or {}).get("host") == "compose":
            print(name)
elif what == "compose-path":
    print((projects.get(sys.argv[2]) or {}).get("compose", ""))
elif what == "host":
    print((projects.get(sys.argv[2]) or {}).get("host", ""))
elif what == "list":
    for name, spec in projects.items():
        spec = spec or {}
        svcs = list((spec.get("services") or {}).keys())
        print(f"{name}\t{spec.get('host','?')}\t{','.join(svcs) or '-'}")
elif what == "urls":
    name = sys.argv[2]
    spec = projects.get(name) or {}
    # An excluded service is never started, so printing a URL for it would
    # advertise a port nothing is listening on.
    skip = set(spec.get("exclude") or {})
    for sname, alloc in (spec.get("services") or {}).items():
        if sname in skip:
            continue
        band = (alloc or {}).get("band", "")
        if band in ("jekyll", "frontend", "api", "docs", "hub"):
            print(f"{sname}\thttp://127.0.0.1:{alloc['port']}")
    for sname, alloc in (spec.get("debug") or {}).items():
        print(f"{sname} (debugpy)\t127.0.0.1:{alloc['port']}")
PY
}
export FLEET_ROOT="$ROOT"

is_project() { reg_query compose-projects | grep -qx "$1"; }

# --- preconditions ---------------------------------------------------------
ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    c_dim "  .env.fleet missing — generating from _data/ports.yml"
    "$PY" "$ROOT/tools/fleet-compose.py" env >/dev/null
  fi
}

# `fleet-net` is external so it outlives any one compose project and a
# submodule started from its own directory can join the hub's Phoenix.
ensure_network() {
  if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    c_dim "  creating network $NETWORK"
    docker network create "$NETWORK" >/dev/null
  fi
}

ensure_submodule() {
  local path="$1" name="$2"
  [[ -f "$ROOT/$path" ]] || die "projects/$name is not checked out (run: git submodule update --init projects/$name)"
}

# --- compose argv for one project -----------------------------------------
# The hub is a pseudo-project backed by compose.fleet.yml; everything else is
# the submodule's own file plus the hub's generated override. `-f base -f
# override` resolves relative paths against the FIRST file's directory, so the
# submodule's build contexts stay correct while the hub owns the port mapping.
compose_args() {
  local name="$1"
  if [[ "$name" == "hub" ]]; then
    printf '%s\n' -p fleet-hub --env-file "$ENV_FILE" -f "$ROOT/compose.fleet.yml"
    return
  fi
  local path; path="$(reg_query compose-path "$name")"
  [[ -n "$path" ]] || die "unknown project '$name' (try: tools/fleet-dev.sh list)"
  ensure_submodule "$path" "$name"
  printf '%s\n' -p "$name" --env-file "$ENV_FILE" -f "$ROOT/$path"

  # --debug layers the repo's OWN docker-compose.debug.yml — the file that
  # actually starts debugpy and bind-mounts the source. Without it an attach
  # config connects to nothing, because the normal command has no debugger in
  # it. djangoerp is the exception: its main compose is already debug-capable
  # behind DEBUGPY_ENABLE, so it ships no debug file and needs none.
  if [[ "$DEBUG" == "1" ]]; then
    local dbg="${path%/docker-compose.yml}/docker-compose.debug.yml"
    if [[ -f "$ROOT/$dbg" ]]; then
      printf '%s\n' -f "$ROOT/$dbg"
    else
      c_dim "  ($name ships no docker-compose.debug.yml — using the main stack)" >&2
    fi
  fi

  # The hub override goes LAST so its port allocation wins over both.
  [[ -f "$ROOT/compose/overrides/$name.yml" ]] && \
    printf '%s\n' -f "$ROOT/compose/overrides/$name.yml"
  return 0
}

# `compose_args` is always consumed through a subshell (process substitution or
# $(...)), where `die` can only kill the SUBSHELL — the caller carries on. With an
# empty array that became a bare `docker compose up -d`, which on bash >= 4.4
# (i.e. CI and Linux) silently targets whatever compose file is in the CWD: the
# HUB stack. So every consumer verifies it got arguments.
compose_args_or_die() {
  local name="$1" a
  ARGS=()
  while IFS= read -r a; do ARGS+=("$a"); done < <(compose_args "$name")
  [[ ${#ARGS[@]} -gt 0 ]] || die "could not resolve compose arguments for '$name'"
}

dc() {
  local name="$1"; shift
  compose_args_or_die "$name"
  docker compose "${ARGS[@]}" "$@"
}

# Projects named on the command line, or every checked-out one for --all.
targets() {
  if [[ $# -eq 0 ]]; then echo hub; return; fi
  if [[ "$1" == "--all" ]]; then
    echo hub
    while IFS= read -r p; do
      local path; path="$(reg_query compose-path "$p")"
      [[ -f "$ROOT/$path" ]] && echo "$p"
    done < <(reg_query compose-projects)
    return
  fi
  printf '%s\n' "$@"
}

print_urls() {
  local name="$1" any=0
  while IFS=$'\t' read -r svc url; do
    [[ -z "$svc" ]] && continue
    [[ $any -eq 0 ]] && any=1
    printf '      %-22s %s\n' "$svc" "$url"
  done < <(reg_query urls "$name")
}

# --- commands --------------------------------------------------------------
# Warn BEFORE `up` when a Postgres volume is behind its image. Otherwise the
# database restarts in a loop with "database files are incompatible with server",
# which reads as a broken stack rather than a one-command migration.
pg_preflight() {
  local p="$1" a out rc=0 args=()
  while IFS= read -r a; do args+=("$a"); done < <(compose_args "$p" 2>/dev/null)
  # A preflight is advisory: an unresolvable project is the caller's problem to
  # report, not this function's.
  [[ ${#args[@]} -gt 0 ]] || return 0
  out="$("$ROOT/tools/pg-major-upgrade.sh" --check -- "${args[@]}" 2>/dev/null)" || rc=$?
  [[ $rc -eq 3 ]] || return 0
  local tag svc old new how
  while IFS=$'\t' read -r tag svc old new how; do
    [[ "$tag" == "MISMATCH" ]] || continue
    c_warn "  ⚠ $p/$svc: its volume holds PostgreSQL $old but the image is $new — it will refuse to start."
    if [[ "$how" == "auto" ]]; then
      c_warn "    fix: tools/dash dev db-upgrade $p --service $svc --yes    (backs up first; a dry run without --yes)"
    else
      c_warn "    TimescaleDB: dump/restore by hand (docs/DOCKER.md), or drop the volume if the data is disposable."
    fi
  done <<<"$out"
}

cmd_up() {
  ensure_env; ensure_network
  local failed=0
  while IFS= read -r p; do
    c_ok "→ up $p"
    pg_preflight "$p"
    if dc "$p" up -d ${EXTRA[@]+"${EXTRA[@]}"}; then print_urls "$p"; else c_err "  $p failed"; failed=1; fi
  done < <(targets "$@")
  return $failed
}

cmd_down() {
  ensure_env
  while IFS= read -r p; do
    c_ok "→ down $p"
    dc "$p" down ${EXTRA[@]+"${EXTRA[@]}"} || c_warn "  $p: nothing to stop"
  done < <(targets "$@")
}

cmd_ps() {
  ensure_env
  while IFS= read -r p; do
    printf '\n\033[1m%s\033[0m\n' "$p"
    dc "$p" ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
  done < <(targets "$@")
}

cmd_build()  { ensure_env; local p="${1:?project}"; shift; dc "$p" build "$@"; }
cmd_logs()   { ensure_env; local p="${1:?project}"; shift; dc "$p" logs -f --tail=100 "$@"; }
cmd_exec()   { ensure_env; local p="${1:?project}"; shift; dc "$p" exec "$@"; }
cmd_config() { ensure_env; dc "${1:?project}" config; }
cmd_ports()  { "$PY" "$ROOT/tools/fleet-compose.py" show "$@"; }

# Connect to and exercise every running container, then hold the fleet to what
# was observed. `record` writes _data/smoke.yml; `check` re-probes and diffs.
cmd_smoke()  { "$PY" "$ROOT/tools/fleet_smoke.py" "$@"; }

# A Postgres MAJOR bump orphans existing volumes (the fleet-wide image bump in
# docs/DOCKER.md triggers exactly that). The helper backs up the raw volume,
# dumps, recreates on the new layout and restores; DRY RUN unless --yes.
cmd_db_upgrade() {
  local p="${1:?project}"; shift
  ensure_env; ensure_network
  compose_args_or_die "$p"
  "$ROOT/tools/pg-major-upgrade.sh" "$@" -- "${ARGS[@]}"
}

cmd_list() {
  printf '%-24s %-10s %s\n' PROJECT HOST SERVICES
  printf -- '---------------------------------------------------------------------\n'
  while IFS=$'\t' read -r name host svcs; do
    local mark=" "
    if [[ "$host" == "compose" ]]; then
      local path; path="$(reg_query compose-path "$name")"
      [[ -f "$ROOT/$path" ]] || mark="!"
    fi
    printf '%s%-23s %-10s %s\n' "$mark" "$name" "$host" "$svcs"
  done < <(reg_query list)
  printf -- '---------------------------------------------------------------------\n'
  c_dim "  ! = submodule not checked out    host=devenv → docker compose exec devenv"
}

usage() { sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

main() {
  local cmd="${1:-help}"; shift || true
  # Pass anything after `--` straight through to docker compose.
  EXTRA=()
  DEBUG=0
  local args=()
  local seen=0
  for a in "$@"; do
    if [[ $seen -eq 1 ]]; then EXTRA+=("$a")
    elif [[ "$a" == "--" ]]; then seen=1
    elif [[ "$a" == "--debug" ]]; then DEBUG=1
    else args+=("$a"); fi
  done
  set -- ${args[@]+"${args[@]}"}

  case "$cmd" in
    up)     cmd_up "$@" ;;
    down)   cmd_down "$@" ;;
    ps)     cmd_ps "$@" ;;
    build)  cmd_build "$@" ;;
    logs)   cmd_logs "$@" ;;
    exec)   cmd_exec "$@" ;;
    config) cmd_config "$@" ;;
    ports)  cmd_ports "$@" ;;
    smoke)  cmd_smoke "$@" ;;
    db-upgrade) cmd_db_upgrade "$@" ;;
    list)   cmd_list ;;
    help|-h|--help) usage ;;
    *) die "unknown command '$cmd' (try: help)" ;;
  esac
}

main "$@"
