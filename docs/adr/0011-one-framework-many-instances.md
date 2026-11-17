# ADR 0011 — One framework, many instances: the stack installs for any owner

- **Status**: accepted
- **Accepted in**: https://github.com/bamr87/bamr87/pull/913 (merged 2026-11-17 by @bamr87)
- **Date**: 2026-11-16
- **Deciders**: proposed by an agent at the maintainer's request (2026-11-16: a stack across these repos that can be applied to any other set of repos for development and governance, installed first for the `bash-365` organization, and general enough that others adopt it instead of rebuilding it)
- **Related**: constitution § 10.8 (prior art first), § 12.3 (gated changes), § 22 (repository cap); PRD FR111 (the agentic loops dashboard as the application Bash 365 is based on); [WORKFLOW-VERSIONING.md](../WORKFLOW-VERSIONING.md); bamr87/bamr87#458 (callers off `@main`); pull requests #911 (framework sources mounted) and #912 (v2.2.0)

<!-- Accepted in and Completed are added by the post-merge ratify job when the maintainer merges this ADR's PR and when the maintainer closes the Tracking issue as completed (docs/adr/README.md#lifecycle). -->

## Context

### Needs assessment

This repository is two things in one tree: a **framework** (the standard in `specs/`, the kits in `templates/`, the tools, the reusable workflows and actions, the console, the governance templates) and **one instance** of it (bamr87's registry, snapshots, profile, pages, nodes and personal settings). Nothing separates them, so another owner can use pieces of the stack and cannot install it. Measured on 2026-11-16:

- **One root.** Every tool finds a single root from its own location (`tools/dash:13`, `tools/check-drift.sh:70`, `tools/fanout.sh:195`, `tools/conformance.py:42`, `.github/scripts/dash-gen/dash_gen.py:148`), and that root must hold both the framework's files and the instance's data. Run against a directory holding only the `bash-365` registry, the standard checker stopped on a missing `_data/specs.yml`; with three framework files copied in it ran and reported `hub tools/docs_index.py not found`. An instance today is a copy of the whole repository.
- **Identity is written into the code.** `_data/fleet.yml` has a `hub:` block (`repo`, `shared`, `default_branch`, `bot_name`, `bot_email`, `owners`), but the literal `bamr87/bamr87` still appears 180 times in the kits (tests and fixtures excluded), 123 times in `tools/`, 74 in `.github/workflows/`, 69 in the generator and 19 in `specs/`. Nothing reads `hub.bot_name` or `hub.bot_email`; the bot is a literal in ten files. No workflow reads the `FLEET_HUB` variable the hub projects onto every repo. Some of those literals are the framework's address, which is meant to be fixed; most are this instance's identity.
- **"Owned" means one owner.** `hub.owners` lists `bamr87`, `bash-365`, `year-of-ai` and `ai-world-view`, and the fan-out, the decision index and the fleet graph honour it. The secret and variable audit, the token rotation, the issue pipeline, the evolution and scout loops, the lake and the console's writes treat only the owner of `hub.repo` as owned (`tools/fleet-config.py:118`), and the dashboard forces every other repo green as an "external mirror" (`dash_gen.py:386`). The rotation ledger holds 154 `bamr87/` repos and none from the three organizations. Two paths address an organization's repo under the wrong owner: `fanout.yml:222` (`slug=bamr87/<name>`) and the kit seeds that write `bamr87/__PROJECT_NAME__` (`templates/verify/features.template.yml:48`, `tools/fanout.sh:810`). `bash-365` is a tenant of this instance in name and is half managed in practice.
- **No install path.** There is no command that creates a control plane for an owner and no document for a second hub. `tools/setup.sh` prepares a machine for this repository; `tools/dash new` scaffolds one project.
- **The interface an adopter pins is behind, and the fleet is not on it.** The floating `v2` tag predates the OAuth-only change (#912 cuts v2.2.0). References to the hub at `@main` fail UPS-WORK-10 and UPS-QA-40 in 38 of 38 graded repos, no repo passes every MUST of the standard (455 failures), and landing every open fan-out pull request would leave 413.
- **A kit upgrade can strand its copies.** In 34 repos one open pull request hand-edits the kit-seeded `claude.yml` and another replaces it with a kit release. Whichever merges first conflicts the other, and the hand edit alone leaves a file that no later `fanout.sh --upgrade` recognises. An adopter who cannot upgrade has a fork, not a framework.

What an outside adopter can use today without forking: the reusable workflows and the `claude-run` and `claude-auth` actions at `@v2`, the standard and its checker through `fleet-conformance.yml`, the `spec-driven` Claude Code plugin, the npm kits (`@bamr87/fleet-engines`, `@bamr87/fleet-feedback`) and the Pyramid Schema package from `bamr87/SCHEMA`. What they cannot do: run the control plane (registry, loops, fan-out, console) under their own identity, seed kits that name their own owner, or pass the standard from a copy of the hub, because the contracts accept only `bamr87/bamr87` as the caller's source.

### Prior art survey (§ 10.8)

- **Backstage software templates and catalog.** Fit: a registry of components and a scaffolder that creates repositories from templates. Limits: a service to host, and a scaffolded file has no upgrade path.
- **Copier** (and Cruft over Cookiecutter). Fit: a template rendered from recorded answers, and `copier update` to re-apply a newer template to a project that has moved on. Limits: files only; it does not run anything.
- **Reusable workflows and Renovate shared presets.** Fit: behaviour consumed by reference at a version, which is how fleet repos already call the hub. Limits: only what a workflow can express.
- **Helm charts and Terraform modules.** Fit: a versioned package of defaults and a small values file per installation. Limits: none that matter here; this is the shape `_data/fleet.yml` lacks.
- **An owner's `.github` repository, repository templates and organization rulesets.** Fit: GitHub's own place for an organization's defaults, profile and shared workflows. Limits: one owner at a time.
- **Pyramid Schema's `DISTRIBUTION.yml`** (in the fleet, `bamr87/SCHEMA`). Fit: a content-addressed manifest of the files a consumer copies, with strict or text parity, so a vendored copy cannot drift unseen.

**Build versus adopt.** Adopt the reference-at-a-tag channel the hub already has, the defaults-plus-values split for settings, Copier's recorded answers and update step for the instance skeleton, and the distribution manifest for every vendored payload. Build two small things: a resolver for the two roots and the identity, and the `init` command.

## Decision

1. **Two roots.** The **framework root** is where the tools, the standard, the kits and the contracts are read from: the checkout the tool runs from. The **instance root** is the control plane that owns a set of repos: its `_data/projects.yml`, its settings, its `.gitmodules` and `projects/`, its governance documents and its snapshots. `FLEET_HOME` names the instance root, and a tool that takes a path takes `--instance`. With neither, the instance root is the framework root, which is today's layout and stays the default.
2. **One identity, read once.** A resolver in `tools/fleetcore/` (with a shell twin) returns the instance's repo, owners, bot, default branch and site from its settings, falling back to `GITHUB_REPOSITORY`. "Owned" means `hub.owners` everywhere. A drift check refuses a new literal owner in `templates/`, `tools/`, `.github/workflows/`, `.github/actions/` and `specs/`, with an allowlist for the framework's address.
3. **Settings are defaults plus an overlay.** `_data/fleet.yml` splits into the framework's defaults (toolchains, images, dependency policy, schedule rules, caps, budgets, the token contract's names) and an instance overlay (`hub`, per-repo switches, nodes, content sites, API-key workspaces, the Projects board). Slugs that repeat the hub's are derived from it.
4. **The framework's address is a setting.** `framework: {repo, ref}` defaults to `bamr87/bamr87` at the floating major. The contracts' caller patterns read it; a reusable workflow checks its own tooling out from `job.workflow_repository` at `job.workflow_sha`; a hub-only workflow checks out `github.repository`.
5. **Kits name their target's owner.** Seeding gains `__OWNER__` and `__CODEOWNER__` beside the three placeholders it has, and each vendored payload gets a distribution manifest of the kind Pyramid Schema ships.
6. **Installing is one command.** `tools/dash init --owner <owner>` writes an instance skeleton to a directory: a registry built from the owner's repositories, the settings overlay, the governance kit, thin callers of the loops pinned at the framework's tag, and the answers it was given. It is a dry run by default and creates nothing on GitHub. `tools/dash upgrade` moves the framework pin and re-applies the skeleton.
7. **Two topologies.** An owner is a **tenant** (listed in another instance's `hub.owners`) or has its **own instance**. For an organization the instance repo is recommended to be its `.github` repository, GitHub's home for an organization's profile, defaults and shared workflows; for a user, the profile repository, as here.
8. **This repository stays both** the framework's source and instance one. No repository is created for the framework (§ 22) until the last phase reviews whether one is needed.

### Phases

| Phase | Delivers | Done when |
| --- | --- | --- |
| P0, this pull request | This record; `tools/conformance.py` reads the registry and settings from a named instance (`--instance`, `FLEET_HOME`) | `tools/test_conformance_instance.py`: an instance holding only its registry is graded with the framework's standard, and with no instance named nothing changes |
| P1, identity | The resolver; "owned" is `hub.owners`; the bot read from settings; `fanout.yml:222` and the wrong-owner seeds fixed; the literal-owner drift check | The `bash-365`, `year-of-ai` and `ai-world-view` repos appear in the rotation ledger, the issue pipeline and the triage queue, and are no longer forced green |
| P2, two roots everywhere | `dash`, the drift gate, the generator and the fan-out honour `FLEET_HOME` | The drift gate and `dash status` pass against a fixture instance that holds no framework file |
| P3, overlay and address | The settings split; `framework:`; contracts and workflows parameterised; the owner placeholders in the kits | A copy of the hub under a test owner passes its own drift and conformance gates |
| P4, install | `dash init`, `dash upgrade`, `docs/ADOPTING.md` | A `bash-365` instance is generated locally, its gates pass, and the kits dry-run against its two repos |
| P5, first adopter | `bash-365` moves from tenant to its own instance; the framework-repository question is reviewed | Amr's decisions: the repository in the organization, its secrets, and each apply |

Every phase after P0 is its own pull request under the tracking epic that follows acceptance. Creating a repository, setting a secret and applying a fan-out stay the maintainer's.

## Consequences

**Positive**

- `bash-365` is fully managed as soon as P1 lands, before it has an instance of its own.
- An adopter's control plane is a registry, an overlay and a pin. Upgrading is moving the pin, not merging a fork.
- The hub is held to the rule it sets: its own callers and kits go through the same resolver and the same tag.
- The first slice is additive: `--hub` keeps its meaning and its default, so the versioned checker interface gains an option and loses nothing.

**Negative**

- A wide, mechanical change: about a hundred files derive a root or name the owner. It is spread over P1 to P3 and each phase needs its own tests.
- Two roots are one more thing to get wrong; a tool that reads instance data from the framework root would report the wrong fleet. P2's fixture test exists for that.
- Splitting `_data/fleet.yml` touches the file most tools read. Until P3 the overlay is a plan.
- The framework's address stays `bamr87/bamr87`, so an adopter depends on this repository's tags and on #458 and #912 keeping them current.

## Alternatives considered

- **A template repository, or a fork per owner.** Rejected: it is a copy that starts drifting on the first day, which is the failure the kit archives already guard against at file scale.
- **Split the framework into its own repository now.** Deferred to P5: the repository cap (§ 22) asks for a merge with every new repository, and the split is only clean once the two roots exist.
- **Tenants only: list every adopter in `hub.owners`.** Kept as the first topology and insufficient alone: a stranger cannot be a tenant of bamr87's instance, and an organization's governance, secrets and budget are its own.
- **A GitHub App or hosted service that manages repositories for its installers.** Rejected for now: it adds an operator, a server and a trust boundary, and `docs/COCKPIT.md` already rules multi-tenant packaging out of scope. The file-and-tag design leaves that door open.
- **Publish everything as packages (npm, PyPI) and drop the checkout.** Rejected as the only channel: the loops are workflows and the gates read a working tree. Packages stay for the engines that already ship that way.

## Supersedes / Superseded by

None.
