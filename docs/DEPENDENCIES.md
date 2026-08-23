# DEPENDENCIES — the always-latest policy

**Every repo installs the newest published version of every dependency, at every build. No exact pins, no version ceilings, no committed lockfiles.**

Declared in [`_data/fleet.yml`](../_data/fleet.yml) under `dependencies:` (adopted 2026-08). This replaces per-repo update chores (lockfile bumps, Dependabot PRs per library) with a standing posture: currency is automatic, and breakage is handled by the machinery that already watches the fleet.

## Why

Forty repos each carrying pinned manifests and lockfiles means a permanent stream of update PRs nobody wants to review. The fleet explicitly trades reproducibility for zero maintenance:

- A new upstream release is picked up by the **next build** — nothing to merge, nothing to bump.
- If it breaks something, that surfaces in **standard CI** (every push/PR) and in the daily **fleet-pulse** pulse, whose **doctor** job reads the failing run and opens a draft fix PR ([DAILY-ANALYSIS.md](DAILY-ANALYSIS.md)).

Accepted tradeoffs, on the record rather than hidden: builds are **not reproducible** (the same commit can resolve differently tomorrow, so "worked yesterday" needs upstream bisecting, not `git bisect`); and a bad or malicious upstream release reaches CI **the day it ships** — the loop catches breakage, not malice. The fleet accepts both in exchange for never spending time on updates.

## The rules

| Surface | Rule |
| --- | --- |
| `package.json` | ranges are `*` — no exact pins, no ceilings (`file:`/`link:`/`workspace:`/git/URL specifiers are fine) |
| `requirements*.txt` | bare `name[extras]`, env markers allowed — no `==`/`~=`/`<` specifiers |
| `Gemfile` | `gem "name"` with no version args; no exact `ruby "X.Y.Z"` pins (kwargs like `group:`/`require:` are fine) |
| Lockfiles — every ecosystem | **never committed**; gitignored fleet-wide (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Gemfile.lock`, `poetry.lock`, `Pipfile.lock`, `uv.lock`, …) |
| GitHub Actions | **exception** — `uses: owner/action@vN` major tags: a ref is mandatory, minors/patches float within the major, and the hub's `dependabot.yml` bumps majors weekly |
| pre-commit | **exception** — `rev:` pins are mandated by the tool; refresh with `pre-commit autoupdate` |
| Toolchains (node/python/ruby) | **exception** — runtime versions are fleet configuration (`toolchain:` in `_data/fleet.yml` → repo `vars.*` → reusable CI), not per-repo pins |

## Enforcement

Until 2026-08 the policy was declared in three places and checked in none — which is how four PRs arguing *for* SHA-pinned actions (two Dependabot configs premised on pinning, two contributor guides documenting it as the house convention) came to sit open against it simultaneously, and how the prose and agent-context kits each shipped a template that trailed the fleet by two majors before anyone noticed (their `VERSION` changelogs are both post-mortems). It is now **check (j)** of `tools/check-drift.sh`, so it gates every PR:

| Caught | Why it matters |
| --- | --- |
| a SHA-pinned `uses:` (`@<40-hex>`) | frozen forever by design — the Actions exception is `@vN` major tags, nothing narrower |
| a `uses:` pinned to a minor/patch (`@v4.2.2`) | blocks the minors/patches the major tag exists to deliver |
| a **seed template** whose action major trails the hub's own workflows | `templates/` is copied verbatim into ~40 repos, so a stale one *downgrades* every repo the fan-out reaches |
| a committed lockfile | reproducibility the fleet deliberately traded away |
| `==` / `~=` / `<` in a hub `requirements*.txt` | floors (`>=`) never block currency; pins and ceilings do |

The check is offline and hub-scoped, so it cannot know whether the hub's own majors are current *upstream* — that is Dependabot's job (the single `github-actions` entry in `.github/dependabot.yml`, bumping majors weekly). The two are complementary: **Dependabot pushes the fleet forward, check (j) stops anything from being frozen or left behind.** Neither one alone is sufficient.

**Check (k)** is the fleet half, reading one git tree per registry repo for the two violations visible without cloning — committed lockfiles and SHA-pinned `uses:`. It is advisory and `--remote`/`--ci` only, for the same reason as check (g): a repo-scoped token 404s on a private repo exactly as it does on a deleted one. Repos it cannot read are reported as **UNREAD, explicitly not verified clean** — a "0 violations" line over 40 unread repos would otherwise read as a fleet-wide all-clear, which is precisely the false comfort that let three stale seed templates ship. Remediate what it finds with `tools/unpin-deps.sh <checkout>` per repo, or `deps-fanout.yml` fleet-wide.

`templates/*/archive/` is exempt: those are deliberately frozen shapes that `fanout.sh --upgrade` byte-compares against to recognize machine-seeded copies. Freezing them is the point.

## Why CI keeps working without lockfiles

- `standard-ci.yml` was already lockfile-tolerant: the npm cache and `npm ci` are used **only when a lockfile exists** (otherwise `npm install`), the pip cache keys on requirements/pyproject, and `ruby/setup-ruby`'s `bundler-cache` generates its own lock at run time when none is committed.
- The Jekyll repos effectively ran this way all along: `remote_theme` floats on the theme's default branch and the `github-pages` gem environment is managed by GitHub.
- Caches get colder than under pinning (keys move whenever upstream resolves differently) — that is the cost of currency, and the Actions analytics layer will show it if it ever matters.

## Converting a repo

- **One repo, locally**: `tools/unpin-deps.sh <checkout>` — idempotent; strips pins from `package.json`/`requirements*.txt`/`Gemfile`, deletes + gitignores lockfiles, rewrites `npm ci` → `npm install`, drops lockfile-keyed `cache:` lines, floats `@vX.Y.Z` action tags to `@vX`, and prints what it changed. Review with `git diff`, commit in the repo itself (submodule workflow).
- **Fleet-wide**: dispatch **`deps-fanout.yml`** (dry-run by default — flip `dry_run` off to push `chore/deps-latest` branches and open PRs). Engine: `tools/fanout.sh --kit deps-latest`; external upstreams (e.g. `microsoft/skills`) are skipped automatically.
- **What the transformer deliberately leaves**, reported as `follow-up:` lines in its output: `pyproject.toml`/Poetry/`Pipfile` dependency tables (no safe stdlib TOML writer), hash-pinned requirements files (hashes require exact pins — converting one is a decision, not a transform), npm `overrides`/`resolutions` (transitive forcings that may be load-bearing), and toolchain files (`.ruby-version`/`.nvmrc`/`.python-version` — see exceptions). Finish those by hand or let the doctor/@claude do it on the PR branch.

## Hub state

The hub practices the policy: no committed lockfiles (`Gemfile.lock` removed), the root `.gitignore` blocks every lockfile pattern, manifests carry floors at most (`>=` never blocks currency), and `.github/dependabot.yml` is reduced to the single Actions-majors exception.
