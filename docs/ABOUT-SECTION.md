# About section — the repository site map

> The fleet standard for each repo's public-facing about section: a consistent, reliable, comprehensive site map of contribution, docs, governance and the other fundamental pages.

Ratified by constitution § 31 (amendment `mission-and-about-section`, numbered at merge). This document is the operator definition of that section. It extends, and does not replace, the portfolio README skeleton in [PORTFOLIO.md](PORTFOLIO.md) § 4 and UPS-DOC-10.

## 1. What it is

The about section is the map a visitor or an agent uses to find every fundamental page in the repo. It lives primarily in `README.md` (and is published on the public docs site, constitution § 14). It is not a second home page and it does not invent pages: it links to files that exist, in a fixed order, and it says so when an optional page is absent.

**Consistent** means every non-exempt repo presents the same entries in the same order. **Reliable** means every link resolves to a file or URL that exists. **Comprehensive** means every required entry is present, and every optional entry is present when the underlying page exists.

The GitHub About box (description, topics, homepage) stays under [PORTFOLIO.md](PORTFOLIO.md) §§ 1–3 and must agree with the README tagline.

## 2. Entries

Order is fixed. Headings may keep an existing name when it already covers the entry (for example "Usage" for Getting started, or "Documentation" for the docs index plus the site map cluster). Rename a heading only when nothing links to its anchor.

| # | Entry | Required? | What it must do | Typical targets |
| --- | --- | --- | --- | --- |
| 1 | Identity | Required | `# <Name>` and a one-line description of what the repo is. The GitHub description and the README tagline say the same thing ([PORTFOLIO.md](PORTFOLIO.md) § 1). | `README.md` H1 and `>` tagline |
| 2 | Mission | Required for governed repos | A one-liner that states the direction and links to constitution § 1. The README tagline and the AGENTS.md opening one-liner match (constitution § 31.2). | [constitution § 1](constitution.md#1-mission), `AGENTS.md` |
| 3 | Docs index | Required when `docs/` exists | A link to the generated docs index, plus the few documents a reader should open first (UPS-DOC-10, UPS-DOC-03). | `docs/README.md` |
| 4 | Getting started | Required (content repos may fold it) | Copy-pasteable install or usage commands that match `AGENTS.md` **Stack & commands**. Content repos may use one **Working with this repo** section ([PORTFOLIO.md](PORTFOLIO.md) § 4). | `AGENTS.md`, setup docs |
| 5 | Contributing | Required | Links to the contributing guide, the agent guide, and the code of conduct when that file exists. If the repo has no `CONTRIBUTING.md`, link the hub's. | `CONTRIBUTING.md`, `AGENTS.md`, `CODE_OF_CONDUCT.md` or `.github/CODE_OF_CONDUCT.md` |
| 6 | Governance | Required when the governance kit is present; SHOULD for every active governed repo | Links to the constitution, the amendments log, the PRD and the feature catalog. | `docs/constitution.md`, `docs/amendments/README.md`, `PRD.md`, `features/features.yml` |
| 7 | Roadmap / backlog | Optional; required when the page exists | A link to the repo's roadmap or backlog, or to the [Fleet project](https://github.com/users/bamr87/projects/14) when the repo has no local roadmap. | `ROADMAP.md`, `docs/ROADMAP.md`, `docs/BACKLOG.md`, `_data/roadmap.yml` |
| 8 | Changelog / releases | Required as a link | Links `CHANGELOG.md`, or the commit history when there is none yet, plus the GitHub Releases page when releases exist ([PORTFOLIO.md](PORTFOLIO.md) § 4). | `CHANGELOG.md`, `https://github.com/<owner>/<repo>/releases` |
| 9 | Security / support | Optional; SECURITY SHOULD for active public apps | Links `SECURITY.md` (or `.github/SECURITY.md`) and `SUPPORT.md` when they exist. Do not invent a support page. | `SECURITY.md`, `.github/SECURITY.md`, `SUPPORT.md` |
| 10 | License | Required | The license and a link to the LICENSE file. If there is no LICENSE file, say so ([PORTFOLIO.md](PORTFOLIO.md) § 4). | `LICENSE` |
| 11 | Live site / demo | Required when a live URL exists | The homepage, Pages site or demo, using the homepage rule in [PORTFOLIO.md](PORTFOLIO.md) § 3. Omit the entry when nothing is deployed. | GitHub homepage, `live_url` in the registry |

The portfolio footer ([PORTFOLIO.md](PORTFOLIO.md) § 4) still closes the README.

## 3. Exemptions

- **Forks** keep the upstream README. A short bamr87 note may be added below it; do not rewrite upstream structure.
- **Archived and retired repos** need a README, a license when one exists, and a retired notice. Other entries are optional.
- **Private repos** are flagged, never made public by an agent, and may omit a public about section for sensitive research (constitution § 14.3, § 31.6).
- **The hub profile README** is also a personal profile. It keeps the personal intro and the generated portfolio index. The control-plane half — "This repository", Quick start, Documentation, License — is the hub's about section and must carry the mission one-liner and the site map.
- Any other exemption needs a reason the constitution § 15 completeness review accepts, recorded under **Standard deviations** in `AGENTS.md`.

## 4. How this is rolled out

The standard is ratified in the hub, then fanned out one repo per PR (roadmap `FF-NEW:about-section-sitemap`). A fan-out PR adds links to pages that already exist and records genuine gaps; it does not invent files to make the table look complete. The conformance check in constitution § 31.5 is follow-up work and stays warn-only until that repo's fan-out lands.

The snapshot of which entries exist today, repo by repo, lives in [FLEET.md](FLEET.md) § 4. It is evidence for priority, not a promise that every gap has been filled.

## 5. Related

- [PORTFOLIO.md](PORTFOLIO.md) — description, topics, homepage, README skeleton
- [STANDARDS.md](STANDARDS.md) — file-presence tiers
- [SUBMODULES.md](SUBMODULES.md) — how a change moves through `projects/`
- [FLEET.md](FLEET.md) — organization structure, general information, per-repo context
- Constitution [§ 1](constitution.md#1-mission), [§ 14](constitution.md#14-public-documentation-site), [§ 31](constitution.md#31-fleet-mission-statements-and-the-repository-about-section)
