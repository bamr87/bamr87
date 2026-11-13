# tools/weekly/ — the weekly routine

> Friday closes the week, Saturday prepares the next one, Sunday plans it. Each stage reads and reports; `tools/dash weekly confirm --apply` is the only external write, and it never merges or closes. Operator doc: [`docs/WEEKLY.md`](../../docs/WEEKLY.md).

```bash
tools/dash weekly                    # the latest run of each stage
tools/dash weekly close              # Friday, as a preview: saves locally, reports, changes no repo
tools/dash weekly prepare            # Saturday: can next week's scheduled activities run
tools/dash weekly plan               # Sunday: the plan, the week day by day, the Monday brief
tools/dash weekly confirm            # dry run of every external write; --apply is the maintainer's yes
tools/dash weekly brief close        # the Grok bot's brief for a stage (close | prepare | plan)
python3 tools/test_weekly.py         # and test_weekly_dispositions.py, test_weekly_harness.py, test_weekly_stages.py
```

| Module | Stage | What it does |
| --- | --- | --- |
| [`cli.py`](cli.py) | all | The command line. `auto --scheduled` is what the LaunchAgent calls: it runs every stage that is due this weekend and has not run, in order, so a slot missed while the Mac slept is made up at the next one. |
| [`core.py`](core.py) | Friday | Inventory of the hub and every submodule, proof of what is merged, the local save, refresh and tidy behind the report-only runs, the ranking, the chronicles and the retro. Also `confirm`. |
| [`closeout.py`](closeout.py) | Friday | One disposition for every open pull request and issue, from the decision index and the PM review. It reads each merge candidate from live GitHub once, so "ready to merge" means the review gate (constitution § 12.3) has been read, not only that GitHub shows green. It is a list: the module holds no call that writes. |
| [`prepare.py`](prepare.py) | Saturday | Every workflow scheduled for the coming week, when it fires, and whether it can run: its switch, its last result, the credential ledgers, the month's AI spend against its ceilings, the freshness of the data the agents read, and this Mac's own jobs. |
| [`agenda.py`](agenda.py) | Sunday | Lifts what the Grok half handed off into the ranking, lays the week out day by day and writes the Monday brief. |
| [`harness.py`](harness.py) | all | The split of constitution § 26. Claude Code executes: one capped, sandboxed, read-only session over Friday's stale items, through the incident reflector's runner, inside `budget.loops`. Grok bots direct: a brief a stage ([`briefs/`](briefs/)) and the week's direction issue, which is the only thing the two halves pass to each other. |

A run is a folder under `.fleet/weekly/` (gitignored): `run.json`, `report.md`, and what the stage produced (`inventory.json`, `closeout.json`, `lists/`, `agent/`, `prepare.json`, `grok-brief.md`, `posts/`). Friday's also saves bundles and snapshots to `~/bamr87-archive/weekly/<run>/`.
