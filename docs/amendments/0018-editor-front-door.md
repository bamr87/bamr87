<!-- kit: governance v0.1.0 -->
# 0018 — The editor is a front door: every harness surface from VS Code, through the same entry points

- **Status:** ratified
- **Number:** 0018
- **Date:** 2026-11-02
- **Proposed by:** agent (Claude Fable 5.1, on a branch opened for bamr87 at Amr's request on 2026-11-02)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/592 (merged 2026-11-03 by @bamr87)
- **Affects:** constitution new § 20 (follows § 19 `fleet-pr-review`), § 7 (new gate line); specs UPS-REPO-40 (new row, SHOULD); `_data/standards.yml` (new artifact `vscode`); `tools/conformance.py` (new check `UPS-REPO-40`); `tools/test_vscode_launch.py` (new gate); `.vscode/SCHEMA.md` and the root `SCHEMA.md` row; feature `HUB-067`; requirement `FR63`
- **Supersedes:** none (extends § 2's SCHEMA protocol and § 7)
- **Related:** [`.vscode/README.md`](../../../.vscode/README.md), [docs/CONTAINERS.md](../../CONTAINERS.md), [docs/FLEET-COMPOSE.md](../../FLEET-COMPOSE.md), [docs/DASH.md](../../DASH.md), [specs/REPOSITORY.md](../../../specs/REPOSITORY.md) UPS-REPO-30 / UPS-REPO-34, 0016 `fleet-design-consistency` (the warn-then-fail rollout pattern)

## Context

The hub's `tools/dash` is the one command router the CLI, the Harness Console's job API and CI share, and the constitution already says the console never carries a second implementation of anything (`tools/console/README.md`, § 11). The editor was the exception. `.vscode/launch.json` had grown by accretion: it called `tools/fleet-dev.sh` directly instead of `tools/dash dev`, it started a second hub compose project (`fleet-hub`) that collided with the running core on 4000/4001, it carried hand-picked ports for `devenv` that the workspace container no longer published, and about a dozen of its entries pointed at repositories that no longer exist at those paths (cv-builder-pro, gitnexus as a top-level project, lawmode, books, git-with-the-program, `zer0-cms/packages/zer0-mistakes`). Nothing held it to the registries, so nothing noticed.

The 2026-11-02 rewrite (`refactor/vscode-harness-launch`) put every surface behind F5 — the container plane, the console (natively under `debugpy`, with its page under Vite), the public site and `verify`, the lake and log planes, the generators, the JEV loop runner, every gate, every compose-hosted and workspace-hosted submodule — each one through `tools/dash` or the tool's own entry point. That is only durable if the rule is written down and a gate holds it: which registry each picker follows, which plane an entry talks to, and that a new surface adds its entry in the same PR.

Prior art checked: § 2 (the SCHEMA protocol: add, remove, rename in the same change — the same discipline, applied to editor entries); § 7 (gates the repo's guide names); UPS-REPO-30 (compose + devcontainer pin the fleet extension set) and UPS-REPO-34 (published ports come from `_data/ports.yml`); 0016's warn-then-fail rollout for a fleet-wide convention; `tools/docker_view.py`, which already joins `launch.json` to the port registry for the `/docker/` page. No section covers the editor as a surface.

## Amendment

Add to the constitution:

> ## 20. The editor is a front door
>
> 1. **One front door** — every development tool, loop, gate and surface of the hub is reachable from the editor: `.vscode/launch.json` and `.vscode/tasks.json` call `tools/dash`, a tool's own entry point, or `docker compose` against the hub's own services, and never carry a second implementation of anything the CLI, the Harness Console's job API or CI runs.
> 2. **Registries, not numbers** — a port, project, site, scenario or loop named in an editor configuration comes from its registry (`_data/ports.yml`, `_data/fleet.yml` `containers.ports`, `docker-compose.yml`, `.gitmodules`, `verify/scenarios/`, `content.sites`); a picker is held equal to its registry by `tools/test_vscode_launch.py`, which is one of the § 7 gates.
> 3. **Parity in the same PR** — a new `tools/dash` subcommand, loop, gate, user scenario, content site or submodule adds its editor entry and the `.vscode/README.md` line that describes it in the same pull request (README-Last applies to `.vscode/`); an entry that points at a retired path is removed, never left to fail.
> 4. **Debuggers, not terminals** — where a surface can be debugged (the console's API and page, a generator or hub test, a container that ships a debug layer) the entry is a real debugger (`debugpy`, a browser with source maps, an attach) on a hub port that never collides with the running core; a terminal launcher is the fallback, not the default.
> 5. **Fleet** — a fleet repo with a run, test or debug command carries its own `.vscode/launch.json` and `tasks.json` that call the repo's own one-command entry points (UPS-REPO-40); the hub's `.devcontainer/` and `.vscode/extensions.json` are the reference extension set (UPS-REPO-30). Warn-only per repo until a seed kit exists and its fan-out PR lands.
> 6. **Exemptions** — content repos, forks and archived or retired repos are exempt; any other exemption is recorded as a standard deviation (UPS README "Deviating").

And to § 7 (Quality gates):

> - `python3 tools/test_vscode_launch.py` (the editor is a front door: `.vscode/` calls `tools/dash`, its pickers and ports follow the registries — § 20)

## Consequences

- **Hub.** `.vscode/` gains a `SCHEMA.md` and a row in the root `SCHEMA.md`; `tools/test_vscode_launch.py` runs in `tools/run-all-tests.sh` and holds the four files parseable, every pre-launch task and input resolvable, each picker equal to its registry, every named port published by the plane its entry talks to, and the front-door rule (no `fleet-dev.sh`, no `fleet-hub`, no `--all`). `AGENTS.md` gains the convention in one line.
- **Standards.** `specs/REPOSITORY.md` gains UPS-REPO-40 (SHOULD; app, api, site, ext, cli, lib): `.vscode/launch.json` + `tasks.json` present, JSONC-parseable, every `preLaunchTask` resolving — audited by `tools/conformance.py`; `_data/standards.yml` gains the artifact `vscode` (`.vscode/launch.json`), `recommended` for the active tier and `na` elsewhere, so `dash audit` surfaces the gap amber without blocking.
- **Fleet.** The seed is a gap: a `templates/vscode/` kit (per stack profile in `specs/STACKS.md`) is the follow-up, tracked on the roadmap once the maintainer approves it; the row stays SHOULD and the audit warn-only until the kit's fan-out PRs land (0016's rollout pattern). Repos that already adopted the 2026-09 "fleet .vscode run/debug convention" are the first conformers.
- **Known seam, not decided here.** Two dev-stack systems coexist (`tools/dash up` on network `fleet` with registry `dev_port`s; `tools/dash dev` on `fleet-net` with `_data/ports.yml`). The editor entries use `dash up` for the core and `dash dev` for projects and document the seam in `.vscode/README.md`; reconciling the two maps is a separate decision (an ADR), and this amendment does not pre-empt it.
