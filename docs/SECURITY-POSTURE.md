# Security posture

> A weekly, read-only OpenSSF Scorecard sweep of every public registry repo, recorded as the `security:` block of the conformance snapshot and shown as the dash's `scorecard` column. It files nothing and changes nothing.

`tools/conformance.py` measures each repo against the Universal Project Standard, and none of its checks are about security posture. The live security debt was found by hand instead ([#460](https://github.com/bamr87/bamr87/issues/460): a public secret-scanning alert; [#461](https://github.com/bamr87/bamr87/issues/461): one critical and 25 high Dependabot alerts, about 23 high code-scanning alerts). The sweep adds a standing, comparable signal next to the UPS results ([#513](https://github.com/bamr87/bamr87/issues/513)).

| | |
| --- | --- |
| **Tool** | [`tools/scorecard_snapshot.py`](../tools/scorecard_snapshot.py): `targets`, `ingest DIR`, render, `--write`, `--check` |
| **Loop** | [`.github/workflows/scorecard-sweep.yml`](../.github/workflows/scorecard-sweep.yml), Sundays 06:17 UTC, off until `vars.SCORECARD_SWEEP_ENABLED` is `true`; a manual dispatch always runs (`dry_run` defaults to true) |
| **Config** | [`_data/fleet.yml`](../_data/fleet.yml) `schedule.scorecard_sweep` |
| **Output** | `security:` in [`_data/conformance.yml`](../_data/conformance.yml), rendered from the raw cache `_data/scorecard.yml` |
| **Surface** | Harness Console → Projects, the `scorecard` column (hover for the per-check scores) |
| **Tests** | [`tools/test_scorecard_snapshot.py`](../tools/test_scorecard_snapshot.py), `test_security_join` in [`tools/test_tui_fleet.py`](../tools/test_tui_fleet.py) |

## How it runs

1. **plan** lists the registry repos on github.com, skipping archived ones (`scorecard_snapshot.py targets`).
2. **scan** runs one matrix job per repo. A repo the job token cannot read as public is skipped: the sweep is public-only. The rest run the Scorecard CLI container (`gcr.io/openssf/scorecard:stable`) with `--format=json` and the seven checks below, using the job's own `GITHUB_TOKEN` with `contents: read`.
3. **publish** folds the JSON into `_data/scorecard.yml` (`ingest`, details dropped; a repo whose scan failed keeps its last result), splices the block into `conformance.yml` (`--write`), proves it (`--check`), and publishes both files through `.github/actions/utilities/publish-data` with auto-merge off. A dispatch with `dry_run` uploads them as an artifact and publishes nothing.

Each repo is recorded as `{date, commit, checks: {name: score}, aggregate}`. Scores run 0–10. Scorecard's `-1` (inconclusive) is kept as `-1` and shown as `?`, never as a failure.

## The checks

| Check | Why it is in |
| --- | --- |
| Branch-Protection | Default-branch rules. Without admin read, the job token often gets an inconclusive answer, shown as `?` |
| Token-Permissions | Workflows default to least privilege (the hub's own `permissions` lint rule) |
| Dangerous-Workflow | `pull_request_target` and script-injection patterns |
| Code-Review | Changes land through reviewed pull requests |
| Security-Policy | A `SECURITY.md` exists |
| SAST | Static analysis runs on pull requests |
| Vulnerabilities | Open OSV advisories against the dependencies |

**Pinned-Dependencies is excluded.** The fleet's dependency policy is always-latest: no exact pins, no ceilings, actions ride major tags ([DEPENDENCIES.md](DEPENDENCIES.md)). Scorecard's check rewards exactly the opposite, so it would fail every repo by design and its score would carry no information. The exclusion is in the generator (`EXCLUDED`) and is written into every snapshot's `excluded:` key.

## Decisions

- **Read-only, no new secret.** The `fleet.yml` token contract has no read-only cross-repo token (`FLEET_TOKEN`, `PROJECTS_TOKEN`, `RELEASE_PLEASE_TOKEN` and `NPM_TOKEN` can all write), so the sweep uses the job token against public repos. The cost is that private repos are not swept and Branch-Protection is often inconclusive.
- **The CLI, not the public API.** `api.securityscorecards.dev` serves only repos in OpenSSF's own crawl, and it returned 404 for `bamr87/zer0-mistakes` on 2026-11-05. The CLI scores any public repo.
- **No issues filed.** fleet-pulse's doctor stays the fleet's one issue filer ([DAILY-ANALYSIS.md](DAILY-ANALYSIS.md)). The snapshot is an input for it, for `repo-evolution`'s brief and for `repo-scout`, never a second filer.
- **The block survives local regeneration.** `tools/dash spec fleet --write` rewrites `conformance.yml`, and it carries the `security:` block over byte for byte (`conformance.security_span`). The block is always the file's last top-level key.
- **Constitution § 10.8 survey:** Scorecard adopted (read-only); Allstar skipped, because it opens issues and would be a second filer beside fleet-doctor.

## Operating it

```bash
python3 tools/scorecard_snapshot.py            # print the block the cache renders
python3 tools/scorecard_snapshot.py --check    # exit 1 if conformance.yml's block was hand-edited or not re-rendered
python3 tools/test_scorecard_snapshot.py       # offline fixture tests
gh workflow run scorecard-sweep.yml -f target=zer0-mistakes -f dry_run=true   # one repo, artifact only
```

To arm the weekly run, set the repository variable `SCORECARD_SWEEP_ENABLED` to `true`. Never edit the `security:` block or `_data/scorecard.yml` by hand: `--check` fails on either.
