#!/usr/bin/env python3
"""
Contract tests for the fleet activity replay's frozen contracts (P0, #618, HUB-072):

  * schemas/fleet-activity-1.json, the event envelope, accepts every
    schemas/fixtures/fleet-activity-1/valid-*.json and rejects every
    invalid-*.json at the instance path EXPECTED names, and only there, so
    each invalid fixture fails for the one reason it was written for;
  * a real HUB-024 event from tools/fleet_activity.py, wrapped as source
    fleet_event, validates: the envelope carries the activity log's rows whole
    rather than competing with them (FR66);
  * every `observability.logs.redact` prefix planted in a payload, as a value
    or as a key, makes the event invalid;
  * `_data/fleet.yml` `observability.activity` agrees with the schema: its
    source allowlist, the reserved `harness` source and the payload cap;
  * tools/observability/otel-collector/genai-openinference.yml agrees with the
    collector's transform/openinference in both directions.

Validation runs twice when it can: with `jsonschema` (Draft 2020-12) when it
is installed, which CI's python-tests job does, and always with the small
validator below. That validator implements exactly the keywords the schema
uses and raises on any other, so it can never pass an event by skipping a
rule; both must reach the same verdict and the same error paths.

No network, no pytest, PyYAML only:

    python3 tools/test_activity_contract.py
"""
from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fleet_activity  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "fleet-activity-1.json"
FIXTURES = ROOT / "schemas" / "fixtures" / "fleet-activity-1"
FLEET = ROOT / "_data" / "fleet.yml"
GENAI_MAP = ROOT / "tools" / "observability" / "otel-collector" / "genai-openinference.yml"
COLLECTOR = ROOT / "tools" / "observability" / "otel-collector" / "config.yaml"

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

# The ONE instance path each invalid fixture must fail at; () is the event itself.
EXPECT: dict[str, tuple] = {
    "invalid-unredacted-payload.json": ("payload", "env_hint"),
    "invalid-unknown-source.json": ("source",),
    "invalid-kind-namespace.json": ("kind",),
    "invalid-local-time.json": ("ts",),
    "invalid-no-correlation.json": (),
    "invalid-container-unlabelled.json": (),
    "invalid-unknown-field.json": (),
    "invalid-fleet-event-type.json": ("kind",),
    "invalid-trace-id-sha256.json": ("trace_id",),
    "invalid-span-without-trace.json": (),
    "invalid-schema-major.json": ("schema",),
}


# --------------------------------------------------------------------------- #
# the fallback validator: a Draft 2020-12 subset, strict about what it knows
# --------------------------------------------------------------------------- #
class Unsupported(Exception):
    """The schema uses a keyword the fallback cannot check."""


SUPPORTED = {
    # annotations: no effect on validity (format too, as in jsonschema without a format checker)
    "$schema", "$id", "$comment", "$defs", "title", "description", "examples", "default", "format",
    # assertions and applicators the envelope uses
    "$ref", "type", "const", "enum", "pattern", "minLength", "maxLength", "minimum",
    "required", "properties", "additionalProperties", "propertyNames", "dependentRequired",
    "items", "allOf", "anyOf", "not", "if", "then", "else",
}


def _is_type(inst, name: str) -> bool:
    if name == "object":
        return isinstance(inst, dict)
    if name == "array":
        return isinstance(inst, list)
    if name == "string":
        return isinstance(inst, str)
    if name == "boolean":
        return isinstance(inst, bool)
    if name == "null":
        return inst is None
    if name == "integer":
        if isinstance(inst, bool):
            return False
        return isinstance(inst, int) or (isinstance(inst, float) and inst.is_integer())
    if name == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    raise Unsupported(f"type {name!r}")


