# features/features.d/ — pending feature entries

One file per new feature, written by the pull request that adds the feature; compiled into [`../features.yml`](../features.yml) by `python3 -m tools.jev number apply` when the pull request lands on `main` ([amendment 0002](../../docs/amendments/0002-conflict-free-numbering.md), [docs/JEV.md](../../docs/JEV.md)).

**A pull request never picks the next `HUB-NNN`.** Two branches that both append `HUB-033` to `features.yml` conflict on the same line and, worse, agree with each other after a careless merge — two features with one id. A fragment cannot collide: its name is its slug, and the number is assigned once, on `main`, by the only process that can see every other pending fragment.

```yaml
# features/features.d/my-capability.yml
id: HUB-NEW                 # always HUB-NEW — the compiler assigns the number
slug: my-capability         # optional; defaults to the filename stem
title: "What the user gets"
description: "One paragraph, one line. What it does, where, and what proves it."
implemented: true
status: shipped             # shipped | partial | planned | deprecated | tbd
surface: infra              # ui | infra | cli
link: tools/my_capability.py
docs: docs/MY-CAPABILITY.md
tags: [ example ]
date: 2026-10-29
tests:
  - tools/test_my_capability.py
prd: ["FR-NEW:my-capability"]   # reference a NEW requirement by slug, not by number
prd_new:                        # …and declare it here; the compiler numbers it
  - key: my-capability
    kind: FR                    # FR | NFR
    text: "The product must …"
```

| Command | What it does |
| --- | --- |
| `python3 -m tools.jev number next` | the next free id in every series |
| `python3 -m tools.jev number plan` | what the pending fragments would be assigned |
| `python3 -m tools.jev number apply` | assign, compile into `features.yml` + `PRD.md`, delete the fragment |

The compiler consumes the fragment: after it runs, the entry lives in `features.yml` and nowhere else. An existing numbered entry stays exactly where it is — this directory is for what is not numbered yet.
