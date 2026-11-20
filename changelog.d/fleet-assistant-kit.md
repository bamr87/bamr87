### Added

- `templates/assistant/` (`@bamr87/fleet-assist`, kit 0.1.0): the fleet's page bridge as one framework-free payload, `fleet-assist.js`, with adapters for Jekyll, MkDocs, plain HTML, Django templates, React and Next.js. A page that carries it can be shared with the Harness Console on the same machine, and a Claude Code session paired by a single-use code can then see it and, as far as the person on it allows, use it. Spec: `specs/ASSIST.md` (UPS-AST). Seeded with `tools/fanout.sh --kit assist`; `tools/dash apps assist` lists the baseline each repo's platform gets.
