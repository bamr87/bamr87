# Visual evidence for guides and tutorials

> Status: **proposed** (constitution § 24, amendment `visual-evidence`; epic [#678](https://github.com/bamr87/bamr87/issues/678), backlog [#679](https://github.com/bamr87/bamr87/issues/679)).
> Feature: `HUB-NEW` / slug `visual-evidence`. Requirement: `FR-NEW:visual-evidence`. Roadmap: `FF-0039`.
> Sub-PRD / user stories: [`docs/prd/VISUAL-EVIDENCE.md`](prd/VISUAL-EVIDENCE.md).

This is the hub's **guide** visual-evidence standard. Frontend *PR* evidence stays under constitution § 15 and [`VERIFICATION.md`](VERIFICATION.md). A change may need both.

## When visuals are required

Ship at least one screenshot, short recording, or GIF when the reader is told to:

- click, navigate, or configure something in a UI (including the Harness Console);
- install or set up a system, computer, or tool with a visible surface;
- compare what they should see on screen.

Skip only with a one-line reason in front matter:

```yaml
skip-visuals: "API-only contract; no user-visible surface"
```

## Storage and naming

| Kind | Path | Notes |
| --- | --- | --- |
| Durable guide art | `docs/assets/guides/<slug>/` | Preferred for docs and console help |
| Feature / scenario proof | `test/evidence/<slug>/` | Same bundles as § 15 / UPS-QA-52 |

- Filenames: kebab-case; viewport tag when size matters (`overview--desktop.png`, `overview--mobile.png`).
- Recordings: `.gif`, `.webm`, or `.mp4`.
- Reference from Markdown with a relative link and **meaningful alt text** (what the reader should notice). Decorative spacers are forbidden.

```markdown
![Harness Console home with the Apps rail expanded](../assets/guides/console-home/overview--desktop.png)
```

## Redaction

Before commit, redact tokens, secrets, credentials, keys, cookies, credential-bearing URLs, and unredacted PII (same bar as constitution § 23.3). Prefer a dedicated demo account and fake data. Never paste a secret into alt text or the PR body.

## Freshness

When a PR changes a UI that a guide depicts, update or re-capture the visuals in **that same PR**, or add `skip-visuals` with why. Stale screenshots are defects.

## Lint

```bash
python3 tools/guides_visual_lint.py check .          # warn-only (default)
python3 tools/guides_visual_lint.py check . --gate   # hard fail (after adoption)
```

The lint reads the curated backlog in [`visual-evidence-backlog.md`](visual-evidence-backlog.md) plus path heuristics, and flags guide-like Markdown with no image, no `test/evidence/` reference, and no `skip-visuals` reason. Broken image links are reported. Warn-only on the hub until adoption; fleet repos follow the 0007 warn-then-fail fan-out.

## Harness Console (phased)

P1 on epic #678: capture / attach / redaction helpers so operators and agents can record guide evidence from the control plane without a separate toolchain.

## Fleet fan-out

The standard lands here first. Spoke repos get a seed-kit PR that turns the check from warn to fail (epic #678 P3). Do not edit submodule checkouts in the hub PR that ratifies this.

## Related

- Constitution § 15 (PR evidence), § 24 (this standard)
- [`VERIFICATION.md`](VERIFICATION.md), `test/evidence/`
- Backlog audit: [`visual-evidence-backlog.md`](visual-evidence-backlog.md)
