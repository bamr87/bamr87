# PRD — Shared functional specification library

> **Status: Draft / proposed.** Design only; nothing here is implemented. Accepted when the maintainer merges this PR. The resolver, the gate and the spec page land in later PRs.
> Features: `HUB-NEW` slugs `functional-spec-library`, `spec-manifest`, `spec-resolver` and `spec-override-ratification` in [`features/features.d/`](../../features/features.d/). Numbers are assigned at merge ([amendment 0002](../amendments/0002-conflict-free-numbering.md)).
> Requirements: `FR-NEW:functional-spec-library`, `FR-NEW:spec-manifest`, `FR-NEW:spec-resolver`, `FR-NEW:spec-library-gate`, `FR-NEW:spec-docs-parity`, `FR-NEW:spec-override-ratification`, `NFR-NEW:spec-resolver-ssot`, declared on those fragments and numbered at merge.
> Roadmap: `FF-NEW:functional-spec-library` in [`_data/roadmap.d/functional-spec-library.yml`](../../_data/roadmap.d/functional-spec-library.yml).
> Library spec ids use the `FEAT-NNN` format. That series is not in the compiler yet, so this PR does not pick a `FEAT` number; content specs will be `FEAT-NEW` fragments numbered at merge.
> Governing rules: [`docs/constitution.md`](../constitution.md) § 2 (no sequential id in a pull request), § 8 (amendments are ratified only by merge), FR4 and FR28. A follow-up amendment would record override ratification in the constitution. This PR does not write that amendment and does not ratify anything.

## 1. Problem

Fleet repos share kits, a project standard and a per-change spec gate, and they do not share one library of product behaviour. Each repo that wants the same functional rule restates it, and a reader of the docs site cannot see the set CI will actually enforce.

A repo needs one place to say which shared functional specs it has adopted, which it narrows, and which do not apply. CI and the docs site need to read that decision from one resolved set, so a page cannot claim a spec the gate ignored.

## 2. Goals and non-goals

**Goals**

- One central library of generic functional specifications in this monorepo, addressed by `FEAT-NNN` and linked to PRD requirements, consumable by every repo, framework and application in the fleet.
- One root manifest per repo (`specs.json`) with a schema version, the adopted spec ids, optional per-id overrides, and an exclusions list.
- One fleet-level resolver that turns a manifest plus the library into one resolved spec set: core specs, plus the framework overlay for the repo's kinds, minus exclusions, with ratified overrides applied last.
- CI on every pull request runs that resolution and fails when a required spec lacks coverage or the manifest names an id the library does not contain.
- The docs site renders each repo's spec page from that same resolver output.
- A relaxation of a required spec stays unapplied until Amr merges an amendment-style record. A change to a standard or a principle stays on the constitution amendment path and is ratified only by merge.

**Non-goals**

- Implementing the resolver, the workflow, the site route, the `FEAT` compiler series, or the first content specs in this PR.
- Replacing the Universal Project Standard (`specs/`, `UPS-<AREA>-NN`), the spec-driven change packages (`specs/NNN-slug/{spec,plan,tasks}.md`), the feature catalog (`HUB-NNN`), or constitution amendments.
- Vendoring a copy of the library into each repo, or introducing a shared package build. Each repo still builds itself. It shares the resolved spec set.
- Waiving a UPS `MUST` through this manifest. UPS conformance is unchanged: a `MUST` stays unwaivable ([`specs/CONFORMANCE.md`](../../specs/CONFORMANCE.md)).
- Hand-assigning `FEAT-NNN`, `HUB-NNN`, `FRn` or `FF-NNNN` in a pull request.
- Changing workflows, repository settings, secrets or branch protection.
- Merging a relaxation by an agent, or applying a relaxation from an open pull request.

## 3. How this sits beside what the fleet already has

