---
title: Triaging a fleet backlog through a governed write path
date: 2026-11-04
categories:
    - devops
    - ai
tags:
    - github-projects
    - issue-triage
    - claude-code
    - governance
    - monorepo
excerpt: A Claude Code session reviewed 171 open issues in a 40-repo hub and could not touch the project board. What came out was better than a bot with write access — a reviewed plan, a confirm step, an audit log, and a tool the next pass reuses.
draft: true
lastmod: 2026-11-04T12:00:00.000Z
---

The ask was short: review the monorepo, then update and organize its GitHub project and open issues. The hub at [bamr87/bamr87](https://github.com/bamr87/bamr87) manages about forty submodules, and its issue tracker had grown to 171 open items: daily doctor tickets about red workflows, deep-dive findings, a map of agentic design patterns turned into twenty issues in one afternoon, roadmap mirrors, phase sub-issues of six epics, and a handful of backlog items the maintainer had typed in two days earlier with no labels at all. The Fleet project, user project 14, is the system of record by constitution, and most of that work was never put on it.

This post is about what a coding agent can and cannot do with that kind of request, and why the limits turned out to be the useful part.

## The wall: no GraphQL from a cloud session

GitHub Projects (v2) is a GraphQL-only API. The first thing the session learned is that its GitHub proxy refuses GraphQL outright, and the newer REST preview for Projects too: every request to `graphql` or `/users/bamr87/projectsV2/14` came back as a 403 with a note to use repository-scoped endpoints. Issues, labels, sub-issues, pull requests and workflow runs were all reachable. The board was not.

That could have ended the task at "cannot do it". Instead it split the work in two. The issue half can be planned and executed over REST from anywhere `gh` is logged in. The board half needs a machine where `gh api graphql` works, with a token that carries `read:project`. The tool that came out of the session handles both and says which one it is skipping, instead of failing or pretending.

## The rule that shaped the deliverable

The hub's constitution has a section, § 11, that governs every write an agent makes to GitHub: an allowlist of mutations, a dry run that produces a deterministic plan id, a human who sees the plan, and an apply step that only runs with an environment flag, the same plan id and an explicit confirm. There is a service for it already, `tools/console/gh_projects_write.py`, with caps of 50 operations a plan and 200 an hour, an append-only audit log and token redaction.

A session that is "operating autonomously" is tempted to read a rule like that as friction. It is the opposite. It means the correct output of a triage session is not 123 API calls but a reviewed file that compiles into 123 operations, and a command the maintainer runs when they agree with it. The file is [`_data/projects_backfill.yml`](https://github.com/bamr87/bamr87/blob/main/_data/projects_backfill.yml): every close, label change and sub-issue link, each with a `why:` line that names its evidence. Committing a change to that file is the review. Applying it is a second, explicit step, and every batch applied is appended to the file as a ledger entry.

## Evidence before opinion

The triage itself was mechanical once the evidence was in hand, and gathering it is where an agent earns its keep. For each of the 171 issues the session asked: which merged pull request references it, what does the referenced upstream fix look like now, and what is the latest run of the workflow the ticket is about?

Some findings from that sweep:

- The daily fleet doctor files one ticket per red workflow and dedupes against open issues, so tickets that say "not a workflow defect" in their own title stay open as placeholders. Ten of them described billing blocks and usage windows that had since cleared; those close as not planned. Two were filed the day before and still describe a live signal; those stay open on hold, so neither the issue pipeline nor the doctor touches them again.
- A release-please epic consolidated twelve per-repo failures. Its own status table from three days earlier showed ten of the twelve repos holding the new secret with a green Release run, which a fresh check of every repo's latest `main` runs confirmed. Those ten close as completed; the two repos still missing the secret keep the epic open, because only the maintainer can add a secret.
- Three submodule fixes the doctor had pointed at (an ocrmd CLI reference that depended on `$USER`, a zer0-CMS extension that packaged `AGENTS.md`, a pip-audit failure) had all merged weeks ago, with green runs since.
- The amendment log the deep-dive flagged as stale was already repaired by a later job, but the constitution's section 13 still comes before its section 12. The issue stays open, narrowed.
- Two priorities were wrong on the ticket's own evidence: a P0 "security" issue whose title says the CodeQL failure was collateral, and a P1 whose body says the behaviour it asks for already exists.

Everything else was labels. Sixty-five additions give every open issue a type and a priority from the pipeline's taxonomy, thirteen removals clear an alias label and a stale intake marker, and ten sub-issue links turn four umbrella issues into real epics with phases.

## What the tool does and refuses to do

`tools/dash projects plan` compiles the file into operations, reads each target's current state, and prints every batch as before → after with its plan id. Operations already satisfied are marked as such and cost nothing to re-run. `plan --board` adds the Fleet project items: an add for every open issue and PR missing from the project, then Status, Priority and Area for the ones already on it, derived from labels in the issue pipeline's own precedence. `apply FILE --confirm` writes through the service. It never merges, never deletes, never creates a label, never prints a token, and stops at the first error so nothing is half-applied.

The board plan is deliberately two passes. A project item has no id until it exists, so the first plan adds items and the second sets their fields. That is a property of the API, and writing it down in the tool is better than a clever workaround that hides it.

## Working with AI: what carried over

- **Give the agent the governance, not just the task.** A constitution that says "plan, show, confirm" produces a reviewable artifact instead of a surprise. The session spent its first twenty minutes reading rules, and that is what kept it honest later.
- **Ask for evidence in the output.** A `why:` column with a PR number, an upstream issue state or a run date is something a maintainer can spot-check in a minute. A triage without it is an opinion.
- **Make the human's approval a commit.** A decisions file in the repo is reviewable in a pull request, diffable against the last pass, and revertible one line at a time. A chat transcript is none of those.
- **Let caps and audit logs do the worrying.** Fifty operations a batch, two hundred an hour and an append-only log mean a wrong decision has a small blast radius and a paper trail.
- **Treat a closed door as information.** The session could not reach the board. It said so, built the part it could verify, and left the other part runnable from the right machine in one command. That is more useful than a tool that works only where it was written.

The pass is a pull request, not a fait accompli. If the file reads right, applying it is one command with the flag set. If a line reads wrong, that line changes and the plan id with it, and nothing was written in the meantime.
