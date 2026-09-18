# Consuming a ux-audit evidence bundle

You are fixing UX findings for this repository.

Inputs:
- `ux.yml` — surfaces and personas in scope
- `evidence/summary.json` + per-surface `screenshot.png` / `axe.json`
- stdout/log from `python3 scripts/ux_audit.py --root .`

Rules:
1. Only fix findings with evidence or an R-rule id.
2. Keep changes minimal and token-aligned; no drive-by redesign.
3. Re-run `python3 scripts/ux_audit.py --root .` before declaring done.
4. Do not dismiss findings by broadening exempt markers without a reason string.
5. Open a draft PR; do not merge.
