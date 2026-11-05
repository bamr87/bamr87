<!-- kit: governance v0.1.0 -->
# 0019 — Container images are built once, from pinned bases, and promoted by digest

- **Status:** ratified
- **Number:** 0019
- **Date:** 2026-11-02
- **Proposed by:** agent (Grok Bot, on a branch opened for bamr87)
- **Ratified by:** https://github.com/bamr87/bamr87/pull/591 (merged 2026-11-04 by @bamr87)
- **Affects:** constitution § 2 (new invariant), new § 21 (follows § 20 `editor-front-door`); feature `fleet-container-management` (HUB-NEW, follow-up fragment); requirements: none yet
- **Supersedes:** none (extends § 13, § 17 and the image standard in `docs/DOCKER.md`)
- **Related:** bamr87/bamr87#590 (backlog issue), #588, #589, Fleet project #14, `docs/DOCKER.md`, `docs/CONTAINERS.md`, `docs/FLEET-COMPOSE.md`, release-please, Design for Failure (DFF, `.github/copilot-instructions.md`)

## Context

The fleet has a version registry for base images (`_data/fleet.yml` `images:`, `docs/DOCKER.md`) and a shared local container plane (`docs/CONTAINERS.md`), but no rule for what happens after a Dockerfile builds: which registry holds images, how they are tagged, whether production runs the image that was tested or a rebuild, whether images are scanned or signed, and who owns them. Each repo that ships an image decides alone, so a rebuild per environment can ship bytes nobody tested, a mutable tag can change under a running deploy, and a secret baked into a layer is public the moment the image is pushed. Issue #590 collects the open questions (registry, tagging, base updates, multi-arch, cost); this amendment fixes the principles those answers must satisfy.

## Prior art

- **`docs/DOCKER.md`:** versions come from one registry and a harmonizer delivers them as PRs; hub-published base images were rejected. This amendment keeps that and adds the build-and-ship half.
- **Build once, promote by digest:** the common CD practice (GitHub Environments with protection rules, OCI digests, SLSA provenance, Sigstore/cosign, SBOM via syft/BuildKit); nothing new is built that these cover.
- **DFF (Design for Failure):** promotion by digest makes rollback a pointer move to a known-good digest; a failed scan or promotion leaves the previous digest running.
- **§ 13 and JEV tiers:** deterministic build, scan and SBOM steps are tier 0; any AI step on findings is tiered and capped there. **§ 17:** a scheduled image job has a central kill switch.

## Amendment

Add to constitution § 2 (Invariants):

> - A production container image is built once and promoted through environments by digest, never rebuilt per environment, and never contains a secret. _(amendment `container-management`, numbered at merge)_

Add constitution § 21 "Container images and containers" with the text in `docs/constitution.md`.

## Consequences

- Follow-up (#590): choose the registry and tagging scheme, write the reusable build/scan/promote workflow and the per-repo stub, add the feature fragment `fleet-container-management` (HUB-NEW), and file the GitHub-facing parts as a githubai feature.
- `docs/DOCKER.md` gains a "build and ship" section once #590 settles the open questions; until then § 21 is warn-only per repo.
- Repos with no image are not applicable; dev-only images follow items 1, 5, 6 and 7 only.
- Merging the pull request that carries this record ratifies it. An agent never merges it.
