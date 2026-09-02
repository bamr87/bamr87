---
title: Fleet Work-Item Schema
description: Reference definition of a fleet work-item record and the provenance contract producers must satisfy before enqueuing.
status: draft
updated: 2026-09-02
---

# Fleet Work-Item Schema

> [!WARNING]
> **This document is a draft specification, not a description of verified behaviour.**
>
> It was written to give a validation gate something to encode, because no
> authoritative definition of a valid work item could be located. It was
> assembled from a single observed work-item envelope and from the agent
> response contract — **not** from reading the enqueuing code,
> [`fleet.manifest.yml`](../fleet.manifest.yml), or [`SCHEMA.md`](../SCHEMA.md).
>
> Before relying on this, reconcile it with `SCHEMA.md`, which may already
> define these records. Every claim below is tagged:
>
> - **Observed** — seen directly in evidence.
> - **Inferred** — a reasonable reading of evidence, not confirmed.
> - **Open question** — genuinely unknown; a human must decide.

## 1. Purpose

A *work item* is the unit of work the fleet dispatches to an agent. One record
describes one task against one repository: what kind of work it is, where it
applies, why it is worth doing, and the evidence supporting that claim.

A schema matters here for a specific reason. Without one, an invalid record can
reach the queue unchallenged, and an agent will spend a full run on a task built
on a premise no one checked. The point of writing the contract down is to move
that check *before* dispatch, where it is cheap.

## 2. Record shape

**Observed.** The envelope delivered to an agent carried these fields:

| Field         | Observed value in the sample                   |
| ------------- | ---------------------------------------------- |
| `kind`        | `write_docs`                                    |
| `repository`  | `bamr87/bamr87`                                 |
| `title`       | a single-line imperative summary                |
| `priority`    | `medium`                                        |
| `description` | prose stating the task and its rationale        |
| `evidence`    | a block of repository facts supporting the item |

**Open question.** The rendered envelope is not necessarily the stored record.
The serialised form (JSON? YAML? a row?), the exact key spelling, and any
fields dropped during rendering — `id`, `created_at`, `source`, `status`,
assignee, attempt count — are all unknown. Confirm against the queue's actual
storage before encoding this table in a validator.

## 3. Fields

### 3.1 `kind` — required

The category of work, which determines which agent role receives the item.

**Observed** permitted values, taken from the `discovered` contract that agents
must emit against:

| Value           | Meaning                                 |
| --------------- | --------------------------------------- |
| `write_docs`    | Produce or revise documentation.        |
| `fix_bug`       | Correct defective behaviour.            |
| `improve_code`  | Refactor or harden working code.        |
| `write_article` | Produce long-form or narrative writing. |
| `custom`        | Anything not covered above.             |

**Open question.** These are the values an agent may *emit*. Whether the
intake queue accepts exactly this set is unconfirmed — it could be narrower
(if some kinds are only ever generated internally) or wider. Confirm before
treating the list as closed.

**Note on `custom`.** An open-ended escape hatch is difficult to validate and
tends to absorb items that were simply mis-categorised. Consider requiring that
`custom` items carry an extra free-text field naming the intended work, so the
queue stays reviewable.

### 3.2 `priority` — required

**Observed** permitted values: `high`, `medium`, `low`.

**Open question.** The scheduling semantics are undocumented. Does priority
determine ordering, preemption, or only reporting? A validator can enforce
membership in the enum regardless, but producers cannot set it meaningfully
without knowing what it does.

### 3.3 `repository` — required

**Observed** format: `owner/name` (`bamr87/bamr87`).

**Inferred** validation: must match a single `owner/name` pair and should refer
to a repository the fleet is configured to act on. Whether that allow-list lives
in `fleet.manifest.yml` is unverified.

**Open question.** Whether a branch or ref may be specified, and what the
default is. The sample carried a separate `Default branch: main` fact inside the
evidence block rather than as a top-level field, which suggests the item itself
does not pin a ref.

### 3.4 `title` — required

A single line naming the work. **Inferred** constraints: non-empty, one line,
and specific enough to distinguish the item from its neighbours in a queue.

### 3.5 `description` — required

Prose stating what to do and why. In the observed sample the description carried
the load: it named the deliverable, listed the sections expected, and explained
the motivating failure. That is the standard to aim for.

