# 0024 — Roadmap entries are numbered at merge, like every other sequential id

- **Status:** proposed (ratification pending — Amr ratifies by merging this PR)
- **Number:** 0024
- **Date:** 2026-11-05
- **Proposed by:** Grok Bot (agent), on Amr's instruction as owner
- **Ratified by:** the merged PR URL (leave blank until merged)
- **Affects:** constitution § 2 (numbering invariant, extends amendment 0002) and § 5 artifact table; PRD FR28; feature `HUB-084`
- **Supersedes:** none (extends [0002](../0002-conflict-free-numbering.md))
- **Related:** `_data/roadmap.yml`, `tools/jev/number.py`, `.github/workflows/jev-number.yml`

## Context

Amendment 0002 moved every sequential id — `HUB-NNN`, `FRn`/`NFRn`, amendment numbers, changelog entries — to assignment at merge, so two parallel pull requests can never claim the same number. Roadmap ids (`FF-NNNN` in `_data/roadmap.yml`) were left out: the `/future-features` command and the `feature-scout` agent still told contributors to "assign the next free `FF-NNNN` id (scan existing ids)". The race 0002 removed came straight back for the roadmap. Two open pull requests each appended the next `FF` by hand, and issue bodies started citing ids that had not landed. Amendment `Affects:` lines that named a roadmap id were also flagged by `governance_lint` as unknown refs.

## Amendment

In constitution § 2, the numbering invariant now reads (added text in bold):

> A pull request never assigns a sequential id. New entries carry a placeholder (`HUB-NEW`, `FR-NEW:<key>`, `NFR-NEW:<key>`, **`FF-NEW`**, `number: NEW`) and reference each other by slug; the number is assigned on the default branch, by one serialized process, and is never reused. **This includes roadmap entries (`FF-NNNN`, written as `_data/roadmap.d/<slug>.yml`); gaps in a series are never back-filled.**

In § 5's artifact table, a row is added: `_data/roadmap.d/<slug>.yml` — a roadmap entry awaiting its `FF-NNNN`; one entry per file, `id: FF-NEW`; numbered and appended to `_data/roadmap.yml` at merge.

Mechanics (`tools/jev/number.py`, run by `jev-number.yml`):

1. The next `FF` is one past the highest `FF-NNNN` ever seen in `_data/roadmap.yml`, `features/features.yml`, `PRD.md`, `CHANGELOG.md` and every numbered amendment. Gaps (FF-0022, FF-0023, FF-0027, FF-0028) stay gaps.
2. Roadmap fragments are numbered first, in sorted filename order, so feature and amendment fragments in the same run may cite them as `FF-NEW:<slug>`.
3. The entry is appended to `_data/roadmap.yml` as text (its schema header and every existing byte are kept), and the fragment is deleted.
4. `number lint --base` rejects an added `- id: FF-NNNN` line in `_data/roadmap.yml`. Editing an existing entry's `status:`, `priority:` or `issue_url:` in a pull request stays allowed: that file is not fully generated, and the Work board edits it in place.

## Consequences

- `/future-features` and `feature-scout` write `_data/roadmap.d/<slug>.yml` with `id: FF-NEW`. They no longer pick numbers.
- `governance_lint` accepts `FF-NNNN` ids in an amendment's `Affects:` line, and warns only when the roadmap exists and lacks the id.
- The PM review and the Work board show a pending fragment as `FF-NEW:<slug>`. `_data/work_queue.yml` keys stay `roadmap:FF-NNNN`, so a pending entry is pinned only after it has a number.
- Open pull requests that already append a hand-picked `FF-NNNN` must switch to a fragment with `FF-NEW` before they merge, or `number lint` will flag them.
