### Changed

- `_data/roadmap.yml`: roadmap ids (`FF-NNNN`) are now assigned at merge. A new entry is a fragment `_data/roadmap.d/<slug>.yml` with `id: FF-NEW`, cited elsewhere as `FF-NEW:<slug>`; `python3 -m tools.jev number apply` numbers it on `main` and appends it, and `number lint` rejects a hand-picked `- id: FF-NNNN`.