| Existing piece | What it already owns | What this library adds |
| --- | --- | --- |
| Universal Project Standard, [`specs/`](../../specs/README.md) and [`_data/specs.yml`](../../_data/specs.yml) | How a repo is built: layout, CI, docs, operations. Row ids are `UPS-<AREA>-NN`. [`tools/conformance.py`](../../tools/conformance.py) (`dash spec`, reusable `fleet-conformance.yml`) audits them. | Product behaviour (what the software must do for a user). A `FEAT` may cite a UPS row. It does not copy the row and it does not change UPS conformance. |
| Spec-driven kit and [`.github/workflows/spec-gate.yml`](../../.github/workflows/spec-gate.yml) | One change's package `specs/NNN-slug/{spec,plan,tasks}.md` plus `BACKLOG.md`, checked by `spec_validator.py` and `backlog_lint.py` (UPS-WORK-07, [`docs/SPEC-DRIVEN.md`](../SPEC-DRIVEN.md)). The repo consumes the kit by reference. | Whether the repo has adopted the shared functional specs and covered the required ones. The new gate runs beside spec-gate. It does not take over UPS-WORK-07, and this PR does not edit `spec-gate.yml` (that file is a versioned public interface). |
| Feature catalog and [`tools/governance_lint.py`](../../tools/governance_lint.py) | `features/features.yml` rows (`HUB-NNN`) link to PRD requirements (`FRn` / `NFRn`). The PRD feature block is generated. [`tools/features_index.py`](../../tools/features_index.py) grades tests, scenarios and evidence. | The same link shape for library specs: every `FEAT` carries `prd:` pointing at the requirement it serves. Coverage of a required `FEAT` is read from that link, not from a second catalog. |
| JEV, [`tools/jev/number.py`](../../tools/jev/number.py) | `HUB-NNN`, `FRn`, `NFRn`, `FF-NNNN` and amendment numbers are assigned on `main` from fragments. A pull request writes `HUB-NEW`, `FR-NEW:<key>`, `FF-NEW`. | The system features in this PR are those fragments. The `FEAT-NNN` series is specified as the same kind of fragment (`FEAT-NEW`) and joins the compiler in the implementation PR, before any content spec is numbered. |
| Constitution amendments, [`docs/constitution.md`](../constitution.md) § 8 | A rule change is `docs/amendments/proposed/<slug>.md` with `**Number:** NEW`, reviewed, and ratified only when the maintainer merges it. Records are append-only. | Relaxing a required functional spec uses that same propose / review / ratify-by-merge sequence. The record lives in its own log so it is not compiled into the constitution. Standard or principle changes still go through § 8 and are ratified only by merge. |
| Fan-out, [`tools/fanout.sh`](../../tools/fanout.sh) (FR6) | Kits reach spoke repos as dry-run, additive pull requests. | A later rollout opens those PRs for `specs.json`. The library itself stays on the hub and is read by reference, the way `fleet-kit.sh` and `spec-gate.yml` already do. |
| Docs site, [`docs/CONSOLE-PAGES.md`](../CONSOLE-PAGES.md) (FR5, FR36) | Pages renders the console from one build. In-app links use the router basename; file URLs use `asset()`. A new route is registered in `snapshot.STATIC_ROUTES`. | The spec page is one more route fed by the resolver's JSON. The page does not resolve specs itself. |

## 4. Identifiers

This repo's feature catalog prefix is `HUB`. [`templates/verify/features.template.yml`](../../templates/verify/features.template.yml) allows a per-repo prefix (`ZER0-001`); the hub's series is `HUB-NNN`. [`PRD.md`](../../PRD.md) FR33's "FEAT/FR" wording means that catalog id together with the requirement id. `tools/jev/number.py` does not reserve a `FEAT` series. The `FEAT-012` token in [`docs/ARCH-RESEARCH-HARNESS.md`](../ARCH-RESEARCH-HARNESS.md) is an illustration in a sample mapping, not an allocation.

Two id spaces stay distinct on purpose.

