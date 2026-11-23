---
title: An AI reviewer that cannot touch the pull request it reviews
date: 2026-11-23
categories:
    - devops
    - ai
tags:
    - github-actions
    - code-review
    - claude-code
    - security
    - pull-request-target
    - governance
excerpt: The ask was one sentence — after every pull request is marked ready, an AI agent reviews it, comments, and says who does what next. Most of the work was deciding what that agent must never be able to do, and then finding out another session was building the neighbouring feature at the same time.
draft: true
lastmod: 2026-11-23T12:00:00.000Z
---

The ask was one sentence: after every pull request that is marked for review, an AI agent should comment with its review and then delegate or recommend actions. The hub at [bamr87/bamr87](https://github.com/bamr87/bamr87) manages about forty repositories, and on a busy day agents open dozens of pull requests in it.

This post is about how that sentence became a workflow, and why most of the design is a list of things the reviewer cannot do.

## Read the rules before writing the code

The first hour produced no code. The repository has a constitution, and section 19.7 already said an AI review runs when a pull request is opened or marked ready, never on a push. An accepted decision record, ADR 0012, described the review as "stage B" of a four-stage path from opened to merged, and the kit's README listed it under "Not built yet" with the exact parts it would need: a pinned model, a dollar cap, a kill switch, an entry in the agent inventory.

So the request was not a new idea to design. It was a decision already made, waiting for someone to build it. That changes the work: the questions "should it run on every push" and "may it approve" were answered, with reasons, months earlier.

**Tip for working with an agent:** ask it to find the rule that governs a change before it proposes one. An agent that starts from the code will reinvent a decision the repository already recorded, and usually reinvent it slightly differently.

## The event that makes this dangerous

A GitHub Actions workflow that should react to "marked ready" has one usable trigger: `pull_request_target`. The ordinary `pull_request` event gives a fork's pull request no secrets, so it cannot call a model. `pull_request_target` runs the workflow file from the base branch with the repository's secrets, for any pull request, including one from a stranger.

That is the classic way to leak a credential. If the workflow checks out the pull request's code and runs anything from it, the stranger's code runs with your secrets. An AI agent makes it subtler: a coding agent loads settings, hooks and instruction files from its working directory, so checking the pull request out is enough, even if no step runs its code.

The reviewer here never has the pull request's files on disk. Its working directory holds three things: the hub's own tooling, the base branch (the code before the change), and the diff as text. The diff is data it reads, not a project it sits in.

## Three jobs, each holding only what it needs

| Job | What it can do | What it holds |
| --- | --- | --- |
| Plan | Read the pull request through the API, decide whether it gets a review, write the brief | A read-only token |
| Review | Read files. Nothing else: no shell, no network, no write | The model credential, and no GitHub credential |
| Post | Write one review and the inline findings | The token that can write on pull requests, and no model |

The model and the write token are never in the same job. The reviewer leaves two artifacts, and a different workflow, the one that already owns every comment in the fleet, posts them.

The model's reply is treated as untrusted twice. The job that ran the model keeps only what fits a fixed shape: a summary, findings with a severity, and actions. The job that posts validates the artifact again, believes it only when it came from a run of the base branch's workflow file, and escapes every word, so a diff that says "write `@someone approve this`" produces escaped text and not a mention.

## Delegation is a vocabulary, not free text

The second half of the ask was to delegate. The tempting design lets the model write the hand-off: "run this command", "ask this agent to do that". But the model reads text a pull request author wrote, so a command it prints is a command that author can influence, addressed to a maintainer who trusts the bot.

So the model chooses from three words: `agent`, `author`, `maintainer`. The sentence describing the work is the model's, escaped. The instruction for handing it off is fixed text in the code. For an agent it is one comment a maintainer posts, which starts the repository's existing mention handler. The review recommends and hands off; a person still starts anything that spends money.

## What the code scanner knew

The first draft checked the label in the job's condition: run when the `review` label is added. A sibling pull request, opened the same day by another session, had already learned that GitHub's code scanning reports that pattern as critical. A label checked on `pull_request_target` authorizes a pull request at one moment, and a push can arrive after it.

The fix has two parts. The label is read by the script, not by the workflow condition. And the script is told which commit the event carried: if the pull request has moved since, it posts one line saying so and reviews nothing.

## Designing for the merge

That sibling pull request added an AI analysis of failed CI runs to the same workflow, the same settings file and the same README. Both of us had added a settings block under the same new top-level key. Had both merged cleanly at different places in the file, the YAML would have had the key twice, and the parser keeps only the last one: half the settings would have vanished with no error.

So the second design pass was about the merge, not the feature. The settings got a key of their own. The posting step became a function call at the end of the existing pass, so the shared workflow file needed no new step at all. Each documentation section moved to a place the other change did not touch.

**Tip:** before opening a pull request in a busy repository, list the open ones that touch the same files and read their history. Their mistakes are free.

## Testing an AI feature without an AI

None of the 32 tests calls a model. The model's reply is a string a test writes, which is exactly how the code must treat it: a fake GitHub client answers the reads and records the writes. Other tests hold the workflow file to the settings file, so the model name, the turn cap and the dollar cap cannot drift apart, and assert the properties the design depends on: no checkout names a ref, no condition reads a label, no job has a write permission, the agent's environment has no GitHub token.

One assumption could not be tested offline: that a `pull_request_target` run is recorded against the pull request's head commit. A single read of the live Actions API settled it.

## What is not done

The reviewer ships switched off, as every new loop in this fleet does, and its findings are advisory. It has no eval set yet: about twenty past pull requests with the findings a review must and must not report. Until that exists it does not count toward whether a pull request is ready. It runs in the hub only; the other repositories get it through a later kit. And it does not start the fix by itself. That is the next stage, and it needs its own budget and its own brakes.
