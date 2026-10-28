#!/usr/bin/env bash
# ============================================================================
# tools/fanout.sh — shared downward-propagation engine for the fleet
#
# One safety posture for every fan-out: clone each target repo, create the
# kit branch, seed files, commit, and (only with --apply) push + open a PR.
# Called by .github/workflows/fanout.yml (every kit, one dispatch surface);
# runs locally too. Auth (`gh` / FLEET_TOKEN) needs contents:write +
# pull-requests:write AND workflows:write on the targets — every kit can seed
# .github/workflows/* files, which GitHub refuses to push without it.
#
# Guarantees:
#   - DRY RUN by default: builds the branch, prints the diffstat, no push/PR
#   - never pushes to a default branch (PR only, --force-with-lease)
#   - skips submodules whose upstream is not under a FLEET OWNER — the GitHub
#     owners listed in _data/fleet.yml `hub.owners` (bamr87 and its three
#     orgs); external mirrors like microsoft/skills are never written to
#   - additive-only seeding for the seeding kits (standardize/schema/prose):
#     never overwrites a file the target already has. The deps-latest kit is
#     the deliberate exception — converting a repo to the always-latest
#     dependency policy MEANS editing manifests and deleting lockfiles
#     (docs/DEPENDENCIES.md); the docker kit is the second — harmonizing a
#     Dockerfile MEANS editing it (docs/DOCKER.md). Every other guarantee here
#     still applies to both
#   - one bot identity: bamr87-bot <10567847+bamr87@users.noreply.github.com>
#
# Usage:
#   tools/fanout.sh --kit standardize --target <name|all> [--apply] [--upgrade]
#                   [--artifacts editorconfig,ci,conformance,agent-context,claude,claude-settings,
#                    claude-guardrails,claude-agent-auditor,issue-autopilot]
#   tools/fanout.sh --kit schema --target <name|all> [--apply]
#   tools/fanout.sh --kit prose --target <name|all> [--apply]
#   tools/fanout.sh --kit deps-latest --target <name|all> [--apply]
#   tools/fanout.sh --kit docker --target <name|all> [--apply]
#   tools/fanout.sh --kit feedback --target <name|all> [--apply] [--upgrade]
#   tools/fanout.sh --kit community --target <name|all> [--apply] [--upgrade]
#   tools/fanout.sh --kit sdlc --target <name|all> [--apply] [--upgrade]
#   tools/fanout.sh --kit spec-driven --target <name|all> [--apply] [--upgrade]
#   tools/fanout.sh --kit agent-context --target <name|all> [--apply] [--upgrade]
#   tools/fanout.sh --kit governance --target <name|all> [--apply]
#   tools/fanout.sh --kit backlog --target <name> [--apply]   (env from tools/backlog_fanout.py)
#
#   community takes --artifacts too (default: everything): pr-template,
#   issue-forms,codeowners,dependabot,contributing,security,coc. Repos under an
#   owner with a `.github` repo inherit all but codeowners and dependabot
#   (templates/community/README.md), so bamr87 repos usually take just those two.
#
# Stacking mode (environment, all optional — the defaults are the behaviour above):
#   FANOUT_BASE_BRANCH=<branch>  clone that branch when the repo has it (else the
#                                default branch) so the kit lands on top of it
#   FANOUT_BRANCH=<branch>       push to that branch instead of the kit's own
#   FANOUT_PR_APPEND=1           when an open PR already has that head, append a
#                                "## <kit title>" section to its body instead of
#                                opening another PR (FANOUT_PR_TITLE retitles it)
#   FANOUT_PR_DRAFT=1            open new PRs as drafts
#   FANOUT_SUBMODULES_ONLY=1     `--target all` means the checked-out submodules
#                                only — not the registry rows without a checkout
#                                (the zer0-mistakes mirror, the .github defaults
#                                repo, the SCHEMA kit source, forks), which take a
#                                kit only when named explicitly
#   Together they turn N kit PRs per repo into ONE alignment PR per repo with one
#   commit per kit — what the 2026-10-20 fleet alignment used on chore/root-tidy.
#
#   community / sdlc / spec-driven / agent-context seed the templates/ kits of
#   the same name, additive-only: a missing file is seeded, an unmodified
#   machine seed is reported (or refreshed with --upgrade), and a hand-modified
#   file is never touched. spec-driven seeds both consumption modes: the
#   by-reference files (tools/fleet-kit.sh, the spec-gate.yml caller) and the
#   vendored tools; the Claude Code plugin half is enabled per repo in
#   .claude/settings.json (templates/spec-driven/README.md). sdlc follows decision D4 (AGENTS.md canonical,
#   CLAUDE.md a `@AGENTS.md` pointer) and pins its release-please caller to
#   the hub's current major tag (RP_PIN). agent-context is the standardize
#   kit's agent-context artifacts as a kit of its own.
#
# Kits:
#   standardize  branch chore/standardize-baseline; artifacts (default
#                editorconfig,ci):
#                  editorconfig    copy the hub's .editorconfig
#                  ci              templates/standard-ci/ci.yml caller
#                  conformance     templates/conformance/conformance.yml caller
#                                  (in-repo Universal Project Standard gate)
#                  agent-context   templates/agent-context/CLAUDE.template.md,
#                                  only when the repo has NO agent-context file
#                  claude          templates/agent-context/claude.yml
#                                  (@claude mention workflow, OAuth-first)
#                  claude-settings templates/agent-context/settings.template.json
#                                  → .claude/settings.json (minimal read-only
#                                  permissions baseline)
#                  claude-guardrails      quarantine.template.md →
#                                  .claude/skills/_shared/quarantine.md (the
#                                  canonical shared guardrails doc; FF-0021)
#                  claude-agent-auditor   agent-auditor.template.md →
#                                  .claude/agents/agent-auditor.md, only when
#                                  no auditor-role agent exists (FF-0020)
#                  issue-autopilot templates/issue-autopilot/ → the canonical
#                                  issue-triage ENGINE (scripts/issues/*.py) +
#                                  the issue-triage skill and triager/resolver/
#                                  verifier agent skeletons (FF-0018). NEVER
#                                  writes .issues/config.yml or budget.yml —
#                                  engine in the kit, policy in the repo
#                The three claude-* .claude artifacts and issue-autopilot are
#                OPT-IN (never in the default set); other hooks/skills/commands/
#                agents stay repo-local and never fan out.
#                Seeded agent-context/claude files carry a `kit: agent-context
#                vX.Y.Z` stamp (from templates/agent-context/VERSION).
#   schema       branch chore/schema-adoption; delegates to
#                tools/seed-schema.sh (SCHEMA.md contracts + linter + CI)
#   prose        branch style/markdown-oneline; vendors the Liquid-safe
#                tools/unwrap-prose.py, seeds the markdown-oneline CI gate,
#                and does a one-time unwrap of wrapped prose
#                (SCHEMA.md/CHANGELOG.md skipped)
#   feedback     branch feat/page-feedback; vendors the universal feedback
#                widget (templates/feedback: fleet-feedback.js + capture.js),
#                seeds the stack's adapter and the no-JS issue form, and — under
#                --apply — CREATES THE LABELS the taxonomy applies. That last
#                step is the one place a kit writes to a target outside its PR,
#                and it is deliberate: GitHub silently drops unknown labels from
#                a prefilled issue URL, so a widget seeded without them files
#                unlabelled issues that never enter the issue pipeline. Mounting
#                the element stays a human one-liner (the PR body carries it) —
#                every app shell is hand-written and the fan-out is additive.
#                zer0-mistakes theme consumers are detected and told to set
#                `page_feedback.enabled: true` instead: the theme already ships
#                the widget, it is just switched off.
#   deps-latest  branch chore/deps-latest; converts the repo to the fleet's
#                ALWAYS-LATEST dependency policy via tools/unpin-deps.sh —
#                strips exact pins (package.json/requirements*.txt/Gemfile),
#                deletes + gitignores lockfiles, npm ci → npm install,
#                lockfile-keyed caches removed, action tags floated to @major
#                (_data/fleet.yml `dependencies:`, docs/DEPENDENCIES.md)
#   docker       branch chore/docker-harmonize; brings a repo's Dockerfiles and
#                compose files to the fleet standard via tools/docker_harmonize.py —
#                image versions from _data/fleet.yml `images:` (variant kept, never
#                lowered, deliberate pins respected), Postgres 18 data-mount, ports
#                loopback-bound + env-overridable, no container_name, 127.0.0.1
#                healthchecks, optional env_file. Like deps-latest it EDITS existing
#                files — that is its purpose — and is idempotent (docs/DOCKER.md)
#   verify       branch test/agent-verification; the AGENT VERIFICATION kit
#                (templates/verify/, docs/VERIFICATION.md): features/
#                features.yml scaffold (only when the repo has NO feature
#                index of any shape), verify/verify.yml run config, a smoke
#                user scenario, the Playwright runner + MCP config, the
#                verify.yml caller of the reusable fleet-verify.yml, and the
#                repo-local verify-feature skill + verifier agent (dedicated
#                kit artifacts — the sanctioned exception to ".claude/ never
#                fans out"). runner.mjs and verify.yml are upgradeable
#                machine seeds (archive/<file>-<ver>.yml).
#   backlog      branch backlog/<item-id> (FANOUT_BRANCH); ONE hub backlog
#                item per call, driven by tools/backlog_fanout.py — seeds
#                FANOUT_BACKLOG_FILE at FANOUT_BACKLOG_PATH, PR title/body from
#                FANOUT_PR_TITLE/FANOUT_BACKLOG_BODY; with FANOUT_PR_UPDATE=1 an
#                open PR on the branch is edited instead of duplicated
#                (docs/BACKLOG-FANOUT.md)
#   governance   branch docs/feature-catalog; the GOVERNANCE kit
#                (templates/governance/, specs/WORK.md UPS-WORK-15/16):
#                docs/constitution.md (only when neither it nor CONSTITUTION.md
#                exists), the docs/amendments/ log (README, 0000 template, 0001
#                ratification record — each only when absent), a features/
#                features.yml scaffold (only when the repo has no catalog), then
#                tags untagged PRD requirement bullets FRn/NFRn and regenerates
#                the PRD "Feature catalog" block (tools/governance_lint.py
#                prd-ids / prd-sync — the block is generated, like the README
#                AUTO span). Seeds carry TODO: lines and the TODO-001 placeholder:
#                tools/governance_lint.py check fails until a human or agent
#                grounds them in the repo, so the PR is a starting point, not
#                a finished catalog.
#   site-quality branch ci/site-quality; the SITE QUALITY kit
#                (templates/site-quality/, specs/QUALITY.md "Site quality"):
#                the .github/workflows/site-quality.yml caller of the reusable
#                site-quality.yml (pinned @v2; Lighthouse CI + axe-core at
#                390/1366 px + pa11y contrast against a fresh-theme build) and
#                a report-only .github/site-quality.yml config (only when
#                absent). Jekyll repos only (a root _config.yml); anything
#                else is skipped. The caller is an upgradeable machine seed.
#
# --upgrade (every templated artifact, not just claude.yml):
#   Each kit dir carries a VERSION and an archive/ of the shapes it has seeded
#   over time. A target's existing file is refreshed ONLY when it is
#   byte-identical to the current template or to one of those archived shapes —
#   proof it was machine-seeded and never touched. Anything else is treated as
#   hand-modified and left alone, stamp or no stamp.
#
#   Keeping archive/ current is therefore load-bearing: SNAPSHOT THE OUTGOING
#   SHAPE INTO archive/ BEFORE editing a template. Skip that and every deployed
#   copy reads as hand-modified, so --upgrade silently stops reaching the fleet
#   — which is exactly how templates/prose/ sat two major action versions BEHIND
#   its own 30 deployed copies (fixed in prose kit 0.2.0). The reverse failure
#   is worse: re-seeding from a stale template downgrades the fleet.
# ============================================================================
set -euo pipefail

