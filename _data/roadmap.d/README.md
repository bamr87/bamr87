# _data/roadmap.d/ — pending roadmap entries

One file per new roadmap entry, written by the pull request (or the `/future-features` flow) that proposes it; compiled into [`../roadmap.yml`](../roadmap.yml) by `python3 -m tools.jev number apply` when it lands on `main` ([amendment 0002](../../docs/amendments/0002-conflict-free-numbering.md), extended by amendment `roadmap-numbering-at-merge`; [docs/JEV.md](../../docs/JEV.md)).

**A pull request never picks the next `FF-NNNN`.** Two open pull requests that both append `FF-0040` collide; a fragment cannot, because its name is its slug and the number is assigned once, on `main`, one past the highest `FF` id ever seen (in the roadmap, the feature catalog, the PRD, the changelog or a numbered amendment). Gaps are never reused.

```yaml
# _data/roadmap.d/my-idea.yml
id: FF-NEW                  # always FF-NEW — the compiler assigns the number
slug: my-idea               # optional; defaults to the filename stem
title: Short imperative summary
project: bamr87
repo_url: https://github.com/bamr87/bamr87
status: proposed
priority: P2
effort: M
category: feature
problem: >-
  The pain, in one or two sentences.
proposal: >-
  What to build.
acceptance:
  - "What done looks like."
source: manual
created: 2026-11-05
issue_url: null
```

Elsewhere — an issue body, a feature fragment, an amendment's `**Affects:**` line — refer to the pending entry as `FF-NEW:my-idea`. Inside fragments the compiler rewrites it; in an issue or PR body, edit it to the assigned id after the merge (the compile PR names it).

| Command | What it does |
| --- | --- |
| `python3 -m tools.jev number next` | the next free id in every series, `FF` included |
| `python3 -m tools.jev number plan` | what the pending fragments would be assigned |
| `python3 -m tools.jev number apply` | assign, append to `roadmap.yml`, delete the fragment |
| `python3 -m tools.jev number lint --base origin/main` | reject a hand-picked `- id: FF-NNNN` added to `roadmap.yml` |

While pending, the PM review and the Work board show the entry as `FF-NEW:<slug>`; the Work board edits status only on numbered entries, and `_data/work_queue.yml` keys stay `roadmap:FF-NNNN`.
