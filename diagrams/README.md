# diagrams/

Illustrations of the six-layer harness and its loops, drawn as **typed, validated diagrams** rather than hand-made pictures. Each `<name>.<type>.json` is an [archify](https://github.com/tt-a1i/archify) specification (`type` ∈ architecture | workflow | sequence | dataflow | lifecycle); the vendored skill at `.claude/skills/archify/` compiles it into the self-contained interactive `<name>.<type>.html` beside it, which the dash serves at `/diagrams/` and embeds on [`/harness/`](../pages/_dash/harness.md).

| Diagram | Shows |
| --- | --- |
| `harness-layers.architecture` | The six layers as components of the hub; the model and the human outside the boundary |
| `fleet-pulse.workflow` | The daily loop: gather → scorecard → one `publish-data` commit → remediate queue → doctor → draft PR / fallback issue |
| `fleet-signals.dataflow` | GitHub signals → `dash-gen` → `_data/*.yml` → fix queue (agent) + scorecard (people) |
| `issue-pipeline.lifecycle` | The label state machine, with `agent:hold`, `human-review`, and `agent:blocked` as non-terminal gates |
| `repo-evolution.sequence` | The weekly cross-repo loop: plan and probe before paying; a draft PR into the submodule's own upstream |

## Regenerate

```bash
tools/render-diagrams.sh            # validate + deliver every *.json → *.html
tools/render-diagrams.sh --check    # validate only
```

Edit the JSON, never the HTML — `*.html` is generated and excluded from the formatters. Validation is showcase-strict; a non-zero exit means the diagram was not accepted. Background and authoring notes: [`docs/HARNESS.md`](../docs/HARNESS.md) § Illustrated.
