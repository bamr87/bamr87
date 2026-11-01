<!-- kit: sdlc v0.1.0 · ADR index (UPS-WORK-04, decision D2: law-ai format) -->
# Architecture Decision Records

> Decisions for bamr87 that are hard to reverse — the stack, data model, security model, public interfaces, and any relaxation of a gate — one file each.

Add an ADR in the same PR as the change it justifies.

## Format

- File name: `NNNN-short-kebab-title.md`, where `NNNN` is a four-digit sequence (`0001`, `0002`, …). Never renumber; a skipped number stays skipped.
- Start from [`0000-template.md`](0000-template.md).
- Required sections: **Status**, **Context**, **Decision**, **Consequences**, **Alternatives considered**, **Supersedes / Superseded by**.
- Status values: `proposed`, `accepted`, `superseded`, `deprecated`. A superseded ADR is never deleted; it links forward to the ADR that replaced it.
- Optional header field **Tracking**: `- **Tracking**: #N`, the issue or epic that delivers the decision.

## Lifecycle

- **Proposed** in the PR that adds the ADR, or that adds a phase section with its own `- **Status**: proposed` line.
- **Accepted by the merge.** The maintainer's merge of that PR accepts it (the maintainer's ruling of 2026-11-01, amendment `ratification-records`). Because the merge is the decision, a PR that adds or changes an ADR is gated (constitution § 12.3): no agent merges it. The post-merge `ratify` job in [`jev-number.yml`](../../.github/workflows/jev-number.yml) then sets that line to `accepted` (the rest of the line stays), adds `- **Accepted in**: <PR URL> (merged YYYY-MM-DD by @login)` under it, and sets the status cell of the row below (header line only). A PR merged by anyone else, from one of the hub's automation branches or opened by a bot accepts nothing. GitHub cannot tell the maintainer's own merge from one made with `FLEET_TOKEN` (both read `bamr87`); the gate is what makes `merged_by` mean the maintainer, and until a distinct bot identity exists that rests on § 12.5 being kept.
- **Completed when the tracking epic closes.** When the maintainer closes the issue named by **Tracking** as completed and every one of its sub-issues is closed, the job adds `- **Completed**: YYYY-MM-DD (#N closed)` to the header of an accepted ADR. An issue closed by anyone else, or as not planned, leaves it pending.
- **Accepted in** and **Completed** are written by the job through a ratification-record PR (constitution § 12.3), never by hand. Run `python3 -m tools.jev ratify plan` to see what it would record ([docs/JEV.md](../JEV.md#ratification-records)).

## Index

| ID | Title | Status |
| --- | --- | --- |
| 0001 | [Record architecture decisions](0001-record-architecture-decisions.md) | accepted |
| 0002 | [Agent step specs and the local loop runner](0002-agent-step-specs-and-local-runner.md) | accepted |
