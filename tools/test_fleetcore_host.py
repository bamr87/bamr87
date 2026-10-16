#!/usr/bin/env python3
"""
Fixture tests for tools/fleetcore/host.py — live Docker inventory matched onto
registry rows.

  * DASH_DOCKER_HOST: unset means local + ssh://forge for every surface, an
    empty string turns polling off, duplicates and blanks are dropped;
  * `docker ps` runs as an argv (never a shell), with `-H` only for a remote
    host, detached from the terminal and stdin so an ssh prompt fails fast;
  * an unreachable host, a non-zero exit or a timeout is an error string per
    host, never an exception, and malformed output lines are skipped;
  * attribution: an explicit com.bamr87.fleet.project / bamr87.project label is
    authoritative (an unknown project is attributed to nothing); otherwise the
    strongest evidence wins (compose project > exact name > prefix with a
    separator), then the LONGEST key (cv-builder-pro beats cv), keys need two
    characters, and `cvs-1` is never `cv`;
  * attach() fills each row's best container (running first) and its counts.

A fake `docker` on PATH stands in for the daemon; no Docker, no network:

    python3 tools/test_fleetcore_host.py
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleetcore import host as h  # noqa: E402
from fleetcore.fleet import AppRow  # noqa: E402


class Env:
    def __init__(self, **kw):
        self.kw, self.saved = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.saved[k] = os.environ.get(k)
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def fake_docker(script: str) -> str:
    """A PATH with a `docker` that runs `script` (bash); returns the new PATH."""
    d = Path(tempfile.mkdtemp())
    p = d / "docker"
    p.write_text("#!/usr/bin/env bash\n" + script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return f"{d}{os.pathsep}{os.environ.get('PATH', '')}"


def ps_line(name, state="running", status="Up 2 hours", labels="", ports=""):
    return json.dumps({"Names": name, "State": state, "Status": status, "Labels": labels, "Ports": ports})


def box(name, project="", state="running", labels=None):
    return h.Container(name=name, state=state, status=state, project=project, labels=labels or {})


def test_docker_hosts_from_env():
    with Env(DASH_DOCKER_HOST=None):
        assert h.docker_hosts() == ["local", "ssh://forge"] and h.docker_host() == "local"
    with Env(DASH_DOCKER_HOST=""):
        assert h.docker_hosts() == [] and h.docker_host() == ""
    with Env(DASH_DOCKER_HOST=" ssh://forge, ,local,ssh://forge "):
        assert h.docker_hosts() == ["ssh://forge", "local"]


def test_labels_command_and_host_label():
    assert h._parse_labels("a=1, b = x=y ,junk,") == {"a": "1", "b": "x=y"}
    assert h._parse_labels("") == {} and h._parse_labels(None) == {}
    assert h._command("local") == ["docker", "ps", "-a", "--format", "{{json .}}"]
    assert h._command("ssh://forge")[:3] == ["docker", "-H", "ssh://forge"]
    assert h.host_label("local") == "local" and h.host_label("ssh://forge") == "forge"
    assert h.host_label("tcp://10.0.0.5:2375") == "10.0.0.5:2375"


def test_list_containers_parses_and_skips_garbage():
    out = "\n".join([
        ps_line("/web-1", labels="com.docker.compose.project=cv-builder-pro,com.bamr87.fleet.project=cv-builder-pro",
                ports="0.0.0.0:3000->3000/tcp"),
        "",
        "not json",
        ps_line("db", state="exited", status="Exited (0)"),
    ])
    path = fake_docker(f"cat <<'EOF'\n{out}\nEOF\n")
    with Env(PATH=path):
        boxes, err = h.list_containers("ssh://forge")
    assert err is None and [b.name for b in boxes] == ["web-1", "db"], boxes
    web, db = boxes
    assert web.project == "cv-builder-pro" and web.fleet_project == "cv-builder-pro" and web.running
    assert web.host == "forge" and web.ports.startswith("0.0.0.0:3000")
    assert not db.running and db.fleet_project == "" and db.project == ""


def test_unreachable_failing_and_slow_hosts_are_errors_not_exceptions():
    assert h.list_containers("") == ([], None)
    with Env(PATH=fake_docker("echo 'Cannot connect to the Docker daemon' >&2; exit 1\n")):
        boxes, err = h.list_containers("local")
    assert boxes == [] and "Cannot connect" in err
    with Env(PATH=fake_docker("exit 2\n")):
        assert h.list_containers("local") == ([], "docker ps failed")
    with Env(PATH=fake_docker("sleep 5\n")):
        boxes, err = h.list_containers("local", timeout=0.3)
    assert boxes == [] and "timed out" in err
    with Env(PATH=str(Path(tempfile.mkdtemp()))):  # no docker binary at all
        boxes, err = h.list_containers("local")
    assert boxes == [] and err


def test_list_all_merges_hosts_and_keys_errors_by_label():
    script = 'if [ "$1" = "-H" ]; then echo "ssh: connect to host forge: refused" >&2; exit 255; fi\n' \
             f"echo '{ps_line('it-journey-web-1')}'\n"
    with Env(PATH=fake_docker(script)):
        boxes, errors = h.list_all(["local", "ssh://forge"])
    assert [b.name for b in boxes] == ["it-journey-web-1"] and list(errors) == ["forge"], errors


ROWS = [AppRow(name="cv"), AppRow(name="cv-builder-pro", submodule_path="apps/cvbp"),
        AppRow(name="zer0-pages"), AppRow(name="x")]


def by_name(n):
    return next(r for r in ROWS if r.name == n)


def test_owner_strongest_evidence_then_longest_key():
    assert h.owner(box("cv-builder-pro-web-1"), ROWS) is by_name("cv-builder-pro")
    assert h.owner(box("cv-app-1"), ROWS) is by_name("cv")
    assert h.owner(box("cvs-1"), ROWS) is None                        # needs the separator
    assert h.owner(box("cv_worker"), ROWS) is by_name("cv")
    assert h.owner(box("cv"), ROWS) is by_name("cv")                  # exact name
    assert h.owner(box("whatever", project="cv"), ROWS) is by_name("cv")  # compose project beats prefix
    assert h.owner(box("cvbp-web-1"), ROWS) is by_name("cv-builder-pro")  # submodule dir name is a key
    assert h.owner(box("x-1"), ROWS) is None                          # one-character keys never guess


def test_explicit_label_is_authoritative():
    lab = {"com.bamr87.fleet.project": "zer0-pages"}
    assert h.owner(box("cv-web-1", labels=lab), ROWS) is by_name("zer0-pages")
    legacy = {"bamr87.project": "CV"}
    assert h.owner(box("anything", labels=legacy), ROWS) is by_name("cv")
    hub = {"com.bamr87.fleet.project": "bamr87"}
    assert h.owner(box("cv-web-1", labels=hub), ROWS) is None  # labelled, not in the registry: nobody's
    assert h.owner(box("x", labels={"com.bamr87.fleet.project": "x"}), ROWS) is by_name("x")


def test_attach_and_match_prefer_running_containers():
    rows = [AppRow(name="cv"), AppRow(name="cv-builder-pro"), AppRow(name="idle")]
    boxes = [box("cv-builder-pro-db-1", state="exited"), box("cv-builder-pro-web-1"),
             box("cv-app-1", state="exited"), box("stranger")]
    h.attach(rows, boxes)
    cv, cvbp, idle = rows
    assert (cvbp.docker_name, cvbp.docker_running, cvbp.docker_up, cvbp.docker_total) == (
        "cv-builder-pro-web-1", True, 1, 2)
    assert (cv.docker_name, cv.docker_running, cv.docker_up, cv.docker_total) == ("cv-app-1", False, 0, 1)
    assert cv.docker_status == "exited"
    assert (idle.docker_name, idle.docker_status, idle.docker_total) == (None, None, 0)
    assert [b.owner for b in boxes] == ["cv-builder-pro", "cv-builder-pro", "cv", None]
    assert h.match_container(cvbp, boxes).name == "cv-builder-pro-web-1"
    assert h.match_container(idle, boxes) is None


def main() -> int:
    failed = 0
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in cases:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
