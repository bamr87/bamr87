### Fixed

- `tools/check-drift.sh` check (d) now runs `tools/docs_index.py --lint`, so a documentation lint failure fails the drift gate instead of passing unseen (#503). The PRD's FR45 points at HUB-048, the eval baseline it describes, instead of HUB-049 (#500).