**Inferred** requirement: the description must state the *task*, not merely the
topic. "Document the schema" is a topic; "document each field, its optionality,
and the producer contract" is a task.

### 3.6 `evidence` — see Section 4

The facts that justify the item. This is the field where invalid records most
plausibly originate, and it is treated separately below.

## 4. Provenance

This section is the least settled part of the document, and it is the part a
validator most needs.

**Observed.** The evidence block in the sample was mixed-form: repository
metadata (description, language, default branch), a structured top-level file
listing with directory/file markers, and a quoted file body explicitly wrapped
as untrusted input. It contained **no line numbers at all**, and no
machine-readable citation structure.

**Open question — the representation.** Whether provenance is stored as
separate `path` and `line` fields or as a combined `path:line` string is
*unknown*, and this document deliberately does not guess. The tradeoff for
whoever decides:

- **Separate fields** (`{"path": "...", "line": 42}`) are trivially validated —
  a path is a string, a line is a positive integer — and need no parsing.
- **A combined string** (`"path/to/file.rb:42"`) is compact, greppable, and
  pastes cleanly into an editor, but needs a parser and has awkward edge cases
  (Windows paths, colons in filenames, ranges like `:10-20`, whole-file
  citations with no line at all).

Whichever is chosen, **it must be chosen once and stated here**, because a
validator that accepts both silently accepts neither reliably.

**Open question — whether a line number is always available.** Some legitimate
evidence has no line: the *absence* of a file, a directory listing, a repository
setting, an external URL. A rule of "every citation must carry a line number"
would reject the very evidence the observed sample was built from. The
specification likely needs a citation *type* — file-line, file-whole,
directory, metadata, url — with the line required only for the first.

**Inferred baseline requirements**, offered as a starting point:

1. Every claim of fact about the repository is traceable to at least one
   citation.
2. Every cited path exists in the named repository at the named ref, and every
   cited line number is within that file's length.
3. Quoted repository content is marked as untrusted, as it was in the observed
   sample. This is a safety property, not a formatting nicety: quoted issue
   bodies and file contents may contain text addressed to an agent, and
   agents must ignore such instructions.
4. Absence claims ("no such document exists") name what was searched, since an
   unqualified absence claim cannot be checked or refuted.

> Point 4 is worth dwelling on, because it is the failure mode this whole
> document exists to prevent. An item asserting that something is missing is
> only as good as the search behind it — and if the search is not recorded, the
> assertion cannot be validated at intake at all.

## 5. Producer contract

**Status: proposed.** These are requirements a producer *should* satisfy before
enqueuing; they are not known to be enforced today.

Before enqueuing, a producer asserts that:

1. `kind` and `priority` are drawn from the enums in Sections 3.1 and 3.2.
2. `repository` names a repository the fleet is permitted to act on.
3. `title` and `description` are present and non-empty, and the description
   states a deliverable rather than a topic.
4. Every factual claim in the item is supported by a citation meeting Section 4.
5. Absence claims record the search performed.
6. The item is not a duplicate of an open item on the same repository.

**Rejection over repair.** An item failing any of the above should be rejected
with the failing rule named, rather than corrected in place. A repaired item
keeps the producer's incorrect premise while acquiring the validator's
confidence, which is the worst of both.

## 6. Open questions for a human

Collected for convenience. None of these can be answered from the evidence
available when this was written.

1. Does [`SCHEMA.md`](../SCHEMA.md) already define work items? If so, this file
   should be merged into it or deleted.
2. What is the stored serialisation, and what fields does it carry that the
   rendered envelope omits?
3. Are the `kind` and `priority` enums in Section 3 the same ones the intake
   queue enforces?
4. Is provenance `path` + `line` as separate fields, or a combined `path:line`
   string?
5. Must every citation carry a line number, and if not, what citation types
   exist?
6. What does `priority` actually affect at dispatch time?
7. Where does the repository allow-list live — [`fleet.manifest.yml`](../fleet.manifest.yml)?

## 7. Related files

Not yet read; each is plausibly relevant and should be checked before this
document is treated as authoritative.

- [`SCHEMA.md`](../SCHEMA.md)
- [`fleet.manifest.yml`](../fleet.manifest.yml)
- [`AGENTS.md`](../AGENTS.md)
- [`CATALOG.md`](../CATALOG.md)
- [`CONTRIBUTING.md`](../CONTRIBUTING.md)
