# Fleet consolidation — fewer repos, one place per concern

> Decision record for the 2026-10-19 consolidation: which repositories merge into which, how the merge is done, what the hub does on each side, and the decisions still open. Status lines here are updated as the pull requests land.

## Why

Forty-plus submodules had grown several pairs and clusters that share one purpose — a tool and its experiment, a site and its sidecar, three takes on git tooling. Each extra repository costs a CI run, a credential, a harness, a kit fan-out and a registry row, and the dash reports on all of it. Merging the clusters makes the fleet smaller without losing anything: every merge imports the source's **full history** under a subdirectory, so `git log` and `git blame` keep working at the new path.

## The recipe

The same one [zer0-CMS documents](https://github.com/bamr87/zer0-CMS/blob/main/docs/MONOREPO.md): clone the source, drop its tags, rewrite it with `git filter-repo --to-subdirectory-filter <path>` (bare `#123` references become `owner/repo#123` so they still point at the source's issues), then `git merge --allow-unrelated-histories` into the target on a branch, and open a pull request. Nested `.github/workflows/` never run from a subdirectory: the thin callers a target already runs at the root (standard CI, the `@claude` handler, the prose gate) are dropped from the import; bespoke workflows stay as the reference for porting. Nothing is archived or deleted by the merge itself.

## The map

| Source | Target | Path | PR | Status |
|---|---|---|---|---|
| bamr87/lawmode | bamr87/law-ai | `lawmode/` | [law-ai#174](https://github.com/bamr87/law-ai/pull/174) | PR open |
| bamr87/gitnexus | bamr87/gitorio | `packages/gitnexus/` | [gitorio#136](https://github.com/bamr87/gitorio/pull/136) | PR open |
| bamr87/git-with-the-program | bamr87/gitorio | `packages/git-with-the-program/` | [gitorio#136](https://github.com/bamr87/gitorio/pull/136) | PR open |
| bamr87/retro-pi | bamr87/rewind-arcade | `retro-pi/` | [rewind-arcade#36](https://github.com/bamr87/rewind-arcade/pull/36) | PR open |
| bamr87/1987 | bamr87/zer0-CMS | `sites/1987/` | [zer0-CMS#36](https://github.com/bamr87/zer0-CMS/pull/36) | PR open |
| year-of-ai/2005 | bamr87/zer0-CMS | `sites/2005/` | [zer0-CMS#36](https://github.com/bamr87/zer0-CMS/pull/36) | PR open |
| bamr87/cv | bamr87/cv-pro (new) | `cv/` | [cv-pro](https://github.com/bamr87/cv-pro) | pushed to `main` |
| bamr87/cv-builder-pro | bamr87/cv-pro (new) | `app/` | [cv-pro](https://github.com/bamr87/cv-pro) | pushed to `main` |
| bamr87/zer0-mistakes, zer0-image-generator, books, drsai, zer0-pages, zer0-pages-remote, zer0-demo-garden, zer0-demo-cookbook, barodybroject | bamr87/zer0-CMS | `packages/`, `sites/`, `apps/` | done earlier | imported; originals still authoritative for releases and Pages (see below) |

## The hub's side

**Add (this record's PR):** `godotgo`, `bash-365-apex`, `year-of-ai.github.io`, `ai-world-view.github.io` and `bash-365.com` become submodules — live repositories under the owner's accounts that the registry never listed — and so does the new `cv-pro`. `amrchy` (a 248 MB personal fork of Omarchy) and the two zer0 demo sites (already in zer0-CMS `sites/`) are registered without a submodule: shown on the dash, not checked out.

**Retire (a follow-up PR, after the merges land):** the `lawmode`, `gitnexus`, `git-with-the-program`, `retro-pi`, `cv`, `cv-builder-pro` and `books` submodules leave `.gitmodules` and the registry, their references in the hub's own docs and port map move to the targets, and the originals are archived. `books` qualifies now: zer0-CMS reports its CI fully ported and nothing left depending on the original.

## Open decisions

1. **The rest of the zer0 family.** zer0-CMS's MONOREPO.md is explicit that `zer0-mistakes` (the `remote_theme` source every Pages consumer names, plus the gem release), `zer0-image-generator` (gem release), `zer0-pages`, `drsai`, `barodybroject` and the demo sites still do something only their own repository can do today. Their hub submodules stay until, per repository, either the monorepo becomes the place work happens and the original is a read-only mirror fed by `git subtree split`, or the original stays authoritative. One direction per repository, never both.
2. **The lineage organizations.** year-of-ai carries thirteen year repos and ai-world-view four country repos, all generated knowledge bases. Only the two org root sites were added; the per-year and per-country repos are tracked through the content atlas. Registering all seventeen as submodules would undo the point of this exercise — say so if you want them anyway.
3. **cv-pro's deploy.** The live CV site and its releases still publish from bamr87/cv; cv-pro carries those workflows under `cv/.github/workflows/` as reference. Port the publish and release workflows to the root, repoint the `sync-cv` skill at `cv-pro/cv/data/cv.json`, then archive both originals.
4. **Archiving.** Every original is left untouched by this work. Archive each one only after its merge PR is in and anything it still publishes has moved.