HUB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOT_NAME="bamr87-bot"
BOT_EMAIL="10567847+bamr87@users.noreply.github.com"

KIT="" TARGET="" ARTIFACTS="editorconfig,ci" APPLY=0 UPGRADE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kit)       KIT="${2:?--kit needs a value}"; shift ;;
    --target)    TARGET="${2:?--target needs a value}"; shift ;;
    --artifacts) ARTIFACTS="${2:?--artifacts needs a value}"; shift ;;
    --apply)     APPLY=1 ;;
    --upgrade)   UPGRADE=1 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

kit_version() {  # $1 = kit dir under templates/
  local v="$HUB/templates/$1/VERSION"
  [[ -f "$v" ]] && awk '/^version:/{print $2; exit}' "$v" || echo "0.0.0"
}

# Kit version stamped into seeded agent-context files (see the VERSION file).
AC_VERSION="$(kit_version agent-context)"
PROSE_VERSION="$(kit_version prose)"
CI_VERSION="$(kit_version standard-ci)"
CONF_VERSION="$(kit_version conformance)"
VERIFY_VERSION="$(kit_version verify)"
FB_VERSION="$(kit_version feedback)"
IA_VERSION="$(kit_version issue-autopilot)"
ELK_VERSION="$(kit_version elk)"
SQ_VERSION="$(kit_version site-quality)"
COMM_VERSION="$(kit_version community)"
SDLC_VERSION="$(kit_version sdlc)"
SD_VERSION="$(kit_version spec-driven)"
GOV_VERSION="$(kit_version governance)"
# Major tag the sdlc release caller pins. The hub's reusable
# release-please.yml first shipped in v2 (it is absent at v1), so @v1 would
# point a caller at a workflow that does not exist. Bump with the hub major.
RP_PIN="v2"

# Fleet owners (_data/fleet.yml `hub.owners`): the GitHub owners whose repos
# this engine may write to. Anything else is an external mirror.
FLEET_OWNERS="$("${PYTHON:-python3}" - "$HUB" <<'PY' 2>/dev/null || echo bamr87
import sys
try:
    import yaml
    d = yaml.safe_load(open(f"{sys.argv[1]}/_data/fleet.yml")) or {}
    print(" ".join((d.get("hub") or {}).get("owners") or ["bamr87"]))
except Exception:
    print("bamr87")
PY
)"
owner_of_url() {  # github.com/<owner>/<repo>(.git) or github.com:<owner>/<repo> → owner
  local u="${1%.git}"; u="${u#*github.com/}"; u="${u#*github.com:}"; echo "${u%%/*}"
}
is_fleet_owner() { local o; for o in $FLEET_OWNERS; do [[ "$1" == "$o" ]] && return 0; done; return 1; }

# Render a kit template exactly as seeding would, so an on-disk copy can be
# compared byte-for-byte against it.
render_kit_template() {  # $1 template, $2 repo name, $3 default branch, $4 kit version
  sed -e "s/__PROJECT_NAME__/${2}/g" \
      -e "s/__DEFAULT_BRANCH__/${3}/g" \
      -e "s/__KIT_VERSION__/${4}/g" "$1"
}

# True when the on-disk file is byte-identical to some ARCHIVED machine-seeded
# shape of its template — i.e. it was seeded by a previous kit version and never
# touched, so --upgrade may replace it. Hand-modified copies never match and are
# always left alone. Archived shapes live beside the template as
# archive/<template-basename>-<version>[-<variant>].yml.
machine_seeded() {  # $1 file, $2 template, $3 repo name, $4 default branch, $5 version
  local f="$1" tpl="$2" dir base ext cand tmp
  MATCHED_ARCHIVE=""
  # Extension-derived, not hardcoded .yml: the issue-autopilot kit archives .py
  # engine shapes. For a .yml template this is byte-for-byte the old behaviour.
  dir="$(dirname "$tpl")"; ext="${tpl##*.}"; base="$(basename "$tpl" ".$ext")"
  tmp="$(mktemp)"
  for cand in "$dir/archive/$base"-*."$ext"; do
    [[ -f "$cand" ]] || continue
    render_kit_template "$cand" "$3" "$4" "$5" > "$tmp"
    if cmp -s "$f" "$tmp"; then rm -f "$tmp"; MATCHED_ARCHIVE="$cand"; return 0; fi
  done
  rm -f "$tmp"
  return 1
}

# The version an on-disk seed is AT, for the dry-run report (FF-0017): its
# `# kit: <kit> vX.Y.Z` stamp when it has one, else the version in the name of
# the archived shape it matched (archive/<base>-<X.Y.Z>[-variant].<ext>).
seed_version() {  # $1 file, $2 matched archive (may be empty)
  local v
  v="$(sed -n 's/^# kit: [a-z-]* v//p' "$1" | head -1)"
  if [[ -z "$v" && -n "$2" ]]; then
    v="$(basename "$2" | grep -Eo -- '-[0-9]+\.[0-9]+\.[0-9]+' | head -1)"; v="${v#-}"
  fi
  echo "${v:-unknown}"
}

# Seed one templated artifact, or report/refresh an existing copy.
# This is the single upgrade path for EVERY kit artifact: previously only
# claude.yml could be upgraded, which is how the prose kit drifted two major
# action versions behind the fleet unnoticed. Despite the name it is not
# workflow-specific — machine_seeded() derives the archive extension from the
# template, so .py engines and .md skeletons ride the same path.
seed_workflow_artifact() {  # $1 label, $2 dest, $3 template, $4 name, $5 branch, $6 version
  local label="$1" dest="$2" tpl="$3" name="$4" def="$5" ver="$6" stamp
  if [[ ! -f "$dest" ]]; then
    mkdir -p "$(dirname "$dest")"
    render_kit_template "$tpl" "$name" "$def" "$ver" > "$dest"
    echo "${label}: seeded (kit v${ver})"
  elif cmp -s "$dest" <(render_kit_template "$tpl" "$name" "$def" "$ver"); then
    echo "${label}: current (kit v${ver})"
  elif machine_seeded "$dest" "$tpl" "$name" "$def" "$ver"; then
    if [[ "$UPGRADE" -eq 1 ]]; then
      render_kit_template "$tpl" "$name" "$def" "$ver" > "$dest"
      echo "${label}: upgraded machine seed -> kit v${ver}"
    else
      echo "${label}: upgradeable machine seed (v$(seed_version "$dest" "$MATCHED_ARCHIVE") -> latest kit v${ver}; rerun with --upgrade)"
    fi
  else
    stamp="$(sed -n 's/^# kit: [a-z-]* v//p' "$dest" | head -1)"
    echo "${label}: hand-modified — left alone (stamp: ${stamp:-none})"
  fi
}

case "$KIT" in
  standardize|schema|prose|deps-latest|docker|feedback|elk|verify|site-quality|community|sdlc|spec-driven|agent-context|governance|backlog) ;;
  *) echo "usage: tools/fanout.sh --kit <standardize|schema|prose|deps-latest|docker|feedback|elk|verify|site-quality|community|sdlc|spec-driven|agent-context|governance|backlog> --target <name|all> [--artifacts csv] [--apply]" >&2
     exit 2 ;;
esac
[[ -n "$TARGET" ]] || { echo "--target is required (submodule name, or 'all')" >&2; exit 2; }

