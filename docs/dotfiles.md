---
title: Root dotfiles (.zshrc, .zprofile, .gitconfig)
description: What the home-directory dotfiles tracked at the repository root are for, and how to use them without clobbering your own shell configuration.
---

# Root dotfiles

This repository tracks three files at its root that share their names with
home-directory configuration files:

| File | Normally lives at | Read by |
| --- | --- | --- |
| `.zshrc` | `~/.zshrc` | Zsh, for every interactive shell |
| `.zprofile` | `~/.zprofile` | Zsh, once per login shell |
| `.gitconfig` | `~/.gitconfig` | Git, as the per-user configuration |

Because the repository root also holds site content (`_config.yml`, `index.md`,
`pages/`), tooling config (`.editorconfig`, `.prettierrc`,
`.pre-commit-config.yaml`), and a `Rakefile`, it is easy to misread these three
files as something the project applies to your machine. This page exists to
remove that ambiguity.

## ⚠️ Do not copy or source them blindly

`~/.zshrc`, `~/.zprofile`, and `~/.gitconfig` are *yours*. Copying the versions
from this repository over them will silently destroy your aliases, your `PATH`
adjustments, your prompt, and — in the case of `.gitconfig` — your commit
identity, signing configuration, and credential helper settings.

In particular, **do not** run anything of the shape:

```sh
# DON'T: overwrites your personal configuration with no backup
cp .zshrc ~/.zshrc
ln -sf "$PWD/.gitconfig" ~/.gitconfig
```

unless you have already backed up the originals and read the incoming files in
full.

## Intended usage

> **Status: to be confirmed by the maintainer.**
>
> At the time of writing, no bootstrap script, `rake` task, or setup command in
> this repository is *documented* as installing these files into `$HOME`. Until
> that is confirmed one way or the other, treat them as **version-controlled
> reference copies**: read them, borrow from them, but install nothing
> automatically.
>
> If you are the maintainer, please replace this block with the definitive
> answer — and, if an install step exists, the exact command to run. See the
> checklist at the bottom of this page.

### Reading them safely

Inspect the files before doing anything with them:

```sh
cat .zshrc
cat .zprofile
cat .gitconfig
```

### Comparing against your own configuration

A diff is the safest way to see what adopting a file would change:

```sh
diff -u ~/.zshrc    .zshrc    || true
diff -u ~/.zprofile .zprofile || true
diff -u ~/.gitconfig .gitconfig || true
```

(`|| true` keeps the command from reporting a non-zero exit status just because
the files differ.)

### Adopting parts of them

If you decide you want something from these files, prefer copying the specific
lines you want into your existing configuration over replacing the whole file.
If you really do want to adopt a file wholesale, back up first:

```sh
cp ~/.zshrc ~/.zshrc.backup."$(date +%Y%m%d%H%M%S)"
```

For Git specifically, you can pull in this repository's settings *without*
replacing your own file by using an include directive in `~/.gitconfig`, which
lets your own values continue to take precedence if you place it near the top:

```ini
[include]
    path = /absolute/path/to/this/repo/.gitconfig
```

Remove the include line to undo it. Verify what Git actually ended up with:

```sh
git config --list --show-origin
```

## Related files

These are separate concerns and are *not* home-directory dotfiles, even though
they sit in the same directory listing:

- `.editorconfig`, `.prettierrc`, `.prettierignore`, `.markdownlintignore` —
  per-repository editor and formatter settings, applied automatically by the
  relevant tools when you work in this checkout.
- `.pre-commit-config.yaml`, `.husky/` — commit-time hook configuration.
- `.devcontainer/`, `docker-compose.yml` — containerised development
  environment definitions.
- `.env.example` — a template for local environment variables; copy it to your
  own `.env` rather than editing the example in place.

## Maintainer checklist

To finish this page, confirm the following and edit the **Intended usage**
section accordingly:

- [ ] Does any script under `tools/`, any task in the `Rakefile`, or any
      workflow in `.github/` install these files into `$HOME`? If so, document
      the exact command here.
- [ ] Does `.devcontainer/` copy, mount, or source them when the container is
      built? If so, say so — that makes them active configuration inside the
      container, not reference material.
- [ ] Is `.gitconfig` intended as *repository-local* Git configuration (for
      example via `core.hooksPath` or an `include.path` entry) rather than a
      `$HOME` file? If so, reframe the table above.
- [ ] Does `.gitconfig` contain personal identity, signing, or credential
      values that should not be adopted by anyone else? If so, call that out
      explicitly.
- [ ] Once answered, delete this checklist and the "Status" caveat.

A quick starting point:

```sh
git grep -n -e zshrc -e zprofile -e gitconfig -- Rakefile tools .devcontainer .github docker-compose.yml
```