def _same(a, b) -> bool:
    """JSON equality: true is not 1."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _resolve(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise Unsupported(f"$ref {ref!r} (only local refs)")
    node = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def mini_errors(inst, schema, root: dict | None = None, path: tuple = ()) -> list[tuple[tuple, str]]:
    """Every violation as (instance path, message); [] means valid."""
    root = SCHEMA if root is None else root
    if schema is True:
        return []
    if schema is False:
        return [(path, "no value is allowed here")]
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise Unsupported(", ".join(sorted(unknown)))
    errs: list[tuple[tuple, str]] = []
    if "$ref" in schema:
        errs += mini_errors(inst, _resolve(root, schema["$ref"]), root, path)
    if "type" in schema:
        names = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
        if not any(_is_type(inst, n) for n in names):
            errs.append((path, f"is not of type {schema['type']}"))
    if "const" in schema and not _same(inst, schema["const"]):
        errs.append((path, f"must be {json.dumps(schema['const'])}"))
    if "enum" in schema and not any(_same(inst, e) for e in schema["enum"]):
        errs.append((path, f"{json.dumps(inst)} is not one of {schema['enum']}"))
    if isinstance(inst, str):
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append((path, f"{inst!r} does not match {schema['pattern']}"))
        if len(inst) < schema.get("minLength", 0):
            errs.append((path, f"shorter than {schema['minLength']}"))
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append((path, f"longer than {schema['maxLength']}"))
    if _is_type(inst, "number") and "minimum" in schema and inst < schema["minimum"]:
        errs.append((path, f"less than {schema['minimum']}"))
    if isinstance(inst, dict):
        for key in schema.get("required", []):
            if key not in inst:
                errs.append((path, f"missing required {key!r}"))
        for key, needs in (schema.get("dependentRequired") or {}).items():
            if key in inst:
                errs += [(path, f"{key!r} needs {n!r}") for n in needs if n not in inst]
        props = schema.get("properties") or {}
        extra = schema.get("additionalProperties", True)
        for key, val in inst.items():
            if key in props:
                errs += mini_errors(val, props[key], root, path + (key,))
            elif extra is False:
                errs.append((path, f"unknown field {key!r}"))
            elif isinstance(extra, dict):
                errs += mini_errors(val, extra, root, path + (key,))
        if "propertyNames" in schema:
            for key in inst:
                if mini_errors(key, schema["propertyNames"], root, path):
                    errs.append((path, f"field name {key!r} is not allowed"))
    if isinstance(inst, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(inst):
            errs += mini_errors(item, schema["items"], root, path + (i,))
    for sub in schema.get("allOf", []):
        errs += mini_errors(inst, sub, root, path)
    if "anyOf" in schema and all(mini_errors(inst, s, root, path) for s in schema["anyOf"]):
        errs.append((path, "matches none of anyOf"))
    if "not" in schema and not mini_errors(inst, schema["not"], root, path):
        errs.append((path, "matches a forbidden shape (not)"))
    if "if" in schema:
        branch = schema.get("then") if not mini_errors(inst, schema["if"], root, path) else schema.get("else")
        if branch is not None:
            errs += mini_errors(inst, branch, root, path)
    return errs


try:  # CI installs it; a bare local python3 may not
    import jsonschema
    JS = jsonschema.Draft202012Validator(SCHEMA)
except ImportError:
    jsonschema = None
    JS = None


def verdicts(event: dict) -> dict[str, set[tuple]]:
    """Error paths per validator that ran ({} for a valid event)."""
    out = {"mini": {p for p, _ in mini_errors(event, SCHEMA)}}
    if JS is not None:
        out["jsonschema"] = {tuple(e.absolute_path) for e in JS.iter_errors(event)}
    return out


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_names(prefix: str) -> list[str]:
    return sorted(p.name for p in FIXTURES.glob(f"{prefix}-*.json"))


def fleet() -> dict:
    return yaml.safe_load(FLEET.read_text(encoding="utf-8"))


def dotted(doc: dict, path: str):
    node = doc
    for part in path.split("."):
        node = node[part]
    return node


# --------------------------------------------------------------------------- #
# the envelope
# --------------------------------------------------------------------------- #
def test_the_schema_is_draft_2020_12_and_names_its_major():
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema", SCHEMA["$schema"]
    assert SCHEMA["$id"].endswith("/schemas/fleet-activity-1.json"), SCHEMA["$id"]
    assert SCHEMA["properties"]["schema"]["const"] == "fleet-activity/1"
    assert SCHEMA["additionalProperties"] is False, "unknown top-level fields must fail loudly"
    if jsonschema is not None:
        jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_every_fixture_is_named_for_its_verdict():
    names = sorted(p.name for p in FIXTURES.iterdir())
    stray = [n for n in names if not re.fullmatch(r"(valid|invalid)-[a-z0-9-]+\.json", n)]
    assert not stray, f"fixtures must be valid-*.json or invalid-*.json: {stray}"
    invalid = set(fixture_names("invalid"))
    assert invalid == set(EXPECT), f"EXPECT and the invalid fixtures differ: {invalid ^ set(EXPECT)}"


def test_every_valid_fixture_validates():
    names = fixture_names("valid")
    assert names, "no valid fixtures"
    for name in names:
        for validator, paths in verdicts(load(name)).items():
            assert not paths, f"{name}: {validator} rejected it at {sorted(paths)}"


def test_every_invalid_fixture_fails_only_where_it_says():
    for name, want in EXPECT.items():
        for validator, paths in verdicts(load(name)).items():
            assert paths, f"{name}: {validator} accepted it"
            assert paths == {want}, f"{name}: {validator} failed at {sorted(paths)}, expected only {want}"


def test_every_allowed_source_has_a_valid_fixture():
    sources = {load(n)["source"] for n in fixture_names("valid")}
    allowed = set(dotted(fleet(), "observability.activity.sources"))
    assert allowed <= sources, f"no valid fixture for source(s) {sorted(allowed - sources)}"
    kinds = {load(n)["kind"] for n in fixture_names("valid")}
    assert {"container.oom", "container.die"} <= kinds, "the container die/OOM pair must stay covered"


# --------------------------------------------------------------------------- #
# HUB-024 rides as one source (FR66; #620's question, answered A)
# --------------------------------------------------------------------------- #
ENVELOPE_FROM_ROW = {"event_id", "ts", "repo", "run_id", "bot_id", "event_type"}


def wrap_fleet_event(row: dict, *, seq: int, node: str) -> dict:
    """A HUB-024 fleet_event row as a fleet-activity/1 event, losslessly: the
    envelope takes event_id, ts, repo and run_id, bot_id becomes actor, the
    event type becomes the kind, and the rest of the row is the payload."""
    event = {
        "schema": "fleet-activity/1", "event_id": row["event_id"], "ts": row["ts"],
        "source": "fleet_event", "kind": f"fleet_event.{row['event_type']}", "seq": seq,
        "node": node, "actor": row["bot_id"], "run_id": row["run_id"],
        "payload": {k: v for k, v in row.items() if k not in ENVELOPE_FROM_ROW},
    }
    if row.get("repo"):
        event["repo"] = row["repo"]
    return event


def test_a_live_hub_024_event_wraps_into_the_envelope():
    with tempfile.TemporaryDirectory() as tmp:
        act = fleet_activity.Activity("backlog-fanout", queue=Path(tmp) / "queue.jsonl",
                                      run_id="43387493844", dry_run=True, max_events=6)
        repo, ref = "bamr87/zer0-mistakes", "bamr87/bamr87#409"
        act.emit("start", repo=repo, task_ref=ref, decision="fan out the backlog item")
        act.declined(repo=repo, task_ref=ref, decision="skip", reason="policy",
                     reason_text="opted out", rule_ref="0002",
                     amendments=[{"amendment": "0002", "relation": "cited_for_decline"}])
        act.blocked_handoff(repo=repo, task_ref=ref, decision="wait", blocked_by="human",
                            handoff_to="amr", why="needs-amr")
        act.retry(repo=repo, task_ref=ref, decision="retry", attempt=1, max_attempts=3, cause="rate limit")
        act.emit("finish", repo=repo, task_ref=ref, decision="done", outcome="success")
        spooled = act.queue.read_text(encoding="utf-8").splitlines()
        for _ in range(2):  # past max_events: the spool drops the oldest and writes an overflow row, repo ""
            act.emit("finish", repo=repo, task_ref=ref, decision="done", outcome="success")
        assert act.errors == 0, "fleet_activity swallowed an error"
        overflow = [line for line in act.queue.read_text(encoding="utf-8").splitlines()
                    if json.loads(line)["decision"] == "spool overflow"]
        rows = [json.loads(line) for line in spooled + overflow]
    assert {r["event_type"] for r in rows} == fleet_activity.EVENT_TYPES, [r["event_type"] for r in rows]
    assert overflow, "no overflow row to wrap"
    for seq, row in enumerate(rows):
        event = wrap_fleet_event(row, seq=seq, node="ci")
        for validator, paths in verdicts(event).items():
            assert not paths, f"{row['event_type']}/{row['decision']}: {validator} rejected it at {sorted(paths)}"
        assert event["event_id"] == row["event_id"], "a wrapped row must keep its idempotency key"
    profile = next(rule["then"] for rule in SCHEMA["allOf"]
                   if rule["if"]["properties"]["source"].get("const") == "fleet_event")
    kinds = profile["properties"]["kind"]["enum"]
    assert {k.split(".", 1)[1] for k in kinds} == fleet_activity.EVENT_TYPES, \
        "the fleet_event kinds and tools/fleet_activity.py EVENT_TYPES drifted"


# --------------------------------------------------------------------------- #
# redaction: one list, every plane (NFR13)
# --------------------------------------------------------------------------- #
def test_every_redact_prefix_is_rejected_in_a_payload():
    prefixes = dotted(fleet(), "observability.logs.redact")
    assert prefixes, "observability.logs.redact is empty"
    base = load("valid-hook-pre-tool-use.json")
    filler = "Q7x" * 12  # built at run time: no token-shaped literal is committed
    for prefix in prefixes:
        planted = prefix + filler
        as_value = copy.deepcopy(base)
        as_value["payload"]["note"] = f"exported {planted} by mistake"
        as_key = copy.deepcopy(base)
        as_key["payload"][planted] = True
        for shape, event in (("value", as_value), ("key", as_key)):
            for validator, paths in verdicts(event).items():
                assert paths, f"{prefix!r} as a payload {shape} passed {validator}"


# --------------------------------------------------------------------------- #
# _data/fleet.yml observability.activity ↔ the schema
# --------------------------------------------------------------------------- #
def test_the_activity_block_agrees_with_the_schema():
    doc = fleet()
    block = dotted(doc, "observability.activity")
    assert (ROOT / block["schema"]).resolve() == SCHEMA_PATH, block["schema"]
    enum = set(SCHEMA["properties"]["source"]["enum"])
    assert set(block["sources"]) <= enum, f"sources the schema does not know: {set(block['sources']) - enum}"
    assert "harness" in enum and "harness" not in block["sources"], \
        "harness is reserved: in the schema, out of the allowlist until #626 lands"
    cap = block["caps"]["payload_max_bytes"]
    for name in fixture_names("valid"):
        size = len(json.dumps(load(name)["payload"], separators=(",", ":"), ensure_ascii=False).encode())
        assert size <= cap, f"{name}: payload is {size} bytes, over the {cap}-byte cap"


# --------------------------------------------------------------------------- #
# the GenAI ↔ OpenInference map ↔ the collector's transform
# --------------------------------------------------------------------------- #
OPENINFERENCE_KINDS = {"LLM", "EMBEDDING", "CHAIN", "RETRIEVER", "RERANKER", "TOOL", "AGENT",
                       "GUARDRAIL", "EVALUATOR", "PROMPT"}
_SET = re.compile(r'^set\(attributes\["([^"]+)"\]')
_KIND = re.compile(r'^set\(attributes\["openinference\.span\.kind"\], "([A-Z]+)"\) where name == "([^"]+)"$')
_DEFAULT = re.compile(r'^set\(attributes\["openinference\.span\.kind"\], "([A-Z]+)"\) where '
                      r'attributes\["openinference\.span\.kind"\] == nil$')


def transform_statements() -> list[str]:
    config = yaml.safe_load(COLLECTOR.read_text(encoding="utf-8"))
    blocks = config["processors"]["transform/openinference"]["trace_statements"]
    return [s for block in blocks for s in block["statements"]]


def test_the_genai_map_names_its_semconv_versions():
    gmap = yaml.safe_load(GENAI_MAP.read_text(encoding="utf-8"))
    assert gmap["schema"] == "genai-openinference/v1", gmap.get("schema")
    genai = gmap["semconv"]["gen_ai"]
    for key in ("repo", "ref", "schema_url", "stability"):
        assert genai.get(key), f"semconv.gen_ai.{key} is missing"
    assert gmap["semconv"]["openinference"].get("ref"), "semconv.openinference.ref is missing"
    assert (ROOT / gmap["collector"]).resolve() == COLLECTOR, gmap["collector"]


def test_the_genai_map_rows_are_well_formed():
    gmap = yaml.safe_load(GENAI_MAP.read_text(encoding="utf-8"))
    flags = set(dotted(fleet(), "observability.claude_code.content"))
    assert gmap["default_span_kind"] in OPENINFERENCE_KINDS
    for row in gmap["span_kinds"]:
        assert row["openinference"] in OPENINFERENCE_KINDS, row
        assert row.get("collector") in (None, "applied"), row
    seen = set()
    for row in gmap["attributes"]:
        target = row["openinference"]
        assert target and target not in seen, f"missing or duplicate openinference target: {row}"
        seen.add(target)
        assert row.get("gen_ai") or row.get("claude_code"), f"{target}: maps from nothing"
        if row.get("gen_ai"):
            assert row["gen_ai"].startswith("gen_ai."), row
        assert row.get("collector") in (None, "applied"), row
        if "content" in row:
            assert row["content"] in flags, f"{target}: content flag {row['content']!r} is not in claude_code.content"


def test_the_genai_map_and_the_collector_transform_agree():
    gmap = yaml.safe_load(GENAI_MAP.read_text(encoding="utf-8"))
    statements = transform_statements()
    set_targets = {m.group(1) for s in statements if (m := _SET.match(s))} - {"openinference.span.kind"}
    applied = {r["openinference"] for r in gmap["attributes"] if r.get("collector") == "applied"}
    assert applied == set_targets, (f"map says applied but the transform does not set: {sorted(applied - set_targets)}; "
                                    f"the transform sets but the map lacks: {sorted(set_targets - applied)}")
    kinds = {(m.group(2), m.group(1)) for s in statements if (m := _KIND.match(s))}
    mapped = {(r["claude_code"], r["openinference"]) for r in gmap["span_kinds"] if r.get("collector") == "applied"}
    assert kinds == mapped, f"span kinds drifted: transform {sorted(kinds)} vs map {sorted(mapped)}"
    defaults = {m.group(1) for s in statements if (m := _DEFAULT.match(s))}
    assert defaults == {gmap["default_span_kind"]}, defaults


# --------------------------------------------------------------------------- #
# the fallback cannot pass what it does not understand
# --------------------------------------------------------------------------- #
def test_the_fallback_refuses_a_keyword_it_does_not_know():
    for keyword in ("patternProperties", "oneOf", "unevaluatedProperties", "maxItems"):
        try:
            mini_errors({}, {keyword: {}})
        except Unsupported:
            continue
        raise AssertionError(f"the fallback silently ignored {keyword!r}")


def main() -> int:
    if JS is not None:
        from importlib.metadata import version
        engine = f"jsonschema {version('jsonschema')} + fallback"
    else:
        engine = "fallback only (jsonschema is not installed)"
    print(f"validators: {engine}")
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except (AssertionError, Unsupported) as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — fleet activity contracts")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
