### Added

- The console's assistant is observed where the rest of the fleet is. It is agent `local:console-assist` in `_data/agents.yml`, and every console operation that starts a Claude session now names its agent. `tools/fleetcore/assistlog.py` reads its two records back (its AI-ledger rows and the page bridge's audit) as one document, `assist-activity/v1`, behind the Assist page's new **How it is observed** section, `GET /api/assist/activity`, the MCP tool `assist_activity`, `tools/dash apps assist activity` and `tools/dash lake assist` (lake tables `page_audit` and `assist_runs`, which tell a docked session from a paired one).
- **Shared pages** on the Assist page lists the fleet pages sharing themselves with the console and ends one (`POST /api/assist/shared-pages/end`, by the eight characters the list shows; issue #940). The page's panel (`@bamr87/fleet-assist` 0.1.1) says the sharing was ended from the console.
- `tools/dash-gen ai-run` labels the session it starts in Claude Code's own telemetry: `OTEL_RESOURCE_ATTRIBUTES` carries `fleet.source`, `fleet.call_site` and, when named, `fleet.loop` and `fleet.step`.

### Changed

- The page bridge's audit moved from the console's job directory to `.fleet/assist/page-audit.jsonl` in the hub checkout (`DASH_CONSOLE_PAGE_AUDIT` overrides it), so a restart keeps it and the lake reads it. Each line gained an `id`, the kind of page (`console` or `fleet`) and, for a fleet page, its origin and repo, and is also printed on the console's log as `page-bridge audit {…}`. The audit an earlier console wrote stays where it was; it is not moved.
- The daily `com.bamr87.harness-review` job gained a step, `tools/dash-gen lake assist --days 7`. A LaunchAgent already installed runs the job it was installed with until `tools/install-harness-review.sh` is run again.
