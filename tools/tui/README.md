# tools/tui — terminal command center

The TTY twin of the Jekyll dash (`index.md` + `/monitor/`). Same registry, same health YAML, no second inventory.

```
tools/dash tui
```

Reads:

- `_data/projects.yml` — the fleet roster (committed)
- `_data/project_health.yml` — red/amber/green attention (ephemeral)

Missing health degrades to a banner (`run dash-gen health`) and still lists every project. Disk column is local checkout of `submodule_path`, not a new signal.

## Keys

| Key | Action |
|---|---|
| `/` | search |
| `s` | cycle sort (featured / name / health / alerts / recent / stars) |
| `c` | cycle category |
| `t` | cycle status |
| `h` | cycle health |
| `f` | featured only |
| `r` | reload YAML |
| `R` | `tools/dash-gen health` (GitHub) |
| `o` | open `repo_url` |
| `l` | open `live_url` |
| `q` | quit |

Tabs: **Apps** (command center) · **Monitor** (ranked board) · **Attention** (red/amber).

`d` refreshes Docker. Default `DASH_DOCKER_HOST=ssh://forge`. Tab **Forge** is `docker ps -a` on that host; the Apps **Forge** column joins containers to the registry.

Does not write, commit, or shell out except `dash-gen health` on `R` and `docker -H $DASH_DOCKER_HOST ps`. Compose must be started **on forge** — see [`docs/FORGE-HOST.md`](../../docs/FORGE-HOST.md). The credentialed write plane stays `tools/dash console`.
