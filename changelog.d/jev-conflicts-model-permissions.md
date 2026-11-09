### Fixed

- JEV conflict resolution (`tools/jev/conflicts.py`): a tier-1/2 model attempt now runs with an explicit, narrow tool grant (read, edit, stage, read-only local git) under `--permission-mode dontAsk`, with no MCP servers, and is refused at $0 on a CLI older than 2.1.259; the run's permission denials are recorded in the ledger. Before this a headless attempt inherited the operator's own rules, every edit was denied, and it reported `success` with the conflict untouched.
- JEV conflict validation reads only the files the merge touched and counts a marker-shaped line only when neither parent has it, so a seven-`=` reStructuredText underline or an article that quotes a conflict no longer fails every resolution in that repository.