| Id | What it names | Where it is allocated | Linked to |
| --- | --- | --- | --- |
| `HUB-NNN` | A user-facing capability of this hub | `features/features.d/<slug>.yml` with `id: HUB-NEW`, numbered at merge | `prd:` → `FRn` / `NFRn` |
| `FRn` / `NFRn` | A product requirement | The feature fragment's `prd_new:`, numbered at merge into [`PRD.md`](../../PRD.md) | The feature rows that serve it |
| `FEAT-NNN` | One generic functional spec in the shared library | A future `library/functional.d/<slug>.yml` with `id: FEAT-NEW`, numbered at merge by the same compiler once the series exists | The entry's `prd:` field, a `FRn` or `NFRn` |
| `UPS-<AREA>-NN` | A project-standard row | [`specs/`](../../specs/README.md) and [`_data/specs.yml`](../../_data/specs.yml); retired, never reused | Conformance, not this manifest |

The catalog entries this PR adds are the four `HUB-NEW` slugs in the header. They describe the library system. They are not the first content specs, and they are not `FEAT` numbers. Picking `FEAT-001` (or the next free `HUB` number) in this pull request would race any other open pull request, which is the failure [amendment 0002](../amendments/0002-conflict-free-numbering.md) removed.

A library entry's meaning is immutable once numbered. A semantic change retires the id and adds a new one, the same rule `specs/SCHEMA.md` already gives UPS rows. Retiring or redefining a spec that states a standard or a principle is an amendment under § 8, ratified only by the maintainer's merge.

### 4.1 Catalog link for this PR

| Capability | Catalog slug | Requirement slug |
| --- | --- | --- |
| Central library of generic functional specs | `HUB-NEW:functional-spec-library` | `FR-NEW:functional-spec-library` |
| Per-repo `specs.json` manifest | `HUB-NEW:spec-manifest` | `FR-NEW:spec-manifest` |
| Resolver: core + overlay − exclusions, overrides last | `HUB-NEW:spec-resolver` | `FR-NEW:spec-resolver` |
| CI fails on missing coverage or an unknown id | `HUB-NEW:spec-resolver` | `FR-NEW:spec-library-gate` |
| Docs page rendered from the resolver output | `HUB-NEW:spec-resolver` | `FR-NEW:spec-docs-parity` |
| CI and the site call one resolver | `HUB-NEW:spec-resolver` | `NFR-NEW:spec-resolver-ssot` |
| Relaxing overrides stay unapplied until Amr merges | `HUB-NEW:spec-override-ratification` | `FR-NEW:spec-override-ratification` |

`python3 -m tools.jev number plan` prints the numbers those slugs would receive on an empty fragment tree. Those numbers are a dry run. They are not reserved, and another merge can move them. The fragments are the allocation.

## 5. The library

