#!/usr/bin/env python3
"""
Fixture tests for the log plane's pure half — the mappers and the renderers.

Everything here runs offline against literals: no Elasticsearch, no Logstash,
no GitHub, no lake. That is the point of splitting fleet_observe on the network
boundary, and it is what lets these run in the same sweep as every other
control-plane test:

    python3 .github/scripts/dash-gen/test_fleet_observe.py

Each test is a sensor for a specific way this plane can fail quietly:

  * a document that loses a field nobody notices until a Kibana column is empty;
  * a credential reaching the index because the shipper built a document
    Logstash never saw (--dry-run writes one straight to disk);
  * a retention number hardcoded here instead of read from _data/fleet.yml,
    which is how a contract change stops reaching the cluster;
  * a trace id that drifts from Phoenix's, which silently breaks the ONE join
    the Observe tab is built around.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_lake          # noqa: E402
import fleet_observe as fo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

CONTRACT = fo.load_contract()

RUN = {
    "id": 42, "nwo": "bamr87/it-journey", "run_attempt": 2, "run_number": 7,
    "workflow_name": "CI", "workflow_path": ".github/workflows/ci.yml",
    "conclusion": "failure", "status": "completed", "event": "push",
    "head_branch": "main", "head_sha": "abc1234",
    "created_at": "2026-09-20T10:00:00Z", "run_started_at": "2026-09-20T10:00:05Z",
    "updated_at": "2026-09-20T10:04:00Z",
    "html_url": "https://github.com/bamr87/it-journey/actions/runs/42",
}
AGENT = {"model": "claude-opus-5", "cost_usd": 0.42, "num_turns": 6,
         "session_id": "sess-1", "is_error": 0, "ended_at": "2026-09-20T10:03:59Z"}
PROJECT = {"name": "it-journey", "category": "docs"}

ENTRY = "build/3_Run tests.txt"
TEXT = (
    "2026-09-20T10:00:06.1234567Z Running tests\n"
    "2026-09-20T10:00:07.1234567Z ERROR: assertion failed\n"
    "2026-09-20T10:00:08.1234567Z done\n"
)


# --------------------------------------------------------------------------- #
# the document shape
# --------------------------------------------------------------------------- #
def test_actions_document_carries_the_whole_field_contract():
    docs = fo.ecs_from_log_entry(ENTRY, TEXT, RUN, CONTRACT, AGENT, PROJECT)
    assert len(docs) == 3, f"one document per non-blank line, got {len(docs)}"
    d = docs[0]
    for path in ("@timestamp", "message", "ecs.version", "log.level", "event.dataset",
                 "service.name", "fleet.repo", "fleet.project", "fleet.category",
                 "ci.run_id", "ci.run_attempt", "ci.workflow", "ci.job", "ci.step",
                 "ci.conclusion", "ci.event", "ci.branch", "ci.sha",
                 "url.full", "trace.id", "llm.model", "llm.cost_usd"):
        cur = d
        for part in path.split("."):
            assert isinstance(cur, dict) and part in cur, f"missing field {path}"
            cur = cur[part]
    assert d["event"]["dataset"] == "fleet.actions"
    assert d["fleet"]["repo"] == "bamr87/it-journey"
    assert d["ci"]["run_attempt"] == 2


def test_timestamps_come_from_the_log_line_not_from_now():
    docs = fo.ecs_from_log_entry(ENTRY, TEXT, RUN, CONTRACT, None, PROJECT)
    stamps = [d["@timestamp"] for d in docs]
    assert stamps == ["2026-09-20T10:00:06.1234567Z",
                      "2026-09-20T10:00:07.1234567Z",
                      "2026-09-20T10:00:08.1234567Z"], stamps
    # …and the Actions prefix is stripped from the text itself.
    assert docs[0]["message"] == "Running tests", docs[0]["message"]


def test_entry_name_splits_into_job_and_step():
    assert fo._entry_step("build/3_Run tests.txt") == ("build", "Run tests")
    assert fo._entry_step("1_build.txt") == ("build", None)


def test_unstamped_lines_fall_back_to_the_run_start():
    docs = fo.ecs_from_log_entry("1_build.txt", "no timestamp here\n", RUN, CONTRACT, None, PROJECT)
    assert docs[0]["@timestamp"] == RUN["run_started_at"], docs[0]["@timestamp"]


def test_agent_summary_is_one_document_not_one_per_line():
    doc = fo.ecs_from_agent_run(AGENT, RUN, CONTRACT, PROJECT)
    assert doc["llm"]["cost_usd"] == 0.42
    assert doc["event"]["module"] == "claude.agent"
    # A cost aggregation must not be able to sum this AND the per-line copies
    # into the same series, so the two carry different event.module values.
    line = fo.ecs_from_log_entry(ENTRY, TEXT, RUN, CONTRACT, AGENT, PROJECT)[0]
    assert line["event"]["module"] != doc["event"]["module"]


def test_agent_error_run_is_logged_at_error_level():
    doc = fo.ecs_from_agent_run(dict(AGENT, is_error=1), RUN, CONTRACT, PROJECT)
    assert doc["log"]["level"] == "error"


# --------------------------------------------------------------------------- #
# THE JOIN — an ES document and a Phoenix span must address the same run
# --------------------------------------------------------------------------- #
def test_trace_id_is_byte_identical_to_the_phoenix_exporter():
    key = f"run:{RUN['nwo']}:{RUN['id']}:{RUN['run_attempt']}"
    expected = fleet_lake.hex_trace(fleet_lake.trace_id_for(key))
    docs = fo.ecs_from_log_entry(ENTRY, TEXT, RUN, CONTRACT, AGENT, PROJECT)
    summary = fo.ecs_from_agent_run(AGENT, RUN, CONTRACT, PROJECT)
    assert docs[0]["trace"]["id"] == expected, "log line drifted from the Phoenix trace id"
    assert summary["trace"]["id"] == expected, "agent summary drifted from the Phoenix trace id"
    assert len(expected) == 32, "OTel trace ids are 16 bytes / 32 hex chars"


def test_a_retry_is_a_different_trace_than_the_first_attempt():
    a = fo.ecs_from_log_entry(ENTRY, TEXT, RUN, CONTRACT, None, PROJECT)[0]["trace"]["id"]
    b = fo.ecs_from_log_entry(ENTRY, TEXT, dict(RUN, run_attempt=1), CONTRACT,
                              None, PROJECT)[0]["trace"]["id"]
    assert a != b, "run_attempt must be part of the trace key"


# --------------------------------------------------------------------------- #
# redaction — the guard for documents Logstash never sees
# --------------------------------------------------------------------------- #
def test_every_declared_prefix_is_masked():
    declared = CONTRACT["logs"]["redact"]
    samples = {
        "sk-ant-": "sk-ant-api03-AAAABBBBCCCCDDDD",
        "ghp_": "ghp_" + "A" * 36,
        "github_pat_": "github_pat_11ABCDE_" + "x" * 30,
        "gho_": "gho_" + "B" * 36,
        "ghs_": "ghs_" + "C" * 36,
        "AIza": "AIza" + "D" * 35,
    }
    for prefix in declared:
        assert prefix in samples, f"fleet.yml declares {prefix} with no test sample"
        secret = samples[prefix]
        out = fo.redact(f"authenticating with {secret} now")
        assert secret not in out, f"{prefix} survived redaction: {out}"
        assert "[REDACTED]" in out


def test_redaction_catches_every_occurrence_not_just_the_first():
    tok = "ghp_" + "A" * 36
    out = fo.redact(f"{tok} and again {tok}")
    assert tok not in out and out.count("[REDACTED]") == 2, out


def test_shipped_documents_are_redacted_at_build_time():
    text = "2026-09-20T10:00:06Z export TOKEN=ghp_" + "A" * 36 + "\n"
    doc = fo.ecs_from_log_entry(ENTRY, text, RUN, CONTRACT, None, PROJECT)[0]
    assert "ghp_AAAA" not in doc["message"], doc["message"]


# --------------------------------------------------------------------------- #
# routing and levels
# --------------------------------------------------------------------------- #
def test_structured_line_routes_to_app_and_anything_else_to_container():
    ups = json.dumps({"ts": "2026-09-20T10:00:00Z", "level": "info", "msg": "served",
                      "logger": "app", "request_id": "r1", "app": "zer0", "version": "1.2.3"})
    assert fo.dataset_for(ups) == "app"
    assert fo.dataset_for('{"level":"info","message":"also fine"}') == "app"
    assert fo.dataset_for("plain container chatter") == "container"
    assert fo.dataset_for('{"level":"info"}') == "container", "needs a message to be a log line"
    assert fo.dataset_for('{"broken": ') == "container", "malformed JSON is not app data"
    assert fo.dataset_for("") == "container"


def test_level_is_inferred_so_error_search_works_on_unstructured_lines():
    assert fo.level_of("ERROR: boom") == "error"
    assert fo.level_of("a WARNING here") == "warn", "warning normalises to warn"
    assert fo.level_of("everything is fine") == "info"
    assert fo.level_of("") == "info"


def test_data_stream_names_follow_elastic_convention():
    assert fo.data_stream_for("actions", CONTRACT) == "logs-fleet.actions-default"
    assert fo.data_stream_for("container", CONTRACT) == "logs-fleet.container-default"


# --------------------------------------------------------------------------- #
# the renderers read the contract, they do not restate it
# --------------------------------------------------------------------------- #
def test_ilm_retention_comes_from_fleet_yml():
    for key, days in CONTRACT["logs"]["retention_days"].items():
        policy = fo.ilm_policy_for(key, CONTRACT)
        assert policy["policy"]["phases"]["delete"]["min_age"] == f"{days}d", key
        hot = policy["policy"]["phases"]["hot"]["actions"]["rollover"]
        assert hot["max_age"] == CONTRACT["logs"]["rollover"]["max_age"]


def test_a_changed_contract_changes_the_rendered_policy():
    bumped = json.loads(json.dumps(CONTRACT))
    bumped["logs"]["retention_days"]["actions"] = 5
    assert fo.ilm_policy_for("actions", bumped)["policy"]["phases"]["delete"]["min_age"] == "5d"
    assert fo.ilm_policy_for("actions", CONTRACT) != fo.ilm_policy_for("actions", bumped), \
        "the renderer is reading a hardcoded default, not the contract"


def test_every_dataset_gets_a_policy_and_a_template_that_agree():
    policies, templates = fo.render_all(CONTRACT)
    assert set(policies) == set(templates), "a template without its policy, or the reverse"
    for key in CONTRACT["logs"]["datasets"]:
        tpl = fo.index_template_for(key, CONTRACT)
        assert tpl["index_patterns"] == [f"logs-{CONTRACT['logs']['datasets'][key]}-*"]
        assert tpl["template"]["settings"]["index.lifecycle.name"] == fo.ilm_policy_name(key, CONTRACT)
        # A single node can never allocate a replica; leaving the default of 1
        # parks every index at yellow forever.
        assert tpl["template"]["settings"]["index.number_of_replicas"] == 0


def test_actions_template_maps_the_fields_the_dashboards_query():
    props = fo.index_template_for("actions", CONTRACT)["template"]["mappings"]["properties"]
    assert props["llm"]["properties"]["cost_usd"]["type"] == "double", "cost must aggregate numerically"
    assert props["trace"]["properties"]["id"]["type"] == "keyword"
    assert props["fleet"]["properties"]["repo"]["type"] == "keyword", "repo is a filter, not text"
    assert props["ci"]["properties"]["run_id"]["type"] == "long"


def test_missing_contract_block_still_renders_something_valid():
    empty = fo.load_contract(REPO_ROOT / "does-not-exist.yml")
    assert empty["logs"]["datasets"], "fallbacks exist so an offline render degrades, not crashes"
    assert fo.ilm_policy_for("actions", empty)["policy"]["phases"]["delete"]["min_age"].endswith("d")


# --------------------------------------------------------------------------- #
# the dashboards the console embeds
# --------------------------------------------------------------------------- #
def test_pinned_ids_are_what_the_contract_says_they_are():
    portal = CONTRACT["portal"]["dashboards"]
    objs = fo.kibana_saved_objects(CONTRACT)
    ids = {o["id"] for o in objs}
    assert portal["logs"]["id"] in ids, "the console embeds a Kibana dashboard that is not rendered"
    assert fo.grafana_dashboard(CONTRACT)["uid"] == portal["metrics"]["uid"]


def test_every_kibana_panel_reference_resolves_within_the_bundle():
    objs = fo.kibana_saved_objects(CONTRACT)
    ids = {o["id"] for o in objs}
    for o in objs:
        for ref in o["references"]:
            assert ref["id"] in ids, f"{o['id']} references missing object {ref['id']}"


def test_grafana_panels_all_point_at_the_pinned_datasource():
    dash = fo.grafana_dashboard(CONTRACT)
    assert dash["panels"], "a dashboard with no panels is a blank embed"
    for panel in dash["panels"]:
        assert panel["datasource"]["uid"] == fo.GRAFANA_DS_UID, panel["title"]
        for target in panel["targets"]:
            assert target["timeField"] == "@timestamp"


# --------------------------------------------------------------------------- #
def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print("OK — log plane mapper tests" if not failures else f"FAIL — {failures} log plane test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
