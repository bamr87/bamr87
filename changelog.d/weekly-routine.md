<!-- changelog.d/weekly-routine.md -->
### Added

- `tools/dash weekly` (`tools/weekly/`): the weekly routine, one stage a day from one LaunchAgent (`tools/install-weekly.sh`). `close` (Friday) saves everything that exists only on the Mac, refreshes to main, gives every open pull request and issue one disposition, and has one capped Claude Code session propose what to do with the stale ones. `prepare` (Saturday) checks that each activity scheduled for next week can run. `plan` (Sunday) builds the plan, the week day by day and the Monday brief. `confirm --apply` is the only external write (`wip/` pushes, Fleet project ops, the weekly PR); the routine lists what is ready to merge and what is stale, and never merges or closes. `tidy [--apply]` accounts for the folders beside the hub (`~/bamr87-*`) and removes the worktrees among them proven safe, keeping their branches. `brief <stage>` prints the Grok bot's half. See [docs/WEEKLY.md](docs/WEEKLY.md).
- `_data/fleet.yml` `weekly:` (the three slots, the close-out's rules, the agent's model and $2 cap inside `budget.loops`, the week's issue, the handoff label and who may write direction on it), and `harness.agents.local:weekly`.
- `/weekly` in Claude Code: run a stage as a preview and walk through it.

### Changed

- `tools/jev/reflect.py` `run_session` takes the ledger row's `source`, and an unledgered charge carries the caller's loop and step, so another one-session consumer runs under the reflector's posture with its own name on what it spent. The reflector's own rows are unchanged.
