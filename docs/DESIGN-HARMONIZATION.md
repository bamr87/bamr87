# Fleet design harmonization — roadmap and plan

> How the fleet's front-ends move to one shell, layout and design language: inventory, shared tokens and shell, a warn-then-fail check, and fan-out PRs. Rule: proposed amendment [`fleet-design-consistency`](amendments/proposed/fleet-design-consistency.md); shell item: roadmap FF-0032 (`_data/roadmap.yml`).

## Phases

| # | Phase | Output | Done when |
| --- | --- | --- | --- |
| 0 | Inventory | `_data/frontends.yml` (generated): per repo, its front-end type (Jekyll/zer0, React, other, none), framework, theme, tokens source, shell | Every registry repo has a row |
| 1 | Shared tokens | One token source seeded from fleetcore's bashOS palette, exported as CSS variables, a Mantine theme and SCSS for zer0 | Console and zer0-mistakes both build from it |
| 2 | Shell (FF-0032) | Redesigned Harness Console app shell — collapsible, manageable, customizable regions, persisted layout — extracted into a package (successor to `@bamr87/harness-console-ui`) | Console runs on the package; static Pages build matches |
| 3 | Conformance | `tools/conformance.py` check `design`: tokens used, shell or zer0 present, no forked copies | Check runs fleet-wide, warn-only |
| 4 | Fan-out | One PR per front-end repo (zer0 sites first, then React apps), with § 15 visual evidence | Each merged PR flips that repo to fail-on-error |
| 5 | Steady state | Token/shell releases fan out like other kits; drift check reports lag | All active front-end repos pass |

## Ownership

- Hub: tokens, shell package, check, fan-out.
- Sites: zer0 theme family (zer0-mistakes) adopts the tokens.
- Each repo: its fan-out PR and evidence.

## Open questions

- Package distribution (npm via GitHub Packages vs vendored build).
- Whether gitorio's archify chrome converges on the shell or only on tokens.