The library lives in the hub, in `library/functional/`, created with its `SCHEMA.md` by the implementation PR (the schema pyramid's rule for a new directory). It is not placed under `specs/`. That directory is the Universal Project Standard, one file per area, and its schema forbids seedable files there.

Spokes do not vendor the library. A spoke's CI and a local run resolve it the way the spec-driven kit already resolves: an explicit checkout, a hub checkout the repo is a submodule of, or a sparse fetch of the hub at a named ref (the spec-gate `hub-ref` input, default `main`). One copy stays canonical.

A content spec is one YAML mapping per file:

| Field | Meaning |
| --- | --- |
| `id` | `FEAT-NEW` in the fragment; `FEAT-NNN` after merge. Never reused. |
| `slug` | Stable name. The fragment filename. |
| `title` | Short name of the behaviour. |
| `summary` | One paragraph: what the adopting product must do. |
| `severity` | `required` or `advisory`. The library default. |
| `applies` | Stack kinds from [`specs/STACKS.md`](../../specs/STACKS.md) and `.github/sdlc.yml` `kinds:` (`all`, or `site`, `app`, `api`, `lib`, `cli`, and the other kinds that file already lists). |
| `overlay` | Absent on a core spec. A kind name on a framework-specific spec. |
| `prd` | One or more requirement ids this spec serves. A new requirement is `prd_new` on the fragment, same as a feature fragment. |
| `status` | `active` or `retired`. A retired id stays in the library so old manifests still resolve, and it never returns to `required`. |

Core specs are entries with no `overlay`. Overlay specs are entries whose `overlay` names a kind. An overlay may add specs for that kind. An overlay that restates a core spec may only be stricter. A relaxing overlay is a library defect: the resolver fails closed and reports it, so a framework file cannot weaken a core spec quietly.

## 6. The manifest

Each adopting repo has `specs.json` at the repository root. The name matches the request. It is the adoption manifest. It is not a spec-driven package and it is not a UPS area file. The existing `specs/` directory keeps both of those jobs.

```json
{
  "version": 1,
  "adopted": ["FEAT-NNN"],
  "overrides": {
    "FEAT-NNN": {
      "severity": "advisory",
      "scope": "admin API only",
      "record": "docs/spec-overrides/NNNN-slug.md"
    }
  },
  "exclusions": ["FEAT-NNN"]
}
```

| Field | Rule |
| --- | --- |
| `version` | Manifest schema version, integer. The resolver refuses an unknown version and fails closed. |
| `adopted` | Spec ids the repo claims, `FEAT-NNN` only. After exclusions, this array must equal the resolved id set. Overrides do not add or remove ids. |
| `overrides` | Optional. Keyed by spec id. `severity` and `scope` only narrow. `record` points at the amendment-style file that authorizes a relaxation. |
| `exclusions` | Specs that do not apply to this repo. An exclusion of a spec the library already considers inapplicable is documentation. An exclusion of a spec that does apply is a relaxation. |

A tightening (advisory raised to required, or a wider scope the library already allows) is not a relaxation and needs no ratification record. It still has to name an id the library contains. A downgrade from `required` to `advisory`, a scope narrowing that drops a required behaviour, or an exclusion of a spec that applies, is a relaxation and follows § 10.

The repo does not declare its own framework inside the manifest. Kinds come from `.github/sdlc.yml` `kinds:`, and when that key is absent from the same detection [`tools/conformance.py`](../../tools/conformance.py) already uses. A manifest cannot pick an overlay to step around a core spec.

## 7. The resolver

One program produces the resolved set. The implementation PR puts that pure function in `tools/fleetcore/` (the core the console and the TUI already share) so CI, the pages build and a future console view import it and none of them re-derive the set. This PR does not add that module.

Inputs: the hub library at a pinned ref, the repo's `specs.json`, the repo's kinds, and the ratification state of any override or exclusion record. Output: one JSON document per repo (schema versioned) listing each spec's id, severity after overrides, scope, overlay or core, the PRD requirement ids, coverage, and any gate findings. CI asserts on that document. The docs site renders that document. `NFR-NEW:spec-resolver-ssot` is the requirement that those two callers are the same function.

Resolution order, first to last:

1. Load the library. Refuse a duplicate id, a missing `prd` link, or an overlay that relaxes a core spec.
2. Build the eligible set: core specs whose `applies` includes `all` or one of the repo's kinds, union overlay specs whose `overlay` kind is one of the repo's kinds.
3. Fail if `adopted`, `overrides` or `exclusions` names an id that is not in the library. Fail if `adopted` names an id that is not eligible (a spec for another framework).
4. Drop exclusions that are in force. An exclusion is in force when the spec was not eligible (documentation), or when the spec was eligible and the exclusion's ratification record is merged by the maintainer. An unratified exclusion of an eligible spec does not drop it.
5. Apply ratified overrides last. An unratified relaxing override does not change severity or scope.
6. Fail the gate when `adopted` is not exactly the resolved id set, when a required spec in that set lacks coverage, or when a relaxation is present and unratified. While the gate is still warn-only (§ 14), those conditions are reported and do not fail the job.

Coverage of a required spec is a test or scenario that exists on disk and is named by a feature whose `prd:` includes the requirement the `FEAT` links to, or a test that names the `FEAT` id directly. A `{na: reason}` waiver in `features/features.yml` does not satisfy a required spec. It may satisfy an advisory spec. That split keeps a design-only catalog row from making the gate green.

New library specs ship as `advisory` and are promoted to `required` in a later library change, so one new spec does not turn the fleet red on the day it is numbered.

## 8. CI enforcement

On every pull request, resolution runs against the pull request's manifest and the hub library ref the workflow pins.

The job fails when any of these is true and the gate is in hard-fail mode:

- The manifest's `version` is unknown.
- `adopted`, `overrides` or `exclusions` cites a spec id the library does not contain.
- A required spec in the resolved set has no coverage, as § 7 defines coverage.
- A relaxation is recorded and not yet ratified, or the resolver would have to apply it to make the job pass.

The job name, the reusable workflow and the `needs:` edges are a later implementation PR. The intended shape is the spec-gate shape: a `workflow_call` the spoke opts into, pinned to a floating major tag per [`docs/WORKFLOW-VERSIONING.md`](../WORKFLOW-VERSIONING.md), with the library fetched at `hub-ref` and nothing vendored. Other jobs `needs:` it when they must not run against an unresolved spec set. This PR does not add or edit a workflow file. Adding one changes the hub's versioned public interface and belongs in its own pull request with a `changelog.d/` fragment.

Until that workflow exists, no repo is gated by this PRD. The PRD is the contract the workflow has to meet.

## 9. Docs site

The spec page for a repo is rendered from the resolver JSON and from nothing else. A hand-written spec page is a drift bug.

The page shows the resolved set grouped as core and overlay, the severity after overrides, exclusions that were applied, relaxations still waiting on a merge, and the PRD requirement each `FEAT` links to. An unknown id and a coverage gap are visible on the page as the same findings CI reports.

The route joins the console's static route table in the implementation PR (`snapshot.STATIC_ROUTES`, held equal by `tools/console/test_pages.py`). Links go through the Pages basename. The page has an explicit empty state when the repo has no `specs.json` yet, and a failed state when resolution fails, so a build does not invent an empty "all clear".

Production and local preview both call the resolver. They do not check in a second copy of the resolved set. A committed snapshot of resolver output is out of scope; snapshots are how the page and the gate drift apart.

## 10. Override ratification

A relaxation is proposed like a constitution amendment and applied like one: only after the maintainer merges it.

1. **Propose.** The pull request adds `docs/spec-overrides/proposed/<slug>.md` with `**Number:** NEW`, copied from the amendment template's fields (`Status`, `Date`, `Proposed by`, `Affects`, the spec id, the severity or scope before and after, and why the spec does not apply or why the downgrade is justified). The manifest may name the record. The resolver does not apply it.
2. **Review.** Amr reviews. The author of the record does not merge it (§ 8's rule: an agent never approves or merges its own amendment).
3. **Ratify.** Merging the pull request ratifies it. The post-merge numbering job assigns the number, moves the record into `docs/spec-overrides/`, and sets `Status: ratified` and `Ratified by:` from the merge, the same way `jev-number.yml`'s ratify job records constitution amendments. Until that merge, the resolved set keeps the library severity and the gate fails closed once hard-fail is on.
4. **Supersede.** A later record may replace an earlier one. The old record is marked superseded. Numbers are not reused. A ratified record is not edited to change the relaxation; a new record does that.

The record is not filed under `docs/amendments/`. That directory is the constitution log: `tools/governance_lint.py` requires its status vocabulary and compiles proposed files into constitution amendments. A spec relaxation that landed there would read as a change to the constitution. The sequence is the same. The log is separate so the two histories stay readable.

Changing what a spec requires of every repo, or changing a principle in the constitution, is not an override. It is a new library id or a constitution amendment, ratified by merge. An override cannot widen a spec and cannot create a spec.

This section is a product requirement (`FR-NEW:spec-override-ratification`). It is not yet a constitutional rule. § 17 names the follow-up amendment that would make it one. Until that amendment is ratified, no relaxation is valid and the implementation must fail closed.

## 11. User stories

| ID | As a… | I want… | So that… |
| --- | --- | --- | --- |
| US1 | Amr | one library of functional specs in the hub, each `FEAT` tied to a PRD requirement | every repo, framework and app is held to the same statement of behaviour |
| US2 | a repo maintainer | a root `specs.json` of adopted ids, narrow overrides and exclusions | adoption is a reviewable file, not a comment in a README |
| US3 | a reviewer | CI to fail with the spec id, the requirement id and the missing coverage or the unknown id | I can see why the pull request is blocked without re-deriving the set |
| US4 | a reader of the docs site | the repo's spec page to be the resolver output CI just used | the page and the gate cannot disagree |
| US5 | Amr | a downgrade of a required spec to sit unapplied until I merge its record | a relaxation cannot land because an agent opened it |
| US6 | an agent | a fragment placeholder instead of the next `FEAT` number, and no way to apply my own relaxation | two pull requests cannot claim one id, and I cannot ratify myself |
| US7 | a framework author | an overlay for my kind on top of the core set | I add framework rules without forking the specs every repo shares |
| US8 | a spoke repo | the library read from the hub by reference | I do not carry a copy that drifts from the copy CI on the hub enforces |

## 12. Requirements

The root [`PRD.md`](../../PRD.md) owns the numbers. This list is the `prd_new` text on the feature fragments; merge appends the numbered bullets. The sub-PRD keeps the slugs.

- **`FR-NEW:functional-spec-library`** — The hub must hold one central library of generic functional specifications, each with a stable `FEAT-NNN` id allocated at merge, each linked by a `prd:` field to the PRD requirement it serves, stored in this monorepo and readable by every fleet repo, framework and application without vendoring a copy.
- **`FR-NEW:spec-manifest`** — Every adopting repo must declare adoption in a root `specs.json` with a schema version, an array of adopted `FEAT-NNN` ids, an optional overrides object keyed by those ids for severity or scope narrowing, and an exclusions list for specs that do not apply.
- **`FR-NEW:spec-resolver`** — One fleet-level resolver must read each repo's manifest, load the matching library entries, and produce one resolved spec set per repo: core specs plus the framework-specific overlay for the repo's kinds, minus exclusions that are in force, with ratified override precedence applied last.
- **`FR-NEW:spec-library-gate`** — On every pull request, resolution must run and fail when a required spec in the resolved set lacks coverage or when the manifest names a spec id that is not in the library.
- **`FR-NEW:spec-docs-parity`** — The docs site must render each repo's spec page from that same resolver output, so the page shows the set CI enforces, including coverage gaps and unknown ids.
- **`NFR-NEW:spec-resolver-ssot`** — CI and the docs site must both call the one resolver and must not reimplement selection, exclusion or override precedence. A test must show that the document the gate asserts is the document the page renders.
- **`FR-NEW:spec-override-ratification`** — An override that downgrades a required spec to advisory, or otherwise relaxes severity or applicable scope, must be proposed as an amendment-style record and must stay unapplied until the maintainer merges it. A change to a standard or a principle goes through a constitution amendment and is ratified only by that merge.

Existing requirements this serves: FR4 (catalog and PRD link both ways), FR5 (pages rendered from data), FR6 (fan-out is pull-request only), FR28 (ids assigned at merge), FR36 (a repo's public docs include its specs where they exist).

## 13. Design for Failure

| Failure mode | Detection | Containment | Recovery | Learning |
| --- | --- | --- | --- | --- |
| Manifest cites an id the library does not contain | Resolver finding `unknown-id`, failing the gate in hard-fail mode | The id is not dropped and not treated as adopted. The resolved set is not published as clean. | The author fixes the id or removes it. A typo never becomes an exclusion. | The finding names the closest retired id when one exists, so a renamed spec is visible. |
| A required spec has no covering test or scenario | Coverage check against `features/features.yml` `prd:` and on-disk tests, or a direct `FEAT` reference | `{na:}` does not satisfy `required`. The gate fails closed in hard-fail mode. | Add a test or scenario, or ratify a real relaxation. A catalog waiver is not that relaxation. | The finding names the requirement id the spec links to, so the missing proof is the catalog's own link. |
| An agent applies a relaxation from an open record | Record status is not `ratified`, or `Ratified by` is empty | Resolver keeps library severity. The gate fails while the relaxation is required to pass. Agent merge of the record is forbidden by the same rule as § 8. | Amr merges the record, or the manifest drops the relaxation. | The open record stays in the log either way, so a rejected downgrade is still visible. |
| CI and the docs page disagree | Fixture test hashes the gate document and the page document (`NFR-NEW:spec-resolver-ssot`) | The page has no private fallback resolver. A mismatch fails the pages test. | Fix the caller that forked the logic. Delete any committed snapshot of the resolved set. | The test is part of the resolver's own suite, so a second implementation fails before it ships. |
| Library gains a required spec and every manifest is suddenly stale | `adopted` ≠ resolved id set | New specs ship as `advisory` first. Warn-only mode reports the gap. Hard-fail waits for the promotion PR. | Repos update `specs.json` through the fan-out PR, or the spec stays advisory. | Promotion to `required` is its own review, not a side effect of adding the file. |
| Kinds are wrong, so the overlay is wrong | Resolver prints the kinds it used, from `sdlc.yml` or the conformance detector | The manifest cannot override kinds. A disagreement between `sdlc.yml` and detection fails the resolve with both answers shown. | Fix `kinds:` in `.github/sdlc.yml`. Re-run resolution. | The finding is the same text conformance already uses for kind detection, so two gates do not invent two kind lists. |
| Hub library ref is unreachable from a spoke | Fetch of `hub-ref` fails | The job fails. It does not fall back to an empty library or a vendored copy. | Restore the ref, or pin `hub-ref` to the major tag the workflow is pinned to, matching spec-gate. | The job log names the ref. A spoke that vendors the library fails review. |
| A ratified record is edited in place to widen the relaxation | Governance check: a ratified spec-override record's severity and scope are append-only | The edit does not apply. A new record supersedes. | Open a new proposed record. Mark the old one superseded after the new one merges. | Same learning as constitution amendments: history is the record, not the latest edit. |
| Two pull requests both claim the next `FEAT` number | Numbering lint rejects a hand-written `FEAT-NNN` in the library, the same way it rejects a hand-written `HUB-NNN` | The compiler is the only writer of the number, serialized on `main`. | Rewrite the entry as `FEAT-NEW` and let merge assign it. | This is the amendment 0002 failure, extended to the new series rather than reintroduced. |
| spec-gate and this gate are treated as the same job | UPS-WORK-07 still requires `spec_validator.py` or `uses:` of `spec-gate.yml` | This gate does not satisfy UPS-WORK-07. spec-gate does not satisfy `FR-NEW:spec-library-gate`. | A repo that runs the change-spec loop keeps spec-gate and adds this job beside it. | The workflow atlas lists them as two workflows with two contracts. |

Risk tier (constitution § 13.6): reading the library and writing a pull request are reversible and internal, so low. Merging a relaxation is a maintainer act. No secret is read. Nothing in this design runs on Amr's Mac.

## 14. Rollout

| Phase | What lands | Acceptance |
| --- | --- | --- |
| P0, this PR | This sub-PRD, the four feature fragments, the roadmap fragment | `number plan` is clean, schema and governance checks pass, no workflow or catalog number is hand-written, no amendment is marked ratified |
| P1, follow-up | The constitution amendment named in § 17, proposed with `**Number:** NEW`, ratified only if Amr merges it | § 8 record exists and the constitution text matches it. Until then, relaxations stay invalid. |
| P2, implementation | `FEAT` series in the numbering compiler, `library/functional/` with `SCHEMA.md`, the resolver in `tools/fleetcore/`, unit tests for the order in § 7 | A fixture repo resolves core + overlay − exclusions with overrides last; an unknown id and a missing coverage fail; an unratified relaxation does not apply. Claude Code does this work against the numbered requirements. |
| P3, hub dogfood | Hub `specs.json`, the gate in warn-only mode, the spec page rendered from the same JSON | The page and the gate finding list match on a fixture. Empty manifest has an explicit empty state. `snapshot.STATIC_ROUTES` includes the route. |
| P4, hub enforce | Hard-fail on the hub | A pull request with an unknown id or an uncovered required spec fails. Advisory specs do not fail the job. |
| P5, spokes | Fan-out of `specs.json` as dry-run additive PRs (FR6), by reference, warn then hard-fail per repo | No spoke receives a vendored library. A repo without the governance kit stays warn-only until FR4's catalog is present. |

P0 does not start P2. P2 waits until this PRD is merged so the requirement ids exist, and until Amr confirms Claude Code should implement it. P1 can be reviewed in parallel with P0; it is a separate pull request because it changes the constitution.

Verification of P0 is `skip-evidence`: the change is a document and catalog fragments, with no user-visible behaviour to exercise ([`docs/VERIFICATION.md`](../VERIFICATION.md)). P3's page is a user-visible surface and gets a scenario and an evidence bundle in that phase.

## 15. Prior art and build-vs-adopt

Needs assessment: the fleet needs one statement of shared product behaviour, adopted per repo, enforced by CI and shown on the docs site, with a human gate on any relaxation.

| Option | Fit |
| --- | --- |
| UPS rows in `specs/` plus `tools/conformance.py` | Right tool for project shape. Wrong id space and wrong waiver rule for product behaviour. Keep it, and point `FEAT` entries at it when a behaviour depends on a UPS row. |
| spec-gate and `spec_validator.py` | Right tool for one change's spec, plan and tasks. It does not know which shared specs a repo has adopted. Keep it beside the new gate. |
| `features/features.yml` plus `governance_lint.py` | Right link shape (id → PRD requirement) and right coverage grade. The resolver reads it. It does not become the library. |
| JEV `number.py` | Right way to mint `FEAT-NNN` without collisions. Extend it in P2. Do not mint numbers in a pull request. |
| Constitution § 8 | Right ratification sequence for a relaxation. Copy the sequence into a separate log so constitution records stay constitution records. |
| A third-party requirements product or a vendored OpenAPI-style spec pack | No fleet repo consumes one today, and a vendored pack is the drift this design exists to avoid. Not adopted. |

Decision (proposed): build a thin resolver and a `FEAT` series on the catalog link, the spec-gate-by-reference fetch, the JEV compiler and the amendment sequence. Adopt nothing that would become a second source of truth.

## 16. Open questions

- Coverage keyed only through the linked `FRn` in `features/features.yml`, or also through a test annotation that names the `FEAT` id? Proposed: both count, and a `{na:}` waiver counts only for advisory.
- A spoke with no feature catalog yet. Proposed: warn-only until FR4's catalog is present, then the same hard-fail as the hub.
- The manifest filename. Proposed: `specs.json` at the repo root, as requested, documented so it is not mistaken for `specs/` (UPS) or `specs/NNN-slug/` (spec-driven packages).
- Whether a tightening override needs a record. Proposed: no. It still has to name a real id, and it cannot invent behaviour the library does not contain.
- The directory name `library/functional/` versus another hub path. Proposed: that path, with a `SCHEMA.md`, outside `specs/`. The implementation PR owns the final path and the schema row.
- When `FEAT-NEW` joins `tools/jev/number.py`. Proposed: P2, before any content spec is added. This PR does not change the compiler.

## 17. Follow-up amendment (not written, not ratified)

This PRD implies one constitution change and does not make it. Conventions require an amendment to change the constitution, and they require that amendment to be proposed with `**Number:** NEW` and ratified only by the maintainer's merge. They do not require the amendment to ride in the PRD's own pull request. Amr asked for the PRD, with the constitutional piece noted as a follow-up, so the record is not opened here and nothing is marked ratified.

Proposed slug, for a later pull request: `functional-spec-override-ratification`.

It would add a short constitution section that says: the shared functional spec library and its resolver are the source of truth CI and the docs site enforce; a relaxation of a required spec follows the § 8 propose / review / ratify-by-merge sequence in `docs/spec-overrides/` and stays unapplied until the maintainer merges it; a change to a standard or a principle remains a constitution amendment. `Affects` would name § 8, `FR-NEW:spec-override-ratification`, and `HUB-NEW:spec-override-ratification`.

Until that pull request is merged by Amr, implementers treat every relaxation as unavailable and fail closed.
