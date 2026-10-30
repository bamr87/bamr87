# docs/amendments/proposed/ — unnumbered amendment records

One file per proposed constitution amendment, named by slug and carrying `**Number:** NEW`. `python3 -m tools.jev number apply` assigns the next free number on `main`, renames the record to `../NNNN-<slug>.md`, and appends its row to [the index](../README.md) ([amendment 0002](../0002-conflict-free-numbering.md)).

Two proposals opened in the same week both read the log, both see `0001`, and both write `0002-*.md`. Git does not report that as a conflict — the files have different names — so the collision is only found later, by a reader or by `governance_lint.py`. Proposing by slug makes the collision impossible: the number is assigned once, by the process that can see every other pending proposal.

Copy [`../0000-template.md`](../0000-template.md), name the file `<kebab-slug>.md`, and write:

```markdown
# NEW — Title of the amendment

- **Status:** proposed
- **Number:** NEW
- **Date:** YYYY-MM-DD
- **Proposed by:** who (human or agent)
- **Ratified by:** the merged PR URL (leave blank until merged)
- **Affects:** constitution §N; PRD FR/NFR refs; feature ids (or `none`)
- **Supersedes:** none
```

The process is unchanged (constitution § 8): the pull request carries the record **and** the edit to `docs/constitution.md` it describes, an agent never approves or merges its own amendment, and merging the pull request ratifies it. Only the number moves — from the author's guess to the compiler's assignment.
