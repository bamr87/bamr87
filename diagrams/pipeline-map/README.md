# diagrams/pipeline-map/

The harness pipeline map's inputs (HUB-025, HUB-026; [docs/prd/HARNESS-PIPELINE-MAP.md](../../docs/prd/HARNESS-PIPELINE-MAP.md)).

- `pipeline.json` is the node and edge definition of every harness loop and AI routine (`pipeline-map/v1`).
- `events.example.json` holds **EXAMPLE DATA ONLY**: fictional `fleet_event` rows, amendment links and job statuses in the activity log's schema (PR #409), for tests and demos.

Build the view model with `python3 tools/pipeline_map.py --events diagrams/pipeline-map/events.example.json`; test it with `python3 tools/test_pipeline_map.py`.
