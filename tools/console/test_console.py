#!/usr/bin/env python3
"""
Fixture tests for the Harness Console's core (tools/console/core.py).

Guards the properties that make the console safe to leave running:

  * the operation allowlist is the ONLY way to an argv — unknown ops, bad
    parameters, unknown workflows and unknown workflow inputs are refused
    before anything is built, and no parameter ever reaches a shell string;
  * GitHub-writing operations (fan-out --apply, rotation --apply, workflow
    dispatch) demand an explicit confirm and are flagged as remote, while the
    dry-run shapes of the same operations are not;
  * the state document degrades on missing signals instead of crashing;
  * the job manager runs a real subprocess, tails its log, and reports the
    exit status; and
  * the config editor changes ONLY declared knobs anywhere in fleet.yml,
    rejects the rest, preserves every comment (round-trip) when ruamel is
    present, and rewrites only the blocks the form touched;
  * the auth layer takes a credential without ever handing one back: values
    never appear in a status document, a log, or an argv, .env is written only
    on an explicit confirm, and DASH_CONSOLE_AUTH=off refuses every write; and
  * the HTTP surface refuses a rebound Host, so binding to loopback actually
    means loopback (skipped unless FastAPI is installed).

Deliberately dependency-light — no server, no network, no pytest. Needs only
PyYAML (ruamel.yaml enables the round-trip test; absent, it is skipped):

    python3 tools/console/test_console.py
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402


def test_allowlist_refuses_unknown_and_bad_params():
    for bad in ("rm", "harnesses; rm -rf /", "", "dispatch "):
        try:
            core.build_argv(bad, {})
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    try:
        core.build_argv("deploy-target", {"target": "../x"})
    except ValueError:
        pass
    else:
        raise AssertionError("path-like target accepted")
    try:
        core.build_argv("actions", {"days": 400})
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range days accepted")


def test_argv_shapes_are_exact_and_never_shell():
    argv, remote = core.build_argv("deploy-gaps", {"upgrade": True, "artifacts": "claude,claude-settings"})
    assert argv[-4:] == ["--gaps", "--artifacts", "claude,claude-settings", "--upgrade"], argv
    assert remote is False  # dry run
    argv, remote = core.build_argv("deploy-gaps", {"apply": "true"})
    assert argv[-2:] == ["--gaps", "--apply"] and remote is True
    argv, remote = core.build_argv("harnesses", {"days": "7"})
    assert argv[-2:] == ["--days", "7"] and remote is False
    argv, _ = core.build_argv("config-show", {"key": "harnesses.budget"})
    assert argv[-1] == "harnesses.budget"
    try:
        core.build_argv("config-show", {"key": "x; whoami"})
    except ValueError:
        pass
    else:
        raise AssertionError("shell metacharacters accepted in key")
    for op_id in core.OPS:
        if op_id in ("tests",):
            continue
        argv, _ = core.build_argv(op_id, {"target": "alpha", "workflow": "fleet-pulse", "fields": {}})
        assert all(isinstance(a, str) for a in argv) and "bash" not in argv[0], (op_id, argv)


def test_dispatch_validates_workflow_and_inputs():
    argv, remote = core.build_argv("dispatch", {"workflow": "harness-fanout",
                                                 "fields": {"target": "gaps", "dry_run": True}})
    assert argv == ["gh", "workflow", "run", "harness-fanout.yml", "-f", "target=gaps", "-f", "dry_run=true"]
    assert remote is True  # every dispatch is a remote write
    for params in ({"workflow": "claude"}, {"workflow": "fleet-pulse", "fields": {"evil": "x"}},
                   {"workflow": "harness-fanout", "fields": {"target": "$(id)"}}):
        try:
            core.build_argv("dispatch", params)
        except ValueError:
            continue
        raise AssertionError(f"accepted {params}")


def test_lake_ops_argv_shapes_and_status_document():
    argv, remote = core.build_argv("lake-sync", {"days": "3", "target": "alpha", "jobs": "all", "logs": "none"})
    assert argv[1:] == ["lake", "sync", "--days", "3", "--repo", "alpha", "--jobs", "all", "--logs", "none"], argv
    assert remote is False  # the lake writes to disk, never to GitHub
    argv, _ = core.build_argv("lake-sync", {})
    assert argv[-7:] == ["sync", "--days", "7", "--jobs", "ai", "--logs", "ai"], argv
    for bad in ({"jobs": "everything"}, {"target": "a/b"}, {"logs": "all; rm -rf /"}, {"days": 0}):
        try:
            core.build_argv("lake-sync", bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    argv, remote = core.build_argv("lake-export", {"local": True, "dry_run": True, "force": "1"})
    assert argv[1:] == ["lake", "export", "--days", "7", "--local", "--dry-run", "--force"], argv
    assert remote is False
    argv, _ = core.build_argv("lake-status", {})
    assert argv[1:] == ["lake", "status"]
    import json
    s = core.lake_status(probe=False)
    assert "present" in s and s["phoenix"]["collector"] and "lake_dir" in s
    json.dumps(s)
    json.dumps(core.lake_runs(5))
    json.dumps(core.lake_lines())
    caps = core.capabilities()
    assert isinstance(caps["otel_exporter"], bool) and caps["phoenix"]["collector"] and isinstance(caps["lake_present"], bool)


def test_observe_ops_argv_shapes_and_the_destructive_one_is_gated():
    """The Observe tab's operations.

    Two properties matter here. Every parameter reaches the process as an argv
    ELEMENT, never as a shell string — the compose verb is a literal chosen in
    core.py, so no request body can reach that command line. And exactly one of
    these is irreversible, so exactly one requires a confirm.
    """
    argv, remote = core.build_argv("observe-ship", {"days": "3", "target": "alpha", "dry_run": True})
    assert argv[1:] == ["observe", "ship", "--days", "3", "--repo", "alpha", "--dry-run"], argv
    assert remote is False, "shipping writes to a local Logstash, not to GitHub"
    argv, _ = core.build_argv("observe-ship", {})
    assert argv[1:] == ["observe", "ship", "--days", "7"], argv
    for bad in ({"days": 0}, {"days": 999}, {"target": "a/b"}, {"target": "x; rm -rf /"}):
        try:
            core.build_argv("observe-ship", bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")

    # The five services are NAMED, not left to the profile: a bare
    # `--profile elk up` also starts everything in the DEFAULT profile, so
    # "start the log plane" would bring up devenv, console, wiki and db too.
    up = core.build_argv("observe-up", {})[0]
    assert up[:6] == ["docker", "compose", "--profile", "elk", "up", "-d"], up
    assert set(up[6:]) == set(core.ELK_SERVICES), up
    down = core.build_argv("observe-down", {})[0]
    assert down[:5] == ["docker", "compose", "--profile", "elk", "stop"], down
    assert "-v" not in down, "down must not take the volumes with it"

    # The one that destroys data is gated even though it never touches GitHub,
    # and it goes through the CLI rather than running compose itself: a bare
    # `docker compose down -v` removes EVERY named volume in the file, which
    # would take the wiki's database and Phoenix's traces with the log plane.
    argv, remote = core.build_argv("observe-reset", {})
    assert argv[-3:] == ["observe", "reset", "--yes"], argv
    assert "down" not in argv and "-v" not in argv, "reset must not run compose down -v"
    assert remote is True, "deleting every indexed log line must require a confirm"
    try:
        core.JobManager().submit("observe-reset", {}, confirm=False)
    except PermissionError:
        pass
    else:
        raise AssertionError("observe-reset ran without a confirm")
    # …and nothing else in the group is gated, or the tab becomes unusable.
    for oid in ("observe-status", "observe-up", "observe-down", "observe-ship", "observe-verify"):
        assert core.build_argv(oid, {})[1] is False, f"{oid} should not need a confirm"


def test_observability_document_degrades_instead_of_exploding():
    """A plane that is not running is the ORDINARY state — the stack is opt-in
    behind `--profile elk`. The tab has to render a Start button, so this
    document must come back describing the outage rather than raising."""
    import json
    doc = core.observe_status()
    assert doc["present"] is True, doc.get("error")
    for plane in ("logs", "metrics", "traces"):
        assert plane in doc["planes"], plane
        assert doc["planes"][plane]["url"], f"{plane} has no URL to link to"
    assert isinstance(doc["datasets"], list)
    assert doc["disk_budget_gb"] > 0
    json.dumps(doc)          # the API returns it verbatim

    # The cheap variant /api/capabilities uses must not touch the network.
    caps = core.capabilities()
    obs = caps["observability"]
    assert obs["present"] and obs["logs"]["reachable"] is None, \
        "probe=False must not report reachability it did not measure"
    assert caps["phoenix"]["collector"], "the legacy key stays for existing readers"


def test_embed_urls_and_frame_src_come_from_the_contract():
    """Both halves of the portal, and they have to agree.

    A pinned dashboard id that is not in the embed URL, or an origin missing
    from frame-src, produces the identical symptom: a blank iframe and one line
    in a browser console nobody has open.
    """
    sources = core.frame_src()
    assert sources, "no frame-src means the browser refuses every embed"
    embeds = core.observe_status()["embeds"]
    for plane in ("logs", "metrics"):
        url = embeds.get(plane)
        assert url, f"no embed URL for {plane}"
        origin = "/".join(url.split("/", 3)[:3])
        assert origin in sources, f"{plane} embeds {origin}, which frame-src does not allow"
    assert "embed=true" in embeds["logs"], "kibana would render its full chrome inside the pane"
    assert "kiosk" in embeds["metrics"], "grafana would render its full chrome inside the pane"
    for src in sources:
        assert src.startswith("http://127.0.0.1:"), f"{src} is not loopback — the planes are local-only"


def test_the_observability_contract_block_is_editable_from_the_config_tab():
    keys = [s["key"] for s in core.CONFIG_SECTIONS]
    assert "observability" in keys, "retention would be terminal-only to change"
    section = next(s for s in core.CONFIG_SECTIONS if s["key"] == "observability")
    for field in ("logs.retention_days.actions", "logs.disk_budget_gb", "portal.embed"):
        assert field in section["fields"], field


def test_job_env_hands_jobs_this_interpreter():
    """tools/dash-gen execs $PYTHON, defaulting to system python3.

    The console pip-installs its dependencies (the OpenTelemetry SDK among
    them) into .venv-console, so a job launched on the system interpreter
    cannot import what the console installed — `lake export` failed with
    ModuleNotFoundError on every real send while the dry run, which returns
    before that import, looked fine.
    """
    env = core.job_env()
    assert env["PYTHON"] == sys.executable, env["PYTHON"]
    assert env["PYTHONUNBUFFERED"] == "1"
    # the ambient environment is still inherited — that is how a credential
    # reaches `gh` without ever appearing in an argv
    assert set(os.environ) <= set(env)


def test_job_manager_runs_confirms_and_tails():
    tmp = Path(tempfile.mkdtemp())
    try:
        jm = core.JobManager(job_dir=tmp)
        try:
            jm.submit("dispatch", {"workflow": "build-dash"}, confirm=False)
        except PermissionError:
            pass
        else:
            raise AssertionError("remote write ran without confirm")
        job = jm.submit("gaps")   # offline: reads the committed inventory
        for _ in range(100):
            if jm.tail(job.id)["done"]:
                break
            time.sleep(0.1)
        t = jm.tail(job.id)
        assert t["done"] and t["job"]["status"] in ("succeeded", "failed"), t["job"]
        assert t["text"].startswith("$ ") and "harnesses --gaps" in t["text"]
        assert jm.list()[0]["id"] == job.id
        try:
            jm.tail("nope")
        except KeyError:
            pass
        else:
            raise AssertionError("unknown job id tailed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_state_document_degrades_without_signals(monkeypatch_dir=None):
    state = core.load_state()
    for key in ("sources", "contract", "registry", "harnesses", "loops", "git", "usage", "tokens"):
        assert key in state, key
    assert state["registry"]["count"] > 0
    assert all("cron_human" in loop for loop in state["loops"])
    # a token list never carries values — only names/scope/placement
    assert all(set(t) <= {"name", "scope", "required", "deprecated", "used_by"} for t in state["tokens"])
    assert core.source_meta(None, core.dt.datetime.now(core.dt.timezone.utc))["present"] is False


def test_capabilities_report_names_not_values():
    caps = core.capabilities()
    # every credential the console can be handed, plus every one the contract
    # names — booleans only, so a capability probe can never leak a value
    assert set(caps["env_tokens"]) == set(core.CREDENTIALS)
    assert set(core.TOKEN_ENV) <= set(core.CREDENTIALS)
    assert all(isinstance(v, bool) for v in caps["env_tokens"].values())
    assert isinstance(caps["contract_editing"], bool)
    assert isinstance(caps["config_editing"], bool) and isinstance(caps["auth_writes"], bool)


def test_api_documents_are_json_serializable():
    # Every /api document is handed to pydantic's JSON serializer verbatim; a
    # leaked module or datetime object is a 500 in the browser, not a test
    # failure here — unless we serialize them too.
    import json
    json.dumps(core.capabilities())
    json.dumps(core.load_state())
    json.dumps(core.list_ops())
    json.dumps(core.read_contract())
    json.dumps(core.read_config())
    json.dumps(core.auth_status())


def test_contract_editor_limits_and_preserves_comments():
    try:
        import ruamel.yaml  # noqa: F401
    except ImportError:
        print("  (ruamel.yaml absent — round-trip test skipped)")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        fleet = tmp / "fleet.yml"
        shutil.copy(core.DATA / "fleet.yml", fleet)
        before = fleet.read_text()
        for bad in ({"kit": "x"}, {"budget.monthly_ai_usd": -1}, {"exempt": ["../x"]},
                    {"throughput.max_scheduled_ai_per_day_fleet": "lots"}):
            try:
                core.update_contract(bad, fleet)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad}")
        assert fleet.read_text() == before  # refused edits touch nothing
        out = core.update_contract({"budget.monthly_ai_usd": 90, "exempt": "alpha,beta",
                                    "baseline.require_oauth_secret": False}, fleet)
        assert out["applied"] == {"budget.monthly_ai_usd": 90, "exempt": ["alpha", "beta"],
                                  "baseline.require_oauth_secret": False}, out["applied"]
        after = fleet.read_text()
        assert before.count("#") == after.count("#"), "a comment was lost in the round trip"
        import yaml
        new = yaml.safe_load(after)["harnesses"]
        assert new["budget"]["monthly_ai_usd"] == 90 and new["exempt"] == ["alpha", "beta"]
        assert new["baseline"]["require_oauth_secret"] is False
        # unchanged values are not rewritten (idempotent second call)
        again = core.update_contract({"budget.monthly_ai_usd": 90}, fleet)
        assert again["applied"] == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_contract_edit_touches_only_the_edited_lines():
    """The console's promise is a diff a human can read and commit.

    Counting comments is not enough to prove that: a ruamel round trip keeps
    every comment while still reindenting every sequence in the file and
    re-joining hand-wrapped flow lists, which once turned a one-field edit into
    a 188-line diff over blocks the form cannot even edit.
    """
    try:
        import ruamel.yaml  # noqa: F401
    except ImportError:
        print("  (ruamel.yaml absent — surgical-diff test skipped)")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        fleet = tmp / "fleet.yml"
        shutil.copy(core.DATA / "fleet.yml", fleet)
        before = fleet.read_text().splitlines()
        core.update_contract({"attention_max": 21}, fleet)
        after = fleet.read_text().splitlines()
        assert len(before) == len(after), f"line count changed: {len(before)} -> {len(after)}"
        differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(differing) == 1, f"expected 1 changed line, got {len(differing)}: {differing}"
        assert "attention_max: 21" in after[differing[0]]
        assert "#" in after[differing[0]], "the trailing comment was dropped"

        # a list knob stays inline, so the following comment paragraph can never
        # be emitted between the key and its own items
        core.update_contract({"exempt": ["alpha", "beta"]}, fleet)
        lines = fleet.read_text().splitlines()
        row = next(ln for ln in lines if ln.strip().startswith("exempt:"))
        assert "[alpha, beta]" in row, row
        import yaml
        assert yaml.safe_load("\n".join(lines))["harnesses"]["exempt"] == ["alpha", "beta"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_http_refuses_a_rebound_host():
    """DNS rebinding is the way a loopback bind stops meaning loopback: a
    hostile page resolves its own name to 127.0.0.1 and is then same-origin
    with a console that can dispatch workflows and run --apply fan-outs. The
    Host allowlist is what closes it."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("    (skipped: fastapi not installed)")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import app as console_app

    # base_url matters: TestClient otherwise sends `Host: testserver`,
    # which the guard correctly refuses.
    client = TestClient(console_app.app, base_url="http://127.0.0.1:4001")
    assert client.get("/api/health").status_code == 200
    for host in ("evil.attacker.com", "rebind.example"):
        for call in (lambda: client.get("/api/state", headers={"Host": host}),
                     lambda: client.post("/api/jobs", json={"op": "status"}, headers={"Host": host})):
            assert call().status_code == 421, f"{host} was not refused"
    # loopback names still answer, port suffix and case included
    for host in ("127.0.0.1:4001", "localhost", "LOCALHOST:4001"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200, host

    # The frame policy rides alongside that guard. frame-src must name every
    # origin the Observe tab embeds (a browser refuses a missing one with
    # nothing but a console line), and frame-ancestors must be 'none' — this
    # origin can dispatch workflows with the operator's FLEET_TOKEN, so it is
    # not something to be embedded by anyone.
    csp = client.get("/").headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp, csp
    for src in core.frame_src():
        assert src in csp, f"{src} is embedded but not in frame-src: {csp}"
    # Deliberately narrow: index.html is one file of inline script and style,
    # so a default-src would have to carry 'unsafe-inline' to work at all.
    assert "default-src" not in csp, "a default-src here breaks the page it protects"

    assert client.get("/api/observability").status_code == 200


def test_config_editor_reaches_every_section_and_splices_each():
    """The config form edits blocks all over fleet.yml, so the surgical-diff
    promise has to hold for SEVERAL blocks in one save, not just harnesses."""
    try:
        import ruamel.yaml  # noqa: F401
    except ImportError:
        print("    (ruamel.yaml absent — multi-section test skipped)")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        fleet = tmp / "fleet.yml"
        shutil.copy(core.DATA / "fleet.yml", fleet)
        before = fleet.read_text().splitlines()
        out = core.update_config({"remediation.max_candidates": 5,
                                  "schedule.fleet_pulse": "30 6 * * *",
                                  "evolution.max_turns": 130,
                                  "variables.NODE_VERSION": "22"}, fleet)
        assert set(out["applied"]) == {"remediation.max_candidates", "schedule.fleet_pulse",
                                       "evolution.max_turns", "variables.NODE_VERSION"}, out["applied"]
        assert set(out["sections"]) == {"remediation", "schedule", "evolution", "variables"}
        after = fleet.read_text().splitlines()
        assert len(before) == len(after), f"line count changed: {len(before)} -> {len(after)}"
        differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(differing) == 4, f"expected 4 changed lines, got {len(differing)}: {differing}"
        assert "\n".join(before).count("#") == "\n".join(after).count("#"), "a comment was lost"
        # a quoted scalar stays quoted the way the file wrote it — otherwise
        # every version bump lands as two diff lines instead of one
        assert 'NODE_VERSION: "22"' in "\n".join(after)
        assert 'fleet_pulse: "30 6 * * *"' in "\n".join(after)
        import yaml
        doc = yaml.safe_load("\n".join(after))
        assert doc["remediation"]["max_candidates"] == 5 and doc["evolution"]["max_turns"] == 130
        assert doc["variables"]["NODE_VERSION"] == "22"
        assert core.update_config({"evolution.max_turns": 130}, fleet)["applied"] == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_config_editor_refuses_undeclared_keys_and_bad_types():
    try:
        import ruamel.yaml  # noqa: F401
    except ImportError:
        print("    (ruamel.yaml absent — refusal test skipped)")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        fleet = tmp / "fleet.yml"
        shutil.copy(core.DATA / "fleet.yml", fleet)
        before = fleet.read_text()
        for bad in ({"hub.repo": "someone/else"},            # not an editable field
                    {"rotation.hub_first": False},           # the file calls it non-negotiable
                    {"issue_pipeline.autonomy.never_merge": False},
                    {"schedule.fleet_pulse": "0 6 * * * ; rm -rf /"},
                    {"toolchain.node": "$(id)"},
                    {"variables.FLEET_HUB": "a\nb"},
                    {"issue_pipeline.autonomy.default": "whatever"},
                    {"remediation.max_candidates": -1},
                    {"harness.trip_wires.stale_data_days": "soon"}):
            try:
                core.update_config(bad, fleet)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad}")
        assert fleet.read_text() == before, "a refused edit touched the file"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_config_describes_every_editable_knob():
    doc = core.read_config()
    keys = {f["key"] for s in doc["sections"] for f in s["fields"]}
    assert keys == set(core.CONFIG_FIELDS) == set(doc["editable"])
    for s in doc["sections"]:
        assert s["title"] and s["doc"] and s["present"], s["key"]
        for f in s["fields"]:
            assert f["kind"] in ("bool", "int", "float", "list", "choice", "cron", "version", "value", "slug")
            assert f["present"], f"{f['key']} is not declared in fleet.yml"
    # the Contract API keeps its older, harnesses-relative shape
    assert set(core.read_contract()["editable"]) == set(core.EDITABLE)
    assert "attention_max" in core.EDITABLE and "harnesses.attention_max" in core.CONFIG_FIELDS