case "$KIT" in
  standardize)
    BRANCH="chore/standardize-baseline"
    COMMIT_MSG="chore: adopt standardization baseline (${ARTIFACTS})"
    PR_TITLE="chore: adopt standardization baseline"
    PR_BODY="Automated by bamr87 fanout.yml (kit standardize, tools/fanout.sh): seeds the baseline artifacts (${ARTIFACTS}). Additive-only — nothing the repo already has is overwritten. See bamr87/bamr87 docs/STANDARDS.md."
    ;;
  schema)
    BRANCH="chore/schema-adoption"
    COMMIT_MSG="docs: adopt Pyramid Schema (SCHEMA.md contracts + linter + CI)"
    PR_TITLE="docs: adopt Pyramid Schema structural contracts"
    PR_BODY="$(printf 'Automated by bamr87 fanout.yml (kit schema): seeds SCHEMA.md contracts in every directory, the vendored schema_lint.py, a schema-check CI gate, and the agent protocol in CLAUDE.md.\n\nScaffold purposes are TODO until the agent/human pass fills them (dispatch fanout.yml with kit=schema and agent_fill, or edit by hand). See bamr87/bamr87 docs/SCHEMA-FRAMEWORK.md.')"
    ;;
  prose)
    BRANCH="style/markdown-oneline"
    COMMIT_MSG="style(markdown): one paragraph per line + CI enforcement"
    PR_TITLE="style(markdown): enforce one paragraph per line"
    PR_BODY="Automated by bamr87 prose-fanout (tools/fanout.sh): unwraps soft-wrapped markdown prose so each paragraph is a single line — Liquid/HTML/tables/code/front-matter left byte-for-byte, and SCHEMA.md/CHANGELOG.md skipped. Also vendors tools/unwrap-prose.py and seeds a markdown-oneline CI check. Additive-only. See bamr87/bamr87."
    ;;
  feedback)
    BRANCH="feat/page-feedback"
    COMMIT_MSG="feat(feedback): adopt the universal page-feedback widget (kit v${FB_VERSION})"
    PR_TITLE="feat(feedback): universal \"Improve this page\" → GitHub issue widget"
    PR_BODY="$(printf 'Automated by bamr87 fanout.yml (tools/fanout.sh --kit feedback): vendors the universal feedback widget so a reader can file a well-formed issue against this repo from any page — request type, description, page context, environment, and the console/error lines that led up to the report.\n\nSeeded (additive — nothing existing is overwritten):\n- the widget + the early capture buffer, vendored into the static assets of this stack\n- `.github/ISSUE_TEMPLATE/page_feedback.yml`, the no-JS twin carrying the same sections\n- the adapter for the detected stack, ready to mount\n\n**One human line is left**: mount the adapter in the shell — the fan-out log names the exact line, and `templates/feedback/README.md` has the detail. The fan-out never edits a hand-written shell.\n\nIssues filed this way carry the `fleet-feedback` marker comment and labels from the fleet taxonomy, so they enter the three-tier issue pipeline on the next scan. Spec: bamr87/bamr87 specs/FEEDBACK.md (UPS-FB).')"
    ;;
  elk)
    BRANCH="feat/fleet-logging"
    COMMIT_MSG="feat(logging): adopt the fleet log plane (kit v${ELK_VERSION})"
    PR_TITLE="feat(logging): structured logs + fleet log shipping"
    PR_BODY="$(printf 'Automated by bamr87 (tools/fanout.sh --kit elk): adopts the fleet LOG PLANE, so this repo'"'"'s logs are searchable alongside every other repo'"'"'s instead of only readable one container at a time.\n\nSeeded (additive — nothing existing is overwritten):\n- `filebeat.fleet.yml`, the fleet shipper config, vendored byte-for-byte from the hub\n- `compose.labels.yml`, the `com.bamr87.fleet.*` labels + json-file rotation (UPS-OPS-17)\n- `compose.elk.yml`, a standalone single-node Elasticsearch + Kibana for a clone OUTSIDE the hub\n- the UPS-OPS-10 JSON logging adapter for the detected stack, with the UPS-OPS-12 redaction attached\n\n**One human line is left**: add the `include:` (or the four per-service lines) to docker-compose.yml — the fan-out log names it exactly, and `templates/elk/README.md` has the detail. The fan-out never edits a hand-written compose file.\n\nThe labels ARE the opt-in: the hub'"'"'s Filebeat autodiscovers on them and ignores every container without them, so nothing central changes. Spec: bamr87/bamr87 specs/OPERATIONS.md (UPS-OPS-10/12/17/18), doc docs/OBSERVABILITY.md.')"
    ;;
  deps-latest)
    BRANCH="chore/deps-latest"
    COMMIT_MSG="build(deps): adopt fleet always-latest dependency policy"
    PR_TITLE="build(deps): always-latest dependencies — drop pins and lockfiles"
    PR_BODY="Automated by bamr87 fanout.yml (tools/fanout.sh --kit deps-latest): adopts the fleet's ALWAYS-LATEST dependency policy — strips exact version pins from package.json/requirements*.txt/Gemfile, deletes and gitignores lockfiles, floats GitHub Actions on their major tags, and adapts CI installs (npm ci → npm install; lockfile-keyed caches removed). Every install now resolves the newest published versions; breakage surfaces in CI and is triaged by the hub's daily fleet-pulse loop. Follow-ups the script won't automate (pyproject/poetry/Pipfile tables, hash-pinned requirements, npm overrides) are listed in the run log. See bamr87/bamr87 docs/DEPENDENCIES.md."
    ;;
  docker)
    BRANCH="chore/docker-harmonize"
    COMMIT_MSG="build(docker): harmonize Docker configuration to the fleet standard"
    PR_TITLE="build(docker): harmonize Docker configuration to the fleet standard"
    PR_BODY="$(printf 'Automated by bamr87 fanout.yml (tools/fanout.sh --kit docker): brings this repo'"'"'s Dockerfiles and compose files to the fleet standard. Image versions come from one registry (bamr87/bamr87 `_data/fleet.yml` `images:`) — the variant (-alpine, -slim) is kept, a version is never lowered, and anything you marked deliberately pinned (a comment containing "pinned", "bump deliberately", "do not bump" or "fleet-pin") is left alone. Also: published ports become `127.0.0.1:${VAR:-<same port>}:<target>` (defaults unchanged, so nothing moves unless you set the variable), env values that hardcode a host port follow that variable, `container_name` is dropped unless a script references it, healthchecks probe 127.0.0.1 instead of localhost, a missing `.env` no longer stops `compose` from parsing, and the obsolete `version:` key goes.\n\n**A Postgres major bump orphans existing local volumes** — the new server refuses data written by an older major, and Postgres 18 also moved its data directory (the mount is rewritten for you). Dev data is disposable (`docker compose down -v`), or `pg_dumpall` first; `tools/dash dev db-upgrade` in the hub automates the dump/restore. Pin the image with a comment to opt out.\n\nReport-only items the kit does not auto-fix (root user, no HEALTHCHECK, no .dockerignore, single-stage builds) are listed in the run log. Idempotent: re-running on a converted repo is a no-op. See bamr87/bamr87 docs/DOCKER.md and specs/REPOSITORY.md (UPS-REPO-34..39).')"
    ;;
  verify)
    BRANCH="test/agent-verification"
    COMMIT_MSG="test: adopt the agent verification kit (feature index + user scenarios + evidence)"
    PR_TITLE="test: adopt the agent verification kit"
    PR_BODY="$(printf 'Automated by bamr87 fanout.yml (tools/fanout.sh --kit verify): seeds the fleet AGENT VERIFICATION standard — a feature index (features/features.yml, schema features/v1) every agent reads for what this product does and what proves it; verify/verify.yml (how to run the app like a user); a smoke user scenario + the Playwright runner (verify/runner.mjs → test/evidence/<id>/ screenshots + report.json); the Playwright MCP config; a thin verify.yml caller of the reusable fleet-verify.yml (scenarios on every PR, an OAuth Claude Code pass driving the live app on `verify`-labelled PRs — advisory until gate: true); and the repo-local verify-feature skill + verifier agent.\n\nAdditive-only — nothing the repo already has is overwritten. After merge: fill verify/verify.yml `app:` for this stack, `npm i -D @playwright/test yaml && npx playwright install --with-deps chromium`, replace the TODO feature entry, create the `verify` and `skip-evidence` labels. Coverage is graded fleet-wide at bamr87.github.io/bamr87/features/. See bamr87/bamr87 docs/VERIFICATION.md.')"
    ;;
  site-quality)
    BRANCH="ci/site-quality"
    COMMIT_MSG="ci: adopt the site-quality kit (Lighthouse CI + axe-core + pa11y contrast)"
    PR_TITLE="ci: adopt the site-quality kit"
    PR_BODY="$(printf 'Automated by bamr87 site-quality fan-out (tools/fanout.sh --kit site-quality): seeds the fleet SITE QUALITY standard — `.github/workflows/site-quality.yml`, a thin caller of the hub'"'"'s reusable site-quality.yml pinned `@v2` (`v1` predates it), which builds this Jekyll site against a FRESH theme (remote_theme resolved to a commit SHA, recorded in the job summary), serves `_site`, and runs Lighthouse CI, axe-core at 390 px and 1366 px, and pa11y contrast; and `.github/site-quality.yml`, this repo'"'"'s config (validated against templates/site-quality/site-quality.schema.json).\n\nReport-only as seeded: the config sets no budgets, no axe fail_on and no contrast max, so no scan finding fails the job. It still fails if the config is invalid, the site does not build, or the scan cannot run. Read the first run'"'"'s summary, then tighten one gate at a time; known issues go in the allowlist with rule, selector and/or page, reason, issue link and a quoted until date. Additive-only — an existing .github/site-quality.yml is never overwritten. See bamr87/bamr87 templates/site-quality/README.md and specs/QUALITY.md "Site quality".')"
    ;;
  community)
    BRANCH="chore/community-kit"
    COMMIT_MSG="chore(community): adopt the community kit (kit v${COMM_VERSION})"
    PR_TITLE="chore(community): adopt the community kit"
    PR_BODY="$(printf 'Automated by bamr87 (tools/fanout.sh --kit community): seeds the fleet COMMUNITY kit files this repo is missing: the PR template with the fleet Definition of Done (UPS-WORK-03), the issue forms (UPS-REPO-18), CODEOWNERS, dependabot.yml, CONTRIBUTING.md, SECURITY.md (7-day window, UPS-REPO-14) and CODE_OF_CONDUCT.md.\n\nAdditive-only: an existing file is never overwritten, and a hand-modified one is left alone. labels.yml is applied by label-sync, not copied. A repo-level copy overrides the owner .github default; it may add gates but must keep every DoD box. See bamr87/bamr87 templates/community/README.md.')"
    ;;
  sdlc)
    BRANCH="chore/sdlc-kit"
    COMMIT_MSG="chore(sdlc): adopt the sdlc kit (kit v${SDLC_VERSION})"
    PR_TITLE="chore(sdlc): adopt the sdlc kit"
    PR_BODY="$(printf 'Automated by bamr87 (tools/fanout.sh --kit sdlc): seeds the fleet SDLC kit files this repo is missing: `.github/sdlc.yml` (schema sdlc/v1), `AGENTS.md` as the canonical agent file with `CLAUDE.md` a `@AGENTS.md` pointer (decision D4), `CHANGELOG.md`, `docs/README.md`, the ADR log in `docs/adr/` (D2), and the release-please caller `.github/workflows/release.yml` pinned to the hub @%s, with a release-please config picked by stack (D5).\n\nAdditive-only: an existing CHANGELOG.md, AGENTS.md, CLAUDE.md, ADR log or release config is never overwritten. **Before merge**: fill every `TODO:` line in AGENTS.md (UPS-AGENT-07), check `type` and `release.type` in .github/sdlc.yml, and if CLAUDE.md was already hand-written, move its rules into AGENTS.md and replace it with the pointer. See bamr87/bamr87 templates/sdlc/README.md.' "$RP_PIN")"
    ;;
  spec-driven)
    BRANCH="chore/spec-driven-kit"
    COMMIT_MSG="chore(spec-driven): adopt the spec-driven kit (kit v${SD_VERSION})"
    PR_TITLE="chore(spec-driven): adopt the spec-driven kit"
    PR_BODY="$(printf 'Automated by bamr87 (tools/fanout.sh --kit spec-driven): seeds the spec-driven kit — the by-reference half (tools/fleet-kit.sh, the resolver `make lint-specs` runs the hub tools through, and the .github/workflows/spec-gate.yml caller of the reusable fleet spec gate) plus the vendored tools for repos that keep local copies (tools/spec_validator.py, backlog_lint.py, next_backlog_id.py, pick_backlog_item.py and hooks/gate-check.sh; UPS-WORK-07 byte-identity files), and specs/_template/, BACKLOG.md and docs/constitution.md only where absent.\n\nAdditive-only: a hand-modified copy is left alone (pre-kit copies matching the archive are upgradeable with --upgrade). **Before merge**: declare `modules: { spec_driven: true }` and `backlog: { mode: file, file: BACKLOG.md }` in .github/sdlc.yml; enable the `spec-driven@bamr87` Claude Code plugin in .claude/settings.json; and either keep the seeded caller or move its `uses:` job into ci.yml so the other jobs can `needs:` it. See bamr87/bamr87 templates/spec-driven/README.md and docs/SPEC-DRIVEN.md.')"
    ;;
  governance)
    BRANCH="docs/feature-catalog"
    COMMIT_MSG="docs: add feature catalog, constitution and amendments; link PRD (governance kit v${GOV_VERSION})"
    PR_TITLE="docs: add feature catalog, constitution and amendments; link PRD"
    PR_BODY="$(printf 'Automated by bamr87 (tools/fanout.sh --kit governance): seeds what this repo is missing of the fleet GOVERNANCE kit: docs/constitution.md, the docs/amendments/ log with the 0001 ratification record, and a features/features.yml catalog (features/v1); tags PRD requirement bullets FRn/NFRn and regenerates the PRD Feature catalog block that links every feature id.\n\nAdditive-only: an existing constitution, amendment record or catalog is never overwritten. **Before merge**: replace every TODO: line and the TODO-001 placeholder with facts from this repo (unknown = TBD), give each feature `status` and `prd:` refs, link the constitution from AGENTS.md, and run `python3 <hub>/tools/governance_lint.py check .` until clean. Merging ratifies amendment 0001. See bamr87/bamr87 templates/governance/README.md.')"
    ;;
  agent-context)
    # Same artifacts the standardize kit seeds for agent context; the kit
    # default replaces the standardize default (editorconfig,ci).
    [[ "$ARTIFACTS" == "editorconfig,ci" ]] && ARTIFACTS="agent-context,claude,claude-settings,claude-guardrails,claude-agent-auditor"
    BRANCH="chore/agent-context-kit"
    COMMIT_MSG="chore(agents): adopt the agent-context kit (kit v${AC_VERSION}; ${ARTIFACTS})"
    PR_TITLE="chore(agents): adopt the agent-context kit"
    PR_BODY="Automated by bamr87 (tools/fanout.sh --kit agent-context): seeds the agent-context kit artifacts (${ARTIFACTS}). Additive-only: CLAUDE.md is seeded only when the repo has no agent file at all (AGENTS.md, CLAUDE.md, copilot-instructions, .cursorrules), and a hand-modified workflow is left alone. See bamr87/bamr87 templates/agent-context/."
    ;;
  backlog)
    # Driven by tools/backlog_fanout.py (docs/BACKLOG-FANOUT.md): one item per
    # call, everything item-specific arrives in FANOUT_BACKLOG_* env vars.
    : "${FANOUT_BRANCH:?backlog kit needs FANOUT_BRANCH (set by tools/backlog_fanout.py)}"
    : "${FANOUT_BACKLOG_FILE:?backlog kit needs FANOUT_BACKLOG_FILE}"
    : "${FANOUT_BACKLOG_PATH:?backlog kit needs FANOUT_BACKLOG_PATH}"
    BRANCH="$FANOUT_BRANCH"
    COMMIT_MSG="chore(backlog): track ${FANOUT_BACKLOG_PATH##*/} from the hub backlog"
    PR_TITLE="${FANOUT_PR_TITLE:-chore(backlog): hub backlog item}"
    PR_BODY="${FANOUT_BACKLOG_BODY:-Automated by bamr87 backlog-fanout (tools/fanout.sh --kit backlog). See bamr87/bamr87 docs/BACKLOG-FANOUT.md.}"
    ;;
