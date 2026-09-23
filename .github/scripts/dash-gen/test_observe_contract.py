#!/usr/bin/env python3
"""
The log plane's contract tests: docker-compose.yml <-> _data/fleet.yml <-> the
committed saved objects, asserted in BOTH directions.

Bidirectional is the point, the way test_schedule.py is bidirectional: a
declared dataset with no index template is as broken as a template for a
dataset nobody declared, and only checking one direction finds half of them.

Each test is a sensor for a failure this plane can have without erroring:

  * a port that moved in compose but not in the contract — the console then
    embeds a URL nothing is listening on, and an iframe renders blank;
  * Grafana published on 3000, which the wiki service already owns — compose
    starts, one of the two loses the port, and which one depends on ordering;
  * a hand-edited ILM policy — the cluster then expires on a schedule the
    contract does not describe, which is only visible as missing data later;
  * a dashboard id that drifted from the contract — same blank iframe, no
    error in any log, which is exactly why the ids are pinned.

    python3 .github/scripts/dash-gen/test_observe_contract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_observe as fo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CONFIG = REPO_ROOT / "tools" / "observability"

CONTRACT = fo.load_contract()
CONTRACT_FLEET = yaml.safe_load((REPO_ROOT / "_data" / "fleet.yml").read_text())
DC = yaml.safe_load(COMPOSE.read_text())
SERVICES = DC["services"]
ELK = {n: s for n, s in SERVICES.items() if "elk" in (s.get("profiles") or [])}
ENV = dict(
    line.split("=", 1) for line in ENV_EXAMPLE.read_text().splitlines()
    if line and not line.startswith("#") and "=" in line
)


PORT_RX = re.compile(
    r"^(?:(?P<host>[\d.]+):)?"                      # optional bind address
    r"(?:\$\{[A-Z_][A-Z0-9_]*(?::-(?P<dflt>\d+))?\}|(?P<lit>\d+))"   # ${VAR:-N} or N
    r":(?P<container>\d+)$")


def _ports(svc: dict) -> list[str]:
    return [str(p) for p in (svc.get("ports") or [])]


def _host_ports(svc: dict) -> list[str]:
    """The port each mapping actually publishes on the host.

    Parsed rather than split on ':' — every port in this file is written
    `127.0.0.1:${NAME:-1234}:1234`, and a naive split lands inside the ${...}
    and compares the variable name to a number, which passes nothing and
    proves nothing.
    """
    out = []
    for spec in _ports(svc):
        m = PORT_RX.match(spec)
        assert m, f"unparsed port mapping {spec!r}"
        out.append(m.group("dflt") or m.group("lit"))
    return out


def _env(svc: dict) -> dict:
    raw = svc.get("environment") or []
    if isinstance(raw, dict):
        return {k: str(v) for k, v in raw.items()}
    return dict(item.split("=", 1) for item in raw if "=" in item)


# --------------------------------------------------------------------------- #
# the profile exists and is shaped like the rest of the file
# --------------------------------------------------------------------------- #
def test_the_elk_profile_holds_the_whole_stack():
    assert set(ELK) == {"elasticsearch", "logstash", "kibana", "filebeat", "grafana"}, sorted(ELK)


def test_the_cli_and_the_console_name_exactly_the_profile_members():
    """`docker compose --profile elk up` ALSO starts the default profile.

    So both front doors name the five services explicitly, and both lists have
    to stay equal to the profile — otherwise "start the log plane" starts the
    whole bench, or silently leaves a service out of it.
    """
    import re
    dash = (REPO_ROOT / "tools" / "dash").read_text()
    m = re.search(r"ELK_SERVICES=\(([^)]*)\)", dash)
    assert m, "tools/dash no longer names the elk services"
    assert set(m.group(1).split()) == set(ELK), sorted(set(m.group(1).split()) ^ set(ELK))

    sys.path.insert(0, str(REPO_ROOT / "tools" / "console"))
    import core  # noqa: WPS433
    assert set(core.ELK_SERVICES) == set(ELK), sorted(set(core.ELK_SERVICES) ^ set(ELK))
    argv, _ = core.build_argv("observe-up", {})
    for name in ELK:
        assert name in argv, f"{name} missing from the console's up command"


def test_grafana_also_carries_the_metrics_profile():
    # FF-0003 adds Prometheus + an OTel collector under `metrics`; Grafana has
    # to come up with either, or that work has to re-open this file.
    assert set(SERVICES["grafana"]["profiles"]) == {"elk", "metrics"}


def test_every_elk_service_follows_the_house_conventions():
    for name, svc in ELK.items():
        assert svc.get("container_name") == f"bamr87-{name}", name
        # The shared fleet network, not a per-project one: the log plane has to
        # see containers from every compose project, which is the whole reason
        # the network is named and shared (docs/CONTAINERS.md).
        net = (CONTRACT_FLEET.get("containers") or {}).get("network", "fleet")
        assert net in (svc.get("networks") or []), f"{name} is off the {net} network"
        for port in _ports(svc):
            assert port.startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_every_elk_service_has_a_named_volume_or_is_stateless():
    for name, svc in ELK.items():
        named = [v for v in (svc.get("volumes") or []) if not v.startswith((".", "/"))]
        assert named, f"{name} has no named volume — its state dies with the container"
        for spec in named:
            vol = spec.split(":", 1)[0]
            assert vol in DC["volumes"], f"{name} mounts undeclared volume {vol}"


def test_the_stack_starts_in_dependency_order():
    for name in ("logstash", "kibana", "grafana"):
        dep = ELK[name].get("depends_on") or {}
        assert dep.get("elasticsearch", {}).get("condition") == "service_healthy", \
            f"{name} may start before elasticsearch can answer"
    assert (ELK["filebeat"].get("depends_on") or {}).get("logstash", {}).get("condition") \
        == "service_healthy", "filebeat may ship into a pipeline that is not listening"


def test_elasticsearch_waits_for_yellow_not_green():
    # A single node can never allocate a replica, so green never arrives and a
    # green healthcheck hangs the whole profile forever.
    test = " ".join(ELK["elasticsearch"]["healthcheck"]["test"])
    assert "wait_for_status=yellow" in test, test


# --------------------------------------------------------------------------- #
# compose <-> fleet.yml <-> .env.example
# --------------------------------------------------------------------------- #
def test_published_ports_match_the_urls_in_the_contract():
    want = {
        "elasticsearch": CONTRACT["logs"]["elasticsearch"],
        "kibana": CONTRACT["logs"]["kibana"],
        "grafana": CONTRACT["metrics"]["grafana"],
    }
    for name, url in want.items():
        port = url.rsplit(":", 1)[1]
        published = _host_ports(ELK[name])
        assert port in published, \
            f"{name}: contract says {url}, compose publishes {published} — the console " \
            "would embed a URL nothing is listening on"


def test_grafana_does_not_take_the_wiki_port():
    # Grafana's own default is 3000 and the wiki has owned it since before this
    # plane existed. Two services on one port is a race, not an error.
    wiki = _host_ports(SERVICES["wiki"])
    assert "3000" in wiki, "the premise moved: the wiki no longer owns 3000"
    assert "3000" not in _host_ports(ELK["grafana"]), "grafana is publishing on the wiki's port"


def test_image_tags_agree_with_the_contract():
    want_elastic = CONTRACT["logs"]["stack_version"]
    want_grafana = CONTRACT["metrics"]["grafana_version"]
    for name in ("elasticsearch", "logstash", "kibana", "filebeat"):
        image = ELK[name]["image"]
        assert f":-{want_elastic}}}" in image, f"{name}: {image} does not default to {want_elastic}"
    assert f":-{want_grafana}}}" in ELK["grafana"]["image"], ELK["grafana"]["image"]
    assert ENV.get("ELASTIC_VERSION") == want_elastic, ".env.example drifted from the contract"
    assert ENV.get("GRAFANA_VERSION") == want_grafana, ".env.example drifted from the contract"


def test_heap_defaults_agree_everywhere_they_are_written():
    """Three copies of the same number: the contract, the compose default and
    .env.example. Elasticsearch takes roughly 2x its heap in RSS, and when it
    is too large for the machine the container exits 137 with no message of its
    own — so a stale copy here is a start failure that explains nothing."""
    heap = CONTRACT["logs"]["ship"]["heap"]
    es_env = _env(ELK["elasticsearch"])["ES_JAVA_OPTS"]
    assert f":-{heap['elasticsearch']}" in es_env, f"compose default drifted from {heap}"
    assert ENV.get("ES_HEAP") == heap["elasticsearch"], ".env.example drifted from the contract"
    ls_env = _env(ELK["logstash"])["LS_JAVA_OPTS"]
    assert f":-{heap['logstash']}" in ls_env, f"compose default drifted from {heap}"
    assert ENV.get("LS_HEAP") == heap["logstash"], ".env.example drifted from the contract"
    # -Xms and -Xmx must match: a JVM allowed to grow its heap will, and an
    # Elasticsearch that grows into the bench gets the rest of it OOM-killed.
    assert es_env.count(heap["elasticsearch"]) == 2, f"-Xms and -Xmx disagree: {es_env}"


def test_env_example_declares_every_variable_the_elk_profile_reads():
    declared = set(ENV)
    for name, svc in ELK.items():
        for ref in re.findall(r"\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}", yaml.safe_dump(svc)):
            assert ref in declared, f"{name} reads ${ref} which .env.example never mentions"


def test_embedding_is_actually_enabled_on_both_uis():
    # Both settings are load-bearing for the console's Observe tab and both
    # fail the same way when wrong: a blank iframe and nothing in any log.
    kib = _env(ELK["kibana"])
    assert kib.get("SERVER_SECURITYRESPONSEHEADERS_DISABLEEMBEDDING") == "false"
    assert kib.get("SERVER_PUBLICBASEURL") , "kibana generates wrong absolute URLs without this"
    graf = _env(ELK["grafana"])
    assert graf.get("GF_SECURITY_ALLOW_EMBEDDING") == "true"
    assert graf.get("GF_AUTH_ANONYMOUS_ENABLED") == "true", "an embed cannot complete a login"
    assert graf.get("GF_AUTH_ANONYMOUS_ORG_ROLE") == "Viewer", "the portal is read-only"


def test_the_config_this_stack_mounts_is_committed():
    for name, svc in ELK.items():
        for spec in (svc.get("volumes") or []):
            src = spec.split(":", 1)[0]
            if src.startswith("./"):
                assert (REPO_ROOT / src[2:]).exists(), f"{name} mounts missing {src}"
                assert spec.endswith(":ro"), f"{name} mounts {src} writable"


# --------------------------------------------------------------------------- #
# the rendered cluster configuration is the committed one
# --------------------------------------------------------------------------- #
def test_committed_elasticsearch_config_equals_what_the_contract_renders():
    policies, templates = fo.render_all(CONTRACT)
    for path, rendered in ((CONFIG / "elasticsearch" / "ilm-policies.json", policies),
                           (CONFIG / "elasticsearch" / "index-templates.json", templates)):
        assert path.exists(), f"{path.name} is missing — run: tools/dash observe verify --write"
        assert json.loads(path.read_text()) == rendered, \
            f"{path.name} was hand-edited; re-render with tools/dash observe verify --write"


def test_committed_dashboards_equal_what_the_contract_renders():
    ndjson = CONFIG / "kibana" / "dashboards.ndjson"
    objs = [json.loads(line) for line in ndjson.read_text().splitlines() if line.strip()]
    assert objs == fo.kibana_saved_objects(CONTRACT), \
        "kibana saved objects drifted — tools/dash observe verify --write"
    grafana = CONFIG / "grafana" / "dashboards" / "fleet-logs.json"
    assert json.loads(grafana.read_text()) == fo.grafana_dashboard(CONTRACT), \
        "grafana dashboard drifted — tools/dash observe verify --write"


def test_kibana_import_format_is_one_object_per_line():
    # The saved-objects import API rejects a JSON array outright. This is the
    # kind of thing that only shows up as a failed bootstrap on a fresh volume.
    text = (CONFIG / "kibana" / "dashboards.ndjson").read_text()
    assert not text.lstrip().startswith("["), "NDJSON, not a JSON array"
    for line in text.splitlines():
        if line.strip():
            json.loads(line)


def test_every_dataset_has_a_policy_a_template_and_a_data_view():
    policies, templates = fo.render_all(CONTRACT)
    views = {o["attributes"]["title"] for o in fo.kibana_saved_objects(CONTRACT)
             if o["type"] == "index-pattern"}
    for key, dataset in CONTRACT["logs"]["datasets"].items():
        assert f"{dataset}-logs" in policies, f"{key} has no ILM policy"
        assert f"{dataset}-logs" in templates, f"{key} has no index template"
        assert f"logs-{dataset}-*" in views, f"{key} has no Kibana data view"
    # …and nothing the other way round.
    declared = {f"{d}-logs" for d in CONTRACT["logs"]["datasets"].values()}
    assert set(policies) == declared, f"orphan policies: {set(policies) - declared}"
    assert set(templates) == declared, f"orphan templates: {set(templates) - declared}"


# --------------------------------------------------------------------------- #
# the portal
# --------------------------------------------------------------------------- #
def test_every_pinned_dashboard_id_resolves_in_a_committed_file():
    blob = ((CONFIG / "kibana" / "dashboards.ndjson").read_text()
            + (CONFIG / "grafana" / "dashboards" / "fleet-logs.json").read_text())
    for plane, ref in CONTRACT["portal"]["dashboards"].items():
        ident = ref.get("id") or ref.get("uid")
        assert ident, f"portal.{plane} pins no id"
        assert f'"{ident}"' in blob, \
            f"portal.{plane} embeds '{ident}', which no committed saved object defines"


def test_frame_src_covers_every_plane_the_portal_embeds():
    frame_src = CONTRACT["portal"]["frame_src"]
    for url in (CONTRACT["logs"]["kibana"], CONTRACT["metrics"]["grafana"],
                CONTRACT["traces"]["endpoint"]):
        assert url in frame_src, f"{url} is embedded but missing from portal.frame_src — the " \
                                 "browser will refuse the frame with only a console message"


def test_grafana_datasource_uid_is_pinned_and_matches_the_dashboard():
    ds = yaml.safe_load((CONFIG / "grafana" / "provisioning" /
                         "datasources" / "elasticsearch.yml").read_text())
    uids = {d["uid"] for d in ds["datasources"]}
    assert fo.GRAFANA_DS_UID in uids, "the dashboard points at a datasource uid nothing provisions"
    assert all(d.get("editable") is False for d in ds["datasources"]), \
        "a provisioned datasource edited in the UI silently diverges from this file"


# --------------------------------------------------------------------------- #
# the redaction path
# --------------------------------------------------------------------------- #
def test_the_pipeline_drops_verbatim_copies_before_it_redacts():
    """Regression: the first live document leaked a token through `event.original`.

    Logstash's http input, in ECS-compatibility mode, stores the WHOLE raw
    request body in `event.original`. A gsub on `message` does not touch it, so
    the indexed document showed a correctly masked `message` sitting next to an
    unmasked copy of the same line. Redaction looked like it was working.

    The copies therefore have to be removed BEFORE the gsub runs, in the shared
    pipeline where both inputs pass.
    """
    conf = (CONFIG / "logstash" / "pipeline" / "90-enrich-out.conf").read_text()
    # Directives, not prose: the comments explaining this ordering mention both
    # words, so matching bare "gsub" finds a sentence rather than a filter.
    code = "\n".join(l for l in conf.splitlines() if not l.lstrip().startswith("#"))
    drop_at, gsub_at = code.find("remove_field =>"), code.find("gsub =>")
    assert drop_at >= 0, "nothing removes the verbatim copies"
    assert gsub_at >= 0, "nothing redacts"
    assert drop_at < gsub_at, "the verbatim copies must be dropped before redaction runs"
    for field in ("event.original", "[event][original]", "log.original"):
        assert field in conf, f"{field} survives into the index"
    for noise in ("http", "url", "user_agent", "@version"):
        assert f'"{noise}"' in conf, f"{noise} is http-input transport metadata, not log data"


def test_every_free_text_field_is_redacted_not_just_message():
    """A stack trace in `error.message` is exactly where a token ends up."""
    conf = (CONFIG / "logstash" / "pipeline" / "90-enrich-out.conf").read_text()
    for field in ('"message"', '"[error][message]"'):
        assert field in conf, f"{field} is never passed through gsub"
    # The patterns themselves must match the contract, or the two halves of the
    # guard (shipper-side and pipeline-side) cover different things.
    for prefix in CONTRACT["logs"]["redact"]:
        stem = prefix.rstrip("_-")
        assert stem in conf, f"fleet.yml declares {prefix} but the pipeline never matches it"


# --------------------------------------------------------------------------- #
# the vendored payload
# --------------------------------------------------------------------------- #
def test_the_shipper_config_is_label_gated_and_points_at_logstash():
    fb = yaml.safe_load((CONFIG / "filebeat" / "filebeat.yml").read_text())
    tmpl = fb["filebeat.autodiscover"]["providers"][0]["templates"][0]
    fields = tmpl["condition"]["has_fields"]
    assert any("com.bamr87.fleet.project" in f for f in fields), \
        "filebeat must opt in by label (UPS-OPS-17), not by name or path"
    # Logstash, not Elasticsearch: the redaction filter is in the enrich pipeline.
    assert "output.logstash" in fb, "shipping straight to ES bypasses redaction"
    assert "output.elasticsearch" not in fb


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
    print("OK — log plane contract tests" if not failures else f"FAIL — {failures} contract test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
