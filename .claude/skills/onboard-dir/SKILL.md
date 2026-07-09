---
name: onboard-dir
description: Adopt (or remove) a project directory that exists on disk under projects/ but is in neither .gitmodules nor the registry. Use when the drift gate flags a stray/unregistered project dir.
---

# onboard-dir

The drift gate (`tools/check-drift.sh`) now hard-fails on any `projects/*/` dir
that is in neither `.gitmodules` nor `_data/projects.yml`. This skill resolves it.

## Steps
1. Identify the stray dir (the DRIFT line names it) and inspect it:
   ```bash
   ls projects/<name>; git -C projects/<name> remote -v; git -C projects/<name> log -1
   ```
2. **Decide with the user: onboard or remove.**

### Onboard (it's a real project with its own remote)
```bash
git submodule add -b <branch> <remote-url> projects/<name>
```
- Add a matching entry to `_data/projects.yml` (or run `/register-project`):
  `submodule_path: projects/<name>`, correct `branch`, `category`, `status`,
  and a `tier`/`license` if not derivable.
- `tools/dash-gen readme` (refresh the README AUTO span).
- `tools/dash audit <name>` (check it against its tier baseline).
- `tools/check-drift.sh` (confirm parity is restored).

### Remove (stray / superseded / not wanted)
Confirm there's no uncommitted or unpushed work first:
```bash
git -C projects/<name> status --short && git -C projects/<name> log --oneline @{u}..HEAD
rm -rf projects/<name>
```
The dir's own remote repo (if any) is untouched.

## Guardrail
Never `rm -rf` a dir with uncommitted or unpushed commits without surfacing it and
asking. If it has a `.git` and a remote, default to onboarding, not deleting.
