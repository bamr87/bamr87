<!-- Drop this section into your repository's CLAUDE.md verbatim. -->

## SCHEMA.md protocol (Pyramid Schema)

This repository is structured by `SCHEMA.md` files — one per directory, each a
lintable contract describing its own contents, one level deep. They are your
primary source of structural truth. Prefer reading the schema chain over
running `ls -R` / `find` to understand layout.

**Orient.** At the start of work, read `./SCHEMA.md`. Before touching any
directory, read its `SCHEMA.md` and, if placement is in question, the chain of
schemas from root down to it. `## Conventions` inherit from ancestors; the
nearest schema wins.

**Follow.** Place and name new files according to `## Placement` and
`## Structure` in the nearest schema. If nothing routes your file, do not
guess: add a row to the appropriate Structure table (and a Placement route if
it will recur), then create the file. Respect `## Forbidden`. Never hand-edit
entries marked `generated`. Never descend into directories marked `terminal`.

**Propagate.** Creating a directory is one atomic act with three parts:
1. Create the directory.
2. Create its `SCHEMA.md` from `templates/SCHEMA.template.md`, filling every
   placeholder — especially the one-line purpose.
3. Register it in the parent directory's Structure table.
Never leave a new directory schemaless.

**Maintain.** Any add / remove / rename updates the local `SCHEMA.md` in the
same commit as the change itself. Schema edits ride with the work they
describe. If you find drift you didn't cause, fix it and note it.

**Verify.** Before declaring a task done, run:

```
python tools/schema_lint.py check .
```

Fix errors. Surface warnings to the user with a one-line explanation each if
you choose not to fix them.
