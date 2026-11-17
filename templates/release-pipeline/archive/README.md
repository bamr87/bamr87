# archive/

Byte-exact snapshots of `release.yml` as earlier kit versions shipped it, named `release-<version>.yml`. `tools/adopt-release.sh --upgrade` refreshes a repo's `.github/workflows/release.yml` only when it matches the current template or one of these (rendered with the repo's default branch), so a hand-edited copy is never overwritten. Snapshot the file here BEFORE changing the template. Snapshots: `release-0.1.0.yml` (the unversioned kit as first shipped, calling `release-please.yml@main` and `publish.yml@main`).