esac
# Stacking mode: one branch for every kit (see the header).
[[ -n "${FANOUT_BRANCH:-}" ]] && BRANCH="$FANOUT_BRANCH"

seed_standardize() {
  # cwd = target clone; $1 = repo name, $2 = default branch
  local name="$1" def="$2"
  case ",$ARTIFACTS," in *,editorconfig,*)
    [[ -f .editorconfig ]] || cp "$HUB/.editorconfig" .editorconfig ;;
  esac
  case ",$ARTIFACTS," in *,ci,*)
    seed_workflow_artifact "ci.yml" .github/workflows/ci.yml \
      "$HUB/templates/standard-ci/ci.yml" "$name" "$def" "$CI_VERSION" ;;
  esac
  case ",$ARTIFACTS," in *,conformance,*)
    seed_workflow_artifact "conformance.yml" .github/workflows/conformance.yml \
      "$HUB/templates/conformance/conformance.yml" "$name" "$def" "$CONF_VERSION" ;;
  esac
  case ",$ARTIFACTS," in *,agent-context,*)
    if [[ ! -f CLAUDE.md && ! -f AGENTS.md && ! -f .github/copilot-instructions.md && ! -f .cursorrules ]]; then
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__DEFAULT_BRANCH__/${def}/g" \
          -e "s/__KIT_VERSION__/${AC_VERSION}/g" \
        "$HUB/templates/agent-context/CLAUDE.template.md" > CLAUDE.md
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude,*)
    seed_workflow_artifact "claude.yml" .github/workflows/claude.yml \
      "$HUB/templates/agent-context/claude.yml" "$name" "$def" "$AC_VERSION" ;;
  esac
  case ",$ARTIFACTS," in *,claude-settings,*)
    if [[ ! -f .claude/settings.json ]]; then
      mkdir -p .claude
      cp "$HUB/templates/agent-context/settings.template.json" .claude/settings.json
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude-guardrails,*)
    if [[ ! -f .claude/skills/_shared/quarantine.md ]]; then
      mkdir -p .claude/skills/_shared
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__KIT_VERSION__/${AC_VERSION}/g" \
        "$HUB/templates/agent-context/quarantine.template.md" > .claude/skills/_shared/quarantine.md
    fi ;;
  esac
  case ",$ARTIFACTS," in *,claude-agent-auditor,*)
    # Skip when ANY auditor-role agent exists (hand-authored auditors are theirs).
    if [[ ! -f .claude/agents/agent-auditor.md && ! -f .claude/agents/agent-reviewer.md ]]; then
      mkdir -p .claude/agents
      sed -e "s/__PROJECT_NAME__/${name}/g" -e "s/__KIT_VERSION__/${AC_VERSION}/g" \
        "$HUB/templates/agent-context/agent-auditor.template.md" > .claude/agents/agent-auditor.md
    fi ;;
  esac
  case ",$ARTIFACTS," in *,issue-autopilot,*)
    seed_issue_autopilot "$name" "$def" ;;
  esac
}

