---
id: ADP-12
chapter: 12
title: Exception Handling and Recovery
book_pages: "Ch. 12 (8 pp.)"
status: partial
evidence_repos: [bamr87/bamr87]
last_verified: 2026-10-31
owner_bot: executor (Grok Bot)
---
# Exception Handling and Recovery

## Summary

Agents in the real world hit broken tools, bad credentials, overloaded APIs and malformed output. The pattern is a loop of **detect → handle → recover**: classify the failure, choose a response (log, retry, fall back to an alternative, degrade gracefully, or escalate to a human), then restore a stable state (rollback, self-correction, re-planning). Gulli frames it as making agents "robust and reliable" under unpredictable conditions (book ch. 12, "At a Glance"). The key discipline is *not* treating all errors alike: transient faults get retries, credential faults get a different credential, logic faults get escalation, and nothing fails silently.

## When to use / not

- Use: any unattended agent loop, external API calls, scheduled automation.
- Avoid: blind retries of non-idempotent work (re-running a task that already spent its budget or wrote state).

## Failure modes

- Silent swallowing.
- Retry storms.
- Fallback on the credential most likely to be dead.
- Recovery that discards partial work.

## Fleet evidence (`bamr87/bamr87@2321b3a`)

| Behavior | Permalink |
|---|---|
| Failure classifier (budget / quota / auth / transient / model) | [run.sh L225-238](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/run.sh#L225-L238) |
| Operator hint per class (escalation text, secrets redacted L221) | [run.sh L240-260](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/run.sh#L240-L260) |
| Fallback chain across auth methods (OAuth → API key), spend recorded before fallback | [run.sh L266-300](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-run/run.sh#L266-L300) |
| Bounded retry (2 attempts) with structured `retry` events | [backlog_fanout.py L269-287](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/backlog_fanout.py#L269-L287), [L354-358](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/backlog_fanout.py#L354-L358); schema [fleet_activity.py L22-60](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/tools/fleet_activity.py#L22-L60) |
| Rejected credential vs rate-limit distinguished | [claude-cost/action.yml L175-186](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/actions/claude-cost/action.yml#L175-L186) |
| Alarm deliberately not riding on the likeliest-dead token | [api-keys.yml L19-25](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/api-keys.yml#L19-L25) |
| Timeouts + concurrency guards (e.g. drift-check 15 min, cancel-in-progress) | [drift-check.yml L26-33](https://github.com/bamr87/bamr87/blob/2321b3a7c1199688042339d68b628f9d08bb46eb/.github/workflows/drift-check.yml#L26-L33) |

### Reproduce

```bash
git clone https://github.com/bamr87/bamr87 /tmp/hub && cd /tmp/hub && git checkout 2321b3a7c1199688042339d68b628f9d08bb46eb
python3 -m pytest -q tools/test_backlog_fanout.py       # retry/give-up paths
grep -n "claude_failure_class" -A10 .github/actions/claude-run/run.sh
```

Expected: tests pass (verified 2026-10-31: 42 passed together with ch.16 tests). Green CI: [Python tests run 41256758330](https://github.com/bamr87/bamr87/actions/runs/41256758330).

## Gaps

1. **Transient (529/503/overloaded) errors are not retried in-run**; run.sh L258 defers to "the next scheduled run". → Issue: https://github.com/bamr87/bamr87/issues/532.
2. Recovery discards work on max_turns termination — already tracked: [#238](https://github.com/bamr87/bamr87/issues/238).
3. API Key Watch itself is red (SDK change) — tracked: [#522](https://github.com/bamr87/bamr87/issues/522); last run [41178148423](https://github.com/bamr87/bamr87/actions/runs/41178148423) failed.

## Cross-links

ADP-16 (budget aborts are a failure class), ADP-19 (monitoring surfaces failures); constitution §15 testing evidence; #528 kill switches.
