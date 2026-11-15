---
description: Run a stage of the weekly routine (close on Friday, prepare on Saturday, plan on Sunday) and walk through what it found
allowed-tools: Bash(tools/dash weekly:*), Bash(tools/dash decisions:*), Bash(tools/dash conflicts scan:*), Read
argument-hint: '[close | prepare | plan | confirm] (default: the stage for today)'
---

Run the weekly routine for: $ARGUMENTS

This is the interactive entry to the routine a LaunchAgent runs unattended (`docs/WEEKLY.md`). You are the Claude Code half: you execute and report. Direction belongs to the Grok bots and to Amr (constitution § 26).

1. Pick the stage. With no argument, use today's: Friday `close`, Saturday `prepare`, Sunday `plan`, any other day `tools/dash weekly` (the latest run of each stage) and stop there.
2. Run it as a preview: `tools/dash weekly close`, `tools/dash weekly prepare` or `tools/dash weekly plan`. A preview changes no repo and writes nothing to GitHub. Add `--agent` to `close` only if Amr asks for the close-out agent: it is one model session, capped by `weekly.agent.usd`.
3. Read the report the command prints and the files it names. Lead with what waits on Amr, in the order that unblocks the most. Give counts as the report gives them, and say "ready to merge" only for rows the report says were read from live GitHub.
4. For `close`: name each list file under the run's `lists/` and what it is for. Do not merge, close, push or delete anything yourself.
5. For `confirm`: run `tools/dash weekly confirm` (a dry run) and show exactly what `--apply` would do: `wip/` pushes, Fleet project ops and the weekly PR. Run `--apply` only when Amr says to in this conversation, and repeat back what it did from its output. The routine never merges or closes. If Amr asks you to merge the ready list, that is a separate request: recheck each pull request live against constitution § 12 first.

Never: run `close --apply` or `confirm --apply` without Amr's explicit yes here; merge or close anything as part of this command; install or uninstall the LaunchAgent (`tools/install-weekly.sh` is Amr's to run, § 10.5).