# Seed the OPT-IN issue-autopilot kit: the canonical issue-triage ENGINE plus the
# skill/agent skeletons.
#
# THE POLICY BOUNDARY IS ENFORCED BY OMISSION: there is no line below that writes
# any path under .issues/. config.yml (dispositions, labels, limits,
# resolve_allow_globs, feature flags) and budget.yml are the repo's, permanently.
# A repo can take a newer engine with zero risk to its routing policy, which is
# the entire reason the engine was extracted. See templates/issue-autopilot/.
seed_issue_autopilot() {  # cwd = target clone; $1 repo name, $2 default branch
  local name="$1" def="$2" kit="$HUB/templates/issue-autopilot" f base
  # The engine + its tests. Upgradeable: archive/ holds both pre-kit fork shapes,
  # so a repo still on its own fork is converted in place rather than reported as
  # hand-modified.
  for base in triage dispatch verify_close test_verify_close test_triage_engine; do
    seed_workflow_artifact "scripts/issues/${base}.py" "scripts/issues/${base}.py" \
      "$kit/${base}.py" "$name" "$def" "$IA_VERSION"
  done
  # The skeletons. Additive-only in practice — there is no archive/ for them, so
  # --upgrade can only ever match the current shape (a no-op). A hand-authored
  # skill or agent is never touched.
  seed_workflow_artifact ".claude/skills/issue-triage/SKILL.md" \
    .claude/skills/issue-triage/SKILL.md \
    "$kit/SKILL.template.md" "$name" "$def" "$IA_VERSION"
  for f in issue-triager issue-resolver issue-verifier; do
    seed_workflow_artifact ".claude/agents/${f}.md" ".claude/agents/${f}.md" \
      "$kit/${f}.template.md" "$name" "$def" "$IA_VERSION"
  done
  # The one thing a human must still write. Say so loudly rather than seeding a
  # default policy: a wrong disposition rule routes real issues wrongly, and the
  # kit has no way to know this repo's labels, limits, or resolver boundary.
  if [[ ! -f .issues/config.yml ]]; then
    echo "issue-autopilot: NOTE — .issues/config.yml is absent and the kit never writes it."
    echo "issue-autopilot:        The engine is inert until you add one (dispositions, labels,"
    echo "issue-autopilot:        limits, resolve_allow_globs). See templates/issue-autopilot/README.md."
  fi
}

seed_prose() {
  # cwd = target clone; $1 = repo name (unused), $2 = default branch.
  # Liquid-safe: unwrap-prose.py only joins wrapped prose, so this is safe even
  # in Jekyll repos where blanket prettier would merge {% %} tags and break
  # rendering. Additive: nothing the repo already has is overwritten.
  local name="$1" def="$2"
  # 1. vendor the Liquid-safe unwrapper
  mkdir -p tools
  if [[ ! -f tools/unwrap-prose.py ]]; then
    cp "$HUB/tools/unwrap-prose.py" tools/unwrap-prose.py
  elif ! cmp -s tools/unwrap-prose.py "$HUB/tools/unwrap-prose.py"; then
    # The vendored copy is the fan-out payload — a drifted one silently changes
    # what the gate enforces. Refresh it only under --upgrade, same posture as
    # the workflow artifacts.
    if [[ "$UPGRADE" -eq 1 ]]; then
      cp "$HUB/tools/unwrap-prose.py" tools/unwrap-prose.py
      echo "unwrap-prose.py: upgraded to hub copy"
    else
      echo "unwrap-prose.py: drifted from hub copy (rerun with --upgrade to refresh)"
    fi
  fi
  # 2. seed the markdown-oneline CI gate
  seed_workflow_artifact "markdown-oneline.yml" .github/workflows/markdown-oneline.yml \
    "$HUB/templates/prose/markdown-oneline.yml" "$name" "$def" "$PROSE_VERSION"
  # 3. one-time fix: unwrap wrapped prose in every tracked markdown file, leaving
  #    lint-gated SCHEMA.md contracts and release-please CHANGELOGs untouched.
  #    Honour the repo's OWN gate excludes when it declares any: seeding with the
  #    defaults rewrote 24 machine-authored quest reports in it-journey, which
  #    exempts exactly those paths — a PR its own gate would never have asked for,
  #    against files the quest loop regenerates wrapped anyway.
  local ex pat
  ex=(--exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$')
  if [[ -f .github/workflows/markdown-oneline.yml ]] \
     && grep -q -- "--exclude '" .github/workflows/markdown-oneline.yml; then
    ex=()
    while IFS= read -r pat; do ex+=(--exclude "$pat"); done \
      < <(grep -o -- "--exclude '[^']*'" .github/workflows/markdown-oneline.yml \
          | sed "s/^--exclude '//; s/'$//")
  fi
  python3 tools/unwrap-prose.py --write "${ex[@]}" >/dev/null 2>&1 || true
}

seed_verify() {
  # cwd = target clone; $1 = repo name, $2 = default branch. Additive-only:
  # every artifact is seeded only when the repo has nothing in its place. The
  # feature index is the one artifact checked against EVERY shape the fleet
  # already uses (features/, _data/, root) — a repo with a legacy index keeps
  # it, because the hub reads legacy files as-is.
  local name="$1" def="$2" tpl="$HUB/templates/verify"
  if [[ ! -f features/features.yml && ! -f _data/features.yml && ! -f features.yml ]]; then
    mkdir -p features
    render_kit_template "$tpl/features.template.yml" "$name" "$def" "$VERIFY_VERSION" > features/features.yml
    echo "features/features.yml: seeded (kit v${VERIFY_VERSION})"
  else
    echo "feature index: present — left alone"
  fi
  mkdir -p verify/scenarios
  seed_workflow_artifact "verify/verify.yml" verify/verify.yml \
    "$tpl/verify.template.yml" "$name" "$def" "$VERIFY_VERSION"
  if ! compgen -G "verify/scenarios/*.yml" >/dev/null 2>&1 \
     && ! compgen -G "verify/scenarios/*.yaml" >/dev/null 2>&1; then
    render_kit_template "$tpl/scenario.template.yml" "$name" "$def" "$VERIFY_VERSION" > verify/scenarios/smoke-home.yml
    echo "verify/scenarios/smoke-home.yml: seeded"
  fi
  seed_workflow_artifact "verify/runner.mjs" verify/runner.mjs \
    "$tpl/runner.mjs" "$name" "$def" "$VERIFY_VERSION"
  [[ -f verify/mcp.json ]] || { cp "$tpl/mcp.json" verify/mcp.json; echo "verify/mcp.json: seeded"; }
  seed_workflow_artifact "verify.yml" .github/workflows/verify.yml \
    "$tpl/verify.yml" "$name" "$def" "$VERIFY_VERSION"
  # Dedicated kit artifacts (agent-context 0.4.0 exception): seeded only when
  # no verification skill/agent of any authorship exists.
  if [[ ! -f .claude/skills/verify-feature/SKILL.md && ! -f .github/skills/visual-evidence/SKILL.md ]]; then
    mkdir -p .claude/skills/verify-feature
    render_kit_template "$tpl/SKILL.template.md" "$name" "$def" "$VERIFY_VERSION" > .claude/skills/verify-feature/SKILL.md
    echo ".claude/skills/verify-feature/SKILL.md: seeded"
  fi
  if [[ ! -f .claude/agents/verifier.md ]]; then
    mkdir -p .claude/agents
    render_kit_template "$tpl/verifier.template.md" "$name" "$def" "$VERIFY_VERSION" > .claude/agents/verifier.md
    echo ".claude/agents/verifier.md: seeded"
  fi
}

# Vendor one kit asset. Same posture as the workflow artifacts: seed when
# absent, report when it matches, and refresh under --upgrade only when the
# on-disk copy is byte-identical to the current kit file or to an ARCHIVED one
# (proof it was machine-seeded and never touched). A hand-modified copy is left
# alone — someone made that change on purpose, and a widget silently reverted
# under them is worse than one version behind.
# Seed one BYTE-COPIED payload (no __PLACEHOLDER__ substitution) and report or
# refresh an existing copy — the untemplated twin of seed_workflow_artifact,
# with the same four states.
#
# $4/$5 default to the feedback kit's version and .js archives, which is what
# every call site used when this only had one caller. The elk kit vendors a
# .yml payload, so both are now parameters: a hardcoded version stamps the
# WRONG kit's number into the log, and a hardcoded extension means --upgrade
# silently never matches that kit's archives.
seed_vendored_asset() {  # $1 dest, $2 kit source, $3 label, [$4 version], [$5 archive ext], [$6 archive dir]
  local dest="$1" src="$2" label="$3" ver="${4:-$FB_VERSION}" ext="${5:-js}" dir base cand
  dir="${6:-$(dirname "$src")/archive}"; base="$(basename "$src")"; base="${base%".$ext"}"
  if [[ ! -f "$dest" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    echo "${label}: vendored -> ${dest} (kit v${ver})"
    return
  fi
  if cmp -s "$dest" "$src"; then echo "${label}: current (kit v${ver})"; return; fi
  for cand in "$dir/$base"-*."$ext"; do
    [[ -f "$cand" ]] || continue
    if cmp -s "$dest" "$cand"; then
      if [[ "$UPGRADE" -eq 1 ]]; then
        cp "$src" "$dest"; echo "${label}: upgraded machine seed -> kit v${ver}"
      else
        echo "${label}: upgradeable machine seed (v$(seed_version "$dest" "$cand") -> latest kit v${ver}; rerun with --upgrade)"
      fi
      return
    fi
  done
  echo "${label}: hand-modified — left alone"
}

# Where a stack keeps files it serves verbatim. Guessing wrong means the widget
# 404s at runtime with nothing in CI to catch it, so this leans on the marker
# file of each stack rather than on directory names alone.
feedback_asset_dir() {
  if   [[ -d public ]];                       then echo "public"
  elif [[ -d frontend/public ]];              then echo "frontend/public"
  elif [[ -d static/js || -d static ]];       then echo "static/js"
  elif [[ -d assets/js ]];                    then echo "assets/js"
  elif [[ -f _config.yml || -f mkdocs.yml ]]; then echo "assets/js"
  elif [[ -d app/assets/javascripts ]];       then echo "app/assets/javascripts"
  elif [[ -d media ]];                        then echo "media"
  else echo "public"
  fi
}

feedback_stack() {
  if [[ -f _config.yml ]] && grep -qs 'zer0-mistakes' _config.yml; then echo "zer0-theme"
  elif [[ -f _config.yml ]];                                          then echo "jekyll"
  elif [[ -f mkdocs.yml ]];                                           then echo "mkdocs"
  elif [[ -f manage.py ]] || compgen -G '*/settings.py' >/dev/null;   then echo "django"
  elif [[ -f config.ru && -d app/views ]];                            then echo "rails"
  elif grep -qs '"vscode"' package.json;                              then echo "ext"
  elif grep -qs '"next"' package.json frontend/package.json;          then echo "next"
  elif grep -qs '"react"' package.json frontend/package.json;         then echo "react"
  else echo "unknown"
  fi
}

# Which logging adapter this repo can actually use. Reuses feedback_stack()'s
# marker-file detection rather than repeating it — the two kits ask the same
# question ("what is this repo built out of") and a second answer would drift.
elk_adapter() {
  case "$(feedback_stack)" in
    django)                echo "django-logging.py" ;;
    rails)                 echo "rails-lograge.rb" ;;
    next|react|ext)        echo "node-pino.mjs" ;;
    mkdocs)                echo "python-logging.py" ;;
    jekyll|zer0-theme)     echo "" ;;   # a static site has no runtime to log from
    *)                     if [[ -f package.json ]]; then echo "node-pino.mjs"
                           elif compgen -G '*.py' >/dev/null || [[ -f pyproject.toml ]]; then echo "python-logging.py"
                           else echo ""; fi ;;
  esac
}