def test_auth_status_reports_names_never_values():
    marker = "s3cret-value-nobody-should-see"
    core.os.environ["ANTHROPIC_API_KEY"] = marker
    try:
        import json
        blob = json.dumps(core.auth_status())
        assert marker not in blob, "a credential value reached the status document"
        entry = next(c for c in core.auth_status()["credentials"] if c["name"] == "ANTHROPIC_API_KEY")
        assert entry["present"] is True and entry["label"] and entry["url"]
    finally:
        core.os.environ.pop("ANTHROPIC_API_KEY", None)
    # a tool's own output is scrubbed before it is ever returned
    scrubbed = core._scrub("  - Token: ghp_aaaaaaaaaaaaaaaaaaaa\n  - repo cloned with github_pat_bbbbbbbb\n  ok")
    assert "ghp_" not in scrubbed and "github_pat_" not in scrubbed and "ok" in scrubbed


def test_credentials_are_held_for_jobs_and_persisted_only_on_confirm():
    tmp = Path(tempfile.mkdtemp())
    saved_env_file, saved_value = core.ENV_FILE, core.os.environ.get("FLEET_TOKEN")
    try:
        core.ENV_FILE = tmp / ".env"
        for bad in ("", "short", "has space in it"):
            try:
                core.set_credential("FLEET_TOKEN", bad)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad!r}")
        try:
            core.set_credential("NOT_A_CREDENTIAL", "x" * 20)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown credential accepted")
        # persisting a secret to disk is its own confirm, like every remote write
        try:
            core.set_credential("FLEET_TOKEN", "ghp_" + "a" * 30, persist=True)
        except PermissionError:
            pass
        else:
            raise AssertionError("persisted without confirm")
        assert not core.ENV_FILE.exists(), "the refused persist wrote a file anyway"

        st = core.set_credential("FLEET_TOKEN", "ghp_" + "a" * 30)
        assert core.os.environ["FLEET_TOKEN"] == "ghp_" + "a" * 30   # what a job inherits
        entry = next(c for c in st["credentials"] if c["name"] == "FLEET_TOKEN")
        assert entry["source"] == "session" and entry["in_env_file"] is False

        core.set_credential("FLEET_TOKEN", "ghp_" + "b" * 30, persist=True, confirm=True)
        text = core.ENV_FILE.read_text()
        assert text.count("FLEET_TOKEN=") == 1, text          # upsert, never appended twice
        assert oct(core.ENV_FILE.stat().st_mode)[-3:] == "600", "the .env was not written 0600"
        assert core._env_file_names(core.ENV_FILE) == {"FLEET_TOKEN"}

        core.clear_credential("FLEET_TOKEN", purge=True)
        assert "FLEET_TOKEN" not in core.os.environ
        assert "FLEET_TOKEN" not in core.ENV_FILE.read_text()
    finally:
        core.ENV_FILE = saved_env_file
        core.os.environ.pop("FLEET_TOKEN", None)
        if saved_value is not None:
            core.os.environ["FLEET_TOKEN"] = saved_value
        shutil.rmtree(tmp, ignore_errors=True)


