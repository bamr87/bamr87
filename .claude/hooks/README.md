# .claude/hooks/ — session hooks

Shell/Python commands wired into Claude Code session lifecycle events via [`../settings.json`](../settings.json). They power the **Future-Features** pipeline so feature ideas are captured automatically in every session.

## Hooks

| Script | Event | What it does |
| --- | --- | --- |
| `future_features_session_start.py` | `SessionStart` | Injects `additionalContext` that makes the Future-Features workflow active: reminds Claude it can capture ideas with `/future-features` and should run the `feature-scout` sub-agent at natural stopping points. |
| `stars_session_start.py` | `SessionStart` | Injects the **starred-repo radar brief** ([docs/STARGAZER.md](../../docs/STARGAZER.md)): the account's GitHub stars most like the session's project (a submodule by its path, the hub, or a fleet repo by its `origin`), the newest stars and the trending repos like a fleet project, from the committed `_data/stars.json`; standard library only, no network. `STARS_SESSION_BRIEF=0` silences it; `--user` is the form `tools/dash stars hook --install --yes` puts in `~/.claude/settings.json` for sessions outside the hub. |
| `future_features_scout.py` | `Stop` | Scans the session transcript for feature-signal language in the **user's** messages; at most **once per session**, nudges Claude (`{"decision":"block","reason":…}`) to run the `feature-scout` sub-agent before stopping. |

## Design notes

- **Fail-open.** Any error or missing data → `exit 0` with no output. A misbehaving hook must never block a session.
- **Throttled.** The Stop hook writes a per-session marker under the system temp dir (`$TMPDIR/claude-future-features/<hash>.nudged`) and fires only once per session. It also respects `stop_hook_active` to avoid continuation loops.
- **Targeted, not noisy.** It only fires when feature-signal phrases ("it'd be nice if…", "we should add", "in the future", "roadmap", "enhancement", …) appear, after at least two user turns, and never on its own injected context (self-markers `future-features` / `feature-scout` are excluded from the scan).
- **No silent writes.** The hooks only _prompt_; the `feature-scout` sub-agent only _proposes_. Entries land in `_data/roadmap.yml` only after a human approves.

## Opt out

Set `FUTURE_FEATURES_AUTOSCOUT=0` (`off`/`false`/`no`) in the environment to disable the automatic scout nudge. SessionStart still injects the capability note, minus the auto-scout instruction.

## Test

```bash
# SessionStart emits valid context JSON
echo '{"session_id":"s1","source":"startup"}' \
  | python3 .claude/hooks/future_features_session_start.py | jq .

# Stop fires on a transcript that contains feature-signal language
printf '%s\n' \
  '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"a"}]}}' \
  '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"it would be nice if we added PDF export"}]}}' \
  > /tmp/t.jsonl
echo '{"session_id":"x","transcript_path":"/tmp/t.jsonl","stop_hook_active":false}' \
  | python3 .claude/hooks/future_features_scout.py | jq .
```

See also: [`../commands/future-features.md`](../commands/future-features.md), [`../agents/feature-scout.md`](../agents/feature-scout.md), and the backlog [`../../_data/roadmap.yml`](../../_data/roadmap.yml).