seed_elk() {
  # cwd = target clone; $1 = repo name, $2 = default branch.
  local name="$1" def="$2" kit="$HUB/templates/elk" stack adapter
  stack="$(feedback_stack)"
  echo "elk: detected stack '${stack}'"

  # The shipper config is VENDORED, not templated: every repo must ship in the
  # same shape or the shared index holds two schemas. Drift check (i) compares
  # the copies against the hub's.
  seed_vendored_asset "filebeat.fleet.yml" "$kit/filebeat.fleet.yml" "shipper config" \
    "$ELK_VERSION" "yml"

  # The compose fragments carry __PROJECT_NAME__/__KIT_VERSION__, so they ride
  # the four-state upgrade ladder like every other templated artifact.
  seed_workflow_artifact "compose.labels.yml" compose.labels.yml \
    "$kit/compose.labels.yml" "$name" "$def" "$ELK_VERSION"
  seed_workflow_artifact "compose.elk.yml" compose.elk.yml \
    "$kit/compose.elk.yml" "$name" "$def" "$ELK_VERSION"

  adapter="$(elk_adapter)"
  if [[ -n "$adapter" ]]; then
    mkdir -p .fleet/logging
    seed_workflow_artifact "logging adapter (${adapter})" ".fleet/logging/${adapter}" \
      "$kit/adapters/${adapter}" "$name" "$def" "$ELK_VERSION"
  else
    echo "logging adapter: none — '${stack}' has no runtime that emits logs"
  fi

  # The one line a human adds. Printed, never applied: this kit does not edit a
  # hand-written docker-compose.yml, for the same reason the feedback kit does
  # not edit a hand-written page shell.
  echo
  echo "  MOUNT (one human line in docker-compose.yml):"
  if [[ -f docker-compose.yml ]] || [[ -f compose.yml ]]; then
    echo "    include:"
    echo "      - path: compose.labels.yml"
    echo "    …then per service:  labels: {<<: *fleet-labels, com.bamr87.fleet.stack: ${stack}}  and  logging: *fleet-logging"
  else
    echo "    (no compose file here — the labels apply wherever this repo's containers are defined)"
  fi
  [[ -n "$adapter" ]] && echo "    …and import .fleet/logging/${adapter} where logging is configured."
  echo
}

seed_site_quality() {
  # cwd = target clone; $1 = repo name, $2 = default branch.
  local name="$1" def="$2" kit="$HUB/templates/site-quality"
  # The reusable workflow builds Jekyll (mode: build); other stacks would only
  # get a red job, so they are skipped rather than seeded.
  if [[ ! -f _config.yml ]]; then
    echo "site-quality: no _config.yml — not a Jekyll site, skipped"
    return 0
  fi
  seed_workflow_artifact "site-quality.yml" .github/workflows/site-quality.yml \
    "$kit/site-quality.yml" "$name" "$def" "$SQ_VERSION"
  # The config is the repo's own from the first edit on: seeded once, never
  # compared, never upgraded (like features/features.yml in the verify kit).
  if [[ -f .github/site-quality.yml ]]; then
    echo "site-quality config: present — left alone"
  else
    mkdir -p .github
    render_kit_template "$kit/site-quality.template.yml" "$name" "$def" "$SQ_VERSION" > .github/site-quality.yml
    echo "site-quality config: seeded report-only (kit v${SQ_VERSION})"
  fi
}

seed_feedback() {
  # cwd = target clone; $1 = repo name, $2 = default branch.
  local name="$1" def="$2" kit="$HUB/templates/feedback" stack dir
  stack="$(feedback_stack)"
  echo "feedback: detected stack '${stack}'"

  # A zer0-mistakes consumer already HAS the widget — the theme ships it, and
  # remote_theme simply cannot carry the _config.yml key that turns it on. That
  # is the whole reason it is dead on every consumer site, and vendoring a
  # second widget on top would give the page two feedback buttons.
  if [[ "$stack" == "zer0-theme" ]]; then
    if grep -qs 'page_feedback:' _config.yml; then
      echo "feedback: theme consumer — page_feedback already configured, nothing to seed"
    else
      echo "feedback: theme consumer — ADD TO _config.yml (one key, no kit needed):"
      echo "feedback:     page_feedback:"
      echo "feedback:       enabled: true"
    fi
    # The no-JS twin is still the repo's own file, and the theme does not ship it.
    if [[ ! -f .github/ISSUE_TEMPLATE/page_feedback.yml ]]; then
      mkdir -p .github/ISSUE_TEMPLATE
      cp "$kit/page_feedback.yml" .github/ISSUE_TEMPLATE/page_feedback.yml
      echo "page_feedback.yml: seeded"
    fi
    return
  fi

  dir="$(feedback_asset_dir)"
  seed_vendored_asset "$dir/fleet-feedback.js" "$kit/fleet-feedback.js" "fleet-feedback.js"
  seed_vendored_asset "$dir/fleet-feedback-capture.js" "$kit/capture.js" "capture.js"

  if [[ ! -f .github/ISSUE_TEMPLATE/page_feedback.yml ]]; then
    mkdir -p .github/ISSUE_TEMPLATE
    cp "$kit/page_feedback.yml" .github/ISSUE_TEMPLATE/page_feedback.yml
    echo "page_feedback.yml: seeded"
  fi

  # The adapter is seeded as a file and mounted by a human. Every app shell in
  # the fleet is hand-written; a machine editing one is how a fan-out breaks a
  # site it was meant to improve.
  case "$stack" in
    next|react)
      mkdir -p components
      [[ -f components/FeedbackButton.tsx ]] || cp "$kit/adapters/FeedbackButton.tsx" components/FeedbackButton.tsx
      if [[ "$stack" == "next" && ! -f components/FeedbackCapture.tsx ]]; then
        cp "$kit/adapters/nextjs.tsx" components/FeedbackCapture.tsx
      fi
      echo "feedback: MOUNT — <FeedbackButton repo=\"bamr87/${name}\" /> once in the app shell"
      # A bare `[[ ]] && echo` here would leave the branch with a non-zero exit
      # status for every non-Next repo, and seeding runs under `set -e`.
      if [[ "$stack" == "next" ]]; then
        echo "feedback: MOUNT — <FeedbackCapture /> in the <head> of app/layout.tsx"
      fi
      ;;
    jekyll|mkdocs)
      mkdir -p _includes/custom
      [[ -f _includes/custom/fleet-feedback.html ]] || cp "$kit/adapters/jekyll.html" _includes/custom/fleet-feedback.html
      echo "feedback: MOUNT — {% include custom/fleet-feedback.html %} before </body>"
      ;;
    django|rails)
      mkdir -p templates/includes
      [[ -f templates/includes/fleet-feedback.html ]] || cp "$kit/adapters/django.html" templates/includes/fleet-feedback.html
      echo "feedback: MOUNT — {% include 'includes/fleet-feedback.html' %} before </body> in base.html"
      ;;
    ext)
      echo "feedback: webview stack — mount the inline trigger with mode=\"postmessage\"; see templates/feedback/README.md"
      ;;
    *)
      echo "feedback: stack not recognised — assets vendored to ${dir}; mount <fleet-feedback repo=\"bamr87/${name}\"> by hand"
      ;;
  esac
}

# GitHub SILENTLY DROPS a label that does not exist from a prefilled issue URL:
# no error, no warning, the label is just gone and the issue never enters the
# pipeline. Creating them is therefore part of making the widget work, not a
# nicety — the one place this kit writes to a target outside its own PR, and
# only under --apply.
feedback_ensure_labels() {  # $1 = owner/repo
  local slug="$1" spec name color desc
  for spec in \
    "page-feedback|0E8A16|Filed from a page via the feedback widget" \
    "bug|D73A4A|Something is not working" \
    "feature|A2EEEF|New capability" \
    "docs|0075CA|Documentation" \
    "question|D876E3|Further information is requested" \
    "area:a11y|1D76DB|Accessibility" \
    "area:perf|1D76DB|Performance"; do
    IFS='|' read -r name color desc <<< "$spec"
    gh label create "$name" --repo "$slug" --color "$color" --description "$desc" >/dev/null 2>&1 \
      && echo "label: created ${name}" || true
  done
}

# A fan-out target is a REPO, not a working tree: run_one clones it fresh from
# GitHub and never reads projects/<name>/. The only thing .gitmodules was ever
# supplying is the upstream URL — so a fleet repo that is registered but not
# mounted as a submodule was unreachable for no reason but the lookup.
#
# That gap was not theoretical: `dash harnesses` files a standing
# `gap-not-deployable` finding for exactly this class ("the kit could close
# this, but the repo is not a submodule"), and bamr87/SCHEMA — the upstream of
# the linter this hub vendors — sat with no @claude handler and no kit for
# months because nothing could target it.
#
# The registry is the fleet's source of truth (_data/projects.yml), so it is
# the natural fallback. Every other guarantee is unchanged: still PR-only,
# still additive, still dry-run by default, still skipping upstreams outside
# github.com/bamr87.
registry_url() {
  "${PYTHON:-python3}" - "$HUB" "$1" <<'PY' 2>/dev/null
import sys
try:
    import yaml
except ImportError:
    raise SystemExit(0)
root, want = sys.argv[1], sys.argv[2]
try:
    reg = yaml.safe_load(open(f"{root}/_data/projects.yml")) or []
except OSError:
    raise SystemExit(0)
for p in reg:
    if not isinstance(p, dict):
        continue
    if p.get("name") == want or p.get("slug") == want:
        print(p.get("repo_url") or "")
        break
PY
}