def test_auth_writes_can_be_switched_off_entirely():
    """The console is loopback-guarded, but a deployment that fronts it with
    anything less private needs one switch that refuses every credential write."""
    saved = core.AUTH_WRITES
    try:
        core.AUTH_WRITES = False
        for call in (lambda: core.set_credential("FLEET_TOKEN", "x" * 20),
                     lambda: core.clear_credential("FLEET_TOKEN"),
                     lambda: core.gh_login("x" * 20),
                     core.gh_logout):
            try:
                call()
            except PermissionError:
                continue
            raise AssertionError("a credential write ran with DASH_CONSOLE_AUTH=off")
        assert core.auth_status()["writes_enabled"] is False
    finally:
        core.AUTH_WRITES = saved


def test_gh_login_validates_before_it_ever_runs_gh():
    """The token goes to gh over STDIN — a command line is world-readable and
    would land in this console's own job log. Bad values die before that."""
    for bad in ("", "tiny", "tok en", "tok\nen"):
        try:
            core.gh_login(bad)
        except ValueError:
            continue
        except RuntimeError:
            continue          # gh not installed here — refused earlier still
        raise AssertionError(f"accepted {bad!r}")
    st = core.auth_status()["github"]
    assert set(st) >= {"cli", "authenticated", "account", "scopes", "env_token"}
    # gh prints the token itself; the status document must carry the scopes and
    # never the credential, whether or not this machine happens to be signed in
    msg = st.get("message") or ""
    assert not re.search(r"Token:\s*\S", msg), msg
    assert "ghp_" not in msg and "github_pat_" not in msg, msg


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
    print(f"{'FAIL' if failures else 'OK'} — console fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
