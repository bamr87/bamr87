### Security
- `site-quality.yml` runtime: the `basic-ftp` override moves from 6.2.3 to the patched 6.2.6, so the transitive copy under `@lhci/cli` and `pa11y` (via `get-uri`) resolves to the fixed release; the exact 6.2.3 pin had kept Dependabot from applying the advisory update.