# Every target for `--target all`: the submodules, plus registry entries that
# have no submodule_path and are neither archived nor externally owned.
all_targets() {
  # Submodules first (minus the ones the registry marks archived — GitHub
  # refuses pushes to an archived repo), then registry rows without a checkout.
  "${PYTHON:-python3}" - "$HUB" "$FLEET_OWNERS" "${FANOUT_SUBMODULES_ONLY:-0}" <<'PY' 2>/dev/null
import subprocess, sys
root = sys.argv[1]
paths = subprocess.run(["git", "config", "-f", f"{root}/.gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
                       capture_output=True, text=True).stdout.split()
paths = [p for i, p in enumerate(paths) if i % 2 == 1]
try:
    import yaml
    reg = yaml.safe_load(open(f"{root}/_data/projects.yml")) or []
except Exception:
    reg = []
archived = {p.get("submodule_path") for p in reg if isinstance(p, dict) and p.get("status") == "archived"}
for p in paths:
    if p not in archived:
        print(p)
if len(sys.argv) > 3 and sys.argv[3] == "1":
    raise SystemExit(0)
for p in reg:
    if not isinstance(p, dict) or p.get("submodule_path"):
        continue
    if p.get("status") == "archived":
        continue
    url = p.get("repo_url") or ""
    name = p.get("name")
    # The external-upstream guard in run_one would skip these anyway; filtering
    # here keeps `all` from printing a skip line for every mirror.
    owner = url.replace("github.com:", "github.com/").split("github.com/", 1)[-1].split("/", 1)[0]
    if name and owner in sys.argv[2].split():
        print(f"projects/{name}")
PY
}

# Seed a kit file once: written when absent, never compared or upgraded after.
seed_once() {  # $1 label, $2 dest, $3 template, $4 name, $5 branch, $6 version
  if [[ -e "$2" ]]; then echo "$1: present — left alone"; return 0; fi
  mkdir -p "$(dirname "$2")"
  render_kit_template "$3" "$4" "$5" "$6" > "$2"
  echo "$1: seeded (kit v$6)"
}

seed_community() {  # cwd = target clone; $1 repo name, $2 default branch
  local name="$1" def="$2" kit="$HUB/templates/community" f want="$ARTIFACTS" tok
  # --artifacts narrows the kit; the standardize default means "everything".
  # Tokens: pr-template issue-forms codeowners dependabot contributing security coc.
  [[ "$want" == "editorconfig,ci" ]] && want="all"
  # labels.yml is applied by label-sync, not copied (templates/community/VERSION).
  for f in .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml \
           .github/ISSUE_TEMPLATE/documentation.yml .github/ISSUE_TEMPLATE/config.yml \
           .github/pull_request_template.md .github/CODEOWNERS .github/dependabot.yml \
           CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md; do
    case "$f" in
      .github/pull_request_template.md) tok=pr-template ;;
      .github/ISSUE_TEMPLATE/*)         tok=issue-forms ;;
      .github/CODEOWNERS)               tok=codeowners ;;
      .github/dependabot.yml)           tok=dependabot ;;
      CONTRIBUTING.md)                  tok=contributing ;;
      SECURITY.md)                      tok=security ;;
      CODE_OF_CONDUCT.md)               tok=coc ;;
    esac
    if [[ "$want" != "all" ]]; then case ",$want," in *,"$tok",*) ;; *) continue ;; esac; fi
    seed_workflow_artifact "$f" "$f" "$kit/$f" "$name" "$def" "$COMM_VERSION"
  done
}

seed_sdlc() {  # cwd = target clone; $1 repo name, $2 default branch
  local name="$1" def="$2" kit="$HUB/templates/sdlc" rtype f tmp wired=1
  # release-please type by stack (decision D5); simple for everything else.
  if [[ -f package.json ]]; then rtype=node
  elif [[ -f pyproject.toml || -f setup.py ]]; then rtype=python
  elif compgen -G "*.gemspec" >/dev/null; then rtype=ruby
  else rtype=simple; fi
  if [[ -e .github/sdlc.yml ]]; then
    echo "sdlc.yml: present — left alone"
  else
    mkdir -p .github
    render_kit_template "$kit/sdlc.yml" "$name" "$def" "$SDLC_VERSION" \
      | sed -E "s/^(  type: )simple( +#)/\1${rtype}\2/" > .github/sdlc.yml
    echo "sdlc.yml: seeded (kit v${SDLC_VERSION}, release.type ${rtype})"
  fi
  # D4: AGENTS.md is canonical, CLAUDE.md a pointer. Neither is ever overwritten.
  seed_once "AGENTS.md" AGENTS.md "$kit/AGENTS.template.md" "$name" "$def" "$SDLC_VERSION"
  if [[ ! -e CLAUDE.md ]]; then
    seed_once "CLAUDE.md" CLAUDE.md "$kit/CLAUDE.template.md" "$name" "$def" "$SDLC_VERSION"
  elif grep -qx '@AGENTS.md' CLAUDE.md; then
    echo "CLAUDE.md: already imports @AGENTS.md — left alone"
  else
    echo "CLAUDE.md: hand-written, not a @AGENTS.md pointer — left alone (move its rules into AGENTS.md by hand, D4)"
  fi
  seed_once "CHANGELOG.md" CHANGELOG.md "$kit/CHANGELOG.template.md" "$name" "$def" "$SDLC_VERSION"
  seed_once "docs/README.md" docs/README.md "$kit/docs/README.template.md" "$name" "$def" "$SDLC_VERSION"
  # The ADR log is the repo's once it exists (D2): seed it only into an absent dir.
  if [[ -d docs/adr ]]; then
    echo "docs/adr: present — left alone"
  else
    for f in "$kit"/docs/adr/*.md; do
      seed_once "docs/adr/$(basename "$f")" "docs/adr/$(basename "$f")" "$f" "$name" "$def" "$SDLC_VERSION"
    done
  fi
  # Release caller, pinned to the hub's current major tag (see RP_PIN).
  tmp="$(mktemp)"
  sed "s#release-please.yml@v1#release-please.yml@${RP_PIN}#" "$kit/release/release.yml" > "$tmp"
  if [[ -e .github/workflows/release.yml ]] && ! grep -q 'release-please' .github/workflows/release.yml; then
    echo "release.yml: an unrelated .github/workflows/release.yml exists — left alone (wire release-please by hand)"
    wired=0
  else
    seed_workflow_artifact "release.yml" .github/workflows/release.yml "$tmp" "$name" "$def" "$SDLC_VERSION"
  fi
  rm -f "$tmp"
  # Config + manifest are a pair; never seed one beside a hand-made other.
  if [[ -e release-please-config.json || -e .release-please-manifest.json ]]; then
    echo "release-please config: present — left alone"
  elif [[ "$wired" -eq 0 ]]; then
    echo "release-please config: not seeded — no release-please caller was wired"
  else
    render_kit_template "$kit/release/release-please-config.${rtype}.json" "$name" "$def" "$SDLC_VERSION" > release-please-config.json
    cp "$kit/release/.release-please-manifest.json" .release-please-manifest.json
    echo "release-please config: seeded (${rtype}, manifest 0.1.0)"
  fi
  # _data/backlog.yml belongs to the opt-in content_queue module: never seeded here.
}

seed_spec_driven() {  # cwd = target clone; $1 repo name, $2 default branch
  local name="$1" def="$2" kit="$HUB/templates/spec-driven" f
  # Byte-identity files (UPS-WORK-07): vendored verbatim, upgradeable from archive/.
  for f in spec_validator backlog_lint next_backlog_id pick_backlog_item; do
    seed_vendored_asset "tools/$f.py" "$kit/tools/$f.py" "tools/$f.py" "$SD_VERSION" py "$kit/archive"
  done
  seed_vendored_asset hooks/gate-check.sh "$kit/hooks/gate-check.sh" hooks/gate-check.sh "$SD_VERSION" sh "$kit/archive"
  # By-reference half (kit 0.2.0): the resolver `make lint-specs` runs the hub's
  # tools through, and the caller of the reusable spec-gate.yml. A repo that
  # keeps its gate inside ci.yml (so other jobs can `needs:` it) deletes the
  # standalone caller after moving the `uses:` job there.
  seed_vendored_asset tools/fleet-kit.sh "$kit/fleet-kit.sh" tools/fleet-kit.sh "$SD_VERSION" sh "$kit/archive"
  seed_workflow_artifact "spec-gate.yml" .github/workflows/spec-gate.yml \
    "$kit/workflows/spec-gate.yml" "$name" "$def" "$SD_VERSION"
  chmod +x tools/*.py tools/fleet-kit.sh hooks/gate-check.sh 2>/dev/null || true
  # Templates: seeded once, then owned by the repo.
  for f in spec plan tasks; do
    seed_once "specs/_template/$f.md" "specs/_template/$f.md" "$kit/specs/_template/$f.md" "$name" "$def" "$SD_VERSION"
  done
  seed_once "BACKLOG.md" BACKLOG.md "$kit/BACKLOG.template.md" "$name" "$def" "$SD_VERSION"
  seed_once "docs/constitution.md" docs/constitution.md "$kit/constitution.template.md" "$name" "$def" "$SD_VERSION"
}

seed_governance() {  # cwd = target clone; $1 repo name, $2 default branch
  local name="$1" def="$2" kit="$HUB/templates/governance" f today
  today="$(date +%Y-%m-%d)"
  if [[ -e docs/constitution.md || -e CONSTITUTION.md ]]; then
    echo "constitution: present — left alone (conform it by hand; governance_lint.py check names the gaps)"
  else
    seed_once "docs/constitution.md" docs/constitution.md "$kit/constitution.template.md" "$name" "$def" "$GOV_VERSION"
  fi
  seed_once "docs/amendments/README.md" docs/amendments/README.md "$kit/docs/amendments/README.template.md" "$name" "$def" "$GOV_VERSION"
  seed_once "docs/amendments/0000-template.md" docs/amendments/0000-template.md "$kit/docs/amendments/0000-template.md" "$name" "$def" "$GOV_VERSION"
  if compgen -G "docs/amendments/0001-*.md" >/dev/null; then
    echo "docs/amendments/0001: present — left alone"
  else
    seed_once "docs/amendments/0001-ratify-constitution.md" docs/amendments/0001-ratify-constitution.md \
      "$kit/docs/amendments/0001-ratify-constitution.template.md" "$name" "$def" "$GOV_VERSION"
    sed -i.bak "s/__DATE__/${today}/" docs/amendments/0001-ratify-constitution.md && rm -f docs/amendments/0001-ratify-constitution.md.bak
  fi
  if [[ -e features/features.yml || -e _data/features.yml ]]; then
    echo "feature catalog: present — left alone"
  else
    seed_once "features/features.yml" features/features.yml "$HUB/templates/verify/features.template.yml" "$name" "$def" "$VERIFY_VERSION"
  fi
  "${PYTHON:-python3}" "$HUB/tools/governance_lint.py" prd-ids . --write || echo "PRD: none found — block not written"
  "${PYTHON:-python3}" "$HUB/tools/governance_lint.py" prd-sync . --write || true
  "${PYTHON:-python3}" "$HUB/tools/governance_lint.py" check . || echo "governance_lint: gaps above must be grounded by hand before merge"
}

run_one() {
  local path="$1" name sect url slug def work rc
  name="$(basename "$path")"
  sect="$(git config -f "$HUB/.gitmodules" --get-regexp '^submodule\..*\.path$' \
          | awk -v p="$path" '$2==p{print $1}' | sed 's/^submodule\.//; s/\.path$//')"
  if [[ -n "$sect" ]]; then
    url="$(git config -f "$HUB/.gitmodules" --get "submodule.${sect}.url")"
  else
    url="$(registry_url "$name")"
    if [[ -z "$url" ]]; then
      echo "skip ${name}: in neither .gitmodules nor the registry"; return 0
    fi
    echo "note ${name}: not a submodule — target resolved from the registry"
  fi
  local owner; owner="$(owner_of_url "$url")"
  if ! is_fleet_owner "$owner"; then
    echo "skip ${name}: external upstream (${url}; fleet owners: ${FLEET_OWNERS})"; return 0
  fi
  slug="${owner}/$(basename "${url%.git}")"
  work="$(mktemp -d)"
  echo "::group::${slug}"
  # Stacking mode: start from FANOUT_BASE_BRANCH when the repo has it, so the
  # kit lands as one more commit on the alignment PR; else the default branch.
  if [[ -n "${FANOUT_BASE_BRANCH:-}" ]] && gh repo clone "$slug" "$work" -- --depth=1 --branch "$FANOUT_BASE_BRANCH" >/dev/null 2>&1; then
    echo "base: ${FANOUT_BASE_BRANCH}"
  else
    rm -rf "$work"; mkdir -p "$work"   # a failed branch clone may leave a partial dir
    if ! gh repo clone "$slug" "$work" -- --depth=1 >/dev/null 2>&1; then
      echo "skip ${slug}: clone failed"; echo "::endgroup::"; rm -rf "$work"; return 0
    fi
  fi
  # gh authenticates the clone itself but not later pushes from this repo —
  # route git credentials through gh (uses GH_TOKEN in CI, keyring locally).
  git -C "$work" config credential.helper '!gh auth git-credential'
  # Seed in a subshell whose exit code we capture WITHOUT a condition context
  # (that would suppress errexit inside it), so cleanup always runs and a
  # failure is reported to the caller instead of aborting the whole script.
  set +e
  (
    set -e
    def="$(gh api "repos/${slug}" --jq .default_branch)"
    cd "$work"
    [[ "$(git rev-parse --abbrev-ref HEAD)" == "$BRANCH" ]] || git checkout -b "$BRANCH"
    case "$KIT" in
      standardize) seed_standardize "$(basename "${url%.git}")" "$def" ;;
      schema)      "$HUB/tools/seed-schema.sh" "$work" --apply --default-branch "$def" ;;
      prose)       seed_prose "$(basename "${url%.git}")" "$def" ;;
      deps-latest) "$HUB/tools/unpin-deps.sh" . ;;
      verify)      seed_verify "$(basename "${url%.git}")" "$def" ;;
      docker)      # --project keys the repo into _data/ports.yml so variable names
                   # match the fleet allocation (FREDGAR_API_PORT, not a derived one)
                   "${PYTHON:-python3}" "$HUB/tools/docker_harmonize.py" apply . --project "$name" ;;
      feedback)    seed_feedback "$(basename "${url%.git}")" "$def"
                   [[ "$APPLY" -eq 1 ]] && feedback_ensure_labels "$slug" || true ;;
      elk)         seed_elk "$(basename "${url%.git}")" "$def" ;;
      site-quality) seed_site_quality "$(basename "${url%.git}")" "$def" ;;
      community)   seed_community "$(basename "${url%.git}")" "$def" ;;
      sdlc)        seed_sdlc "$(basename "${url%.git}")" "$def" ;;
      spec-driven) seed_spec_driven "$(basename "${url%.git}")" "$def" ;;
      agent-context) seed_standardize "$(basename "${url%.git}")" "$def" ;;
      governance)  seed_governance "$(basename "${url%.git}")" "$def" ;;
      backlog)     mkdir -p "$(dirname "$FANOUT_BACKLOG_PATH")"
                   cp "$FANOUT_BACKLOG_FILE" "$FANOUT_BACKLOG_PATH"
                   echo "backlog: ${FANOUT_BACKLOG_PATH} written" ;;
    esac
    if [[ -z "$(git status --porcelain)" ]]; then
      echo "${slug}: already conformant"; exit 0
    fi
    git add -A
    git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
      commit -m "$COMMIT_MSG" >/dev/null
    if [[ "$APPLY" -eq 0 ]]; then
      echo "${slug}: DRY RUN — would open PR:"; git show --stat HEAD | head -25; exit 0
    fi
    # The kit branch is machine-owned: re-runs regenerate it. Bare
    # --force-with-lease is useless here — a single-branch clone's fetch
    # refspec doesn't map the kit branch, so git ignores even an explicitly
    # fetched tracking ref and rejects with 'stale info'. Fetch the remote
    # tip and lease on it EXPLICITLY; if the branch doesn't exist yet, a
    # plain push creates it.
    if git fetch origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" >/dev/null 2>&1; then
      git push -u origin "$BRANCH" \
        --force-with-lease="${BRANCH}:$(git rev-parse "refs/remotes/origin/${BRANCH}")"
    else
      git push -u origin "$BRANCH"
    fi
    if [[ "${FANOUT_PR_APPEND:-0}" == "1" ]]; then
      prnum="$(gh pr list --repo "$slug" --head "$BRANCH" --state open --json number --jq '.[0].number' 2>/dev/null || true)"
      if [[ -n "$prnum" && "$prnum" != "null" ]]; then
        prbody="$(gh pr view "$prnum" --repo "$slug" --json body --jq .body)"
        gh pr edit "$prnum" --repo "$slug" ${FANOUT_PR_TITLE:+--title "$FANOUT_PR_TITLE"} \
          --body "$(printf '%s\n\n## %s\n\n%s' "$prbody" "$PR_TITLE" "$PR_BODY")" >/dev/null
        echo "${slug}: appended to PR #${prnum}"
        exit 0
      fi
      PR_BODY="$(printf '## %s\n\n%s' "$PR_TITLE" "$PR_BODY")"
    fi
    # Update mode (backlog kit): re-runs REPLACE the open PR's title/body with
    # the current rendering instead of opening a duplicate.
    if [[ "${FANOUT_PR_UPDATE:-0}" == "1" ]]; then
      prnum="$(gh pr list --repo "$slug" --head "$BRANCH" --state open --json number --jq '.[0].number' 2>/dev/null || true)"
      if [[ -n "$prnum" && "$prnum" != "null" ]]; then
        gh pr edit "$prnum" --repo "$slug" --title "${FANOUT_PR_TITLE:-$PR_TITLE}" --body "$PR_BODY" >/dev/null
        echo "${slug}: updated PR #${prnum}"
        exit 0
      fi
    fi
    gh pr create --repo "$slug" --base "$def" --head "$BRANCH" ${FANOUT_PR_DRAFT:+--draft} \
      --title "${FANOUT_PR_TITLE:-$PR_TITLE}" --body "$PR_BODY" \
      || echo "${slug}: PR may already exist"
  )
  rc=$?
  set -e
  rm -rf "$work"
  echo "::endgroup::"
  return "$rc"
}

# Process substitution (not a pipe) keeps the loop in the main shell so the
# failure counter survives; per-repo failures warn and continue — one flaky
# target must not strand the rest of the fleet. macOS bash 3.2-compatible.
if [[ "$TARGET" == "all" ]]; then
  FAILED=0
  while IFS= read -r p; do
    set +e
    ( set -e; run_one "$p" )
    rc=$?
    set -e
    if [[ "$rc" -ne 0 ]]; then
      echo "::warning::${p}: fan-out failed (exit ${rc}) — continuing with remaining targets"
      FAILED=$((FAILED + 1))
    fi
  done < <(all_targets)
  if [[ "$FAILED" -gt 0 ]]; then
    echo "::error::${FAILED} target(s) failed — see warnings above"
    exit 1
  fi
else
  run_one "projects/${TARGET}"
fi
