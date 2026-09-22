#!/usr/bin/env python3
# ============================================================================
# File:          tools/fleet_smoke.py
# Description:   Connects to and exercises every fleet container locally, records
#                what it observes into _data/smoke.yml, and re-runs that record
#                as the monorepo's smoke test.
# Author:        bamr87
# Created:       2026-09-21
# Last Modified: 2026-09-21
# Version:       1.0.0
# Usage:
#   tools/fleet-smoke record [--project P]   # probe everything, write the baseline
#   tools/fleet-smoke check  [--project P]   # probe, diff against the baseline, exit 1 on regression
#   tools/fleet-smoke show   [--project P]   # print the recorded baseline
#   tools/dash dev smoke {record|check|show} # the friendly form
# ============================================================================
#
# WHY A RECORDED BASELINE RATHER THAN HAND-WRITTEN ASSERTIONS
#
# Forty repos' worth of services have no shared contract to assert against —
# `record` goes and finds out what each one actually does, and `check` holds it
# to that. A hand-written expectation would have to be invented per service and
# would rot; a recording is true by construction on the day it is taken, and the
# diff afterwards is the signal.
#
# WHAT IS AND IS NOT AN ASSERTION
#
# Recorded-and-asserted: whether a port answers, the HTTP status class, whether
# a database accepts a query and its MAJOR version, whether a cache replies to
# PING, whether a container is running/healthy, and whether a service can exec.
# Recorded-but-NOT-asserted: latency, byte counts, exact patch versions, uptime,
# container ids — these move on their own and asserting them would make the gate
# cry wolf. `check` prints them as context on a failure.
#
# The topology comes from _data/ports.yml, so a service added there is probed
# automatically and nothing has to be registered twice.

import argparse
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("fleet_smoke: PyYAML is required (pip install pyyaml)\n")
    raise SystemExit(2)

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTS_YML = os.path.join(HUB, "_data", "ports.yml")
SMOKE_YML = os.path.join(HUB, "_data", "smoke.yml")

HTTP_BANDS = {"jekyll", "frontend", "api", "docs", "hub"}
HTTP_TIMEOUT = 20
TCP_TIMEOUT = 4

# `hub` is a pseudo-project: its compose project is `fleet-hub`.
PROJECT_LABEL = {"bamr87": "fleet-hub"}


# ---------------------------------------------------------------------------
# docker facts
# ---------------------------------------------------------------------------
# The Docker CLI contends with itself: a cold `docker exec` on this machine costs
# ~7s while a warm one costs 0.2s, so twelve threads arriving at once all queue
# past any sane per-call timeout and the whole recording reads as "timeout".
# Probe concurrency stays high for HTTP/TCP (which never touch the daemon) and is
# gated here for anything that does.
_DOCKER_GATE = threading.Semaphore(1)


def sh(args, timeout=45, retries=1):
    gated = args and args[0] == "docker"
    if gated:
        _DOCKER_GATE.acquire()
    try:
        for attempt in range(retries + 1):
            rc, out, err = _sh_once(args, timeout)
            if rc != 124 or attempt == retries:
                return rc, out, err
            time.sleep(1)
        return rc, out, err
    finally:
        if gated:
            _DOCKER_GATE.release()


def _sh_once(args, timeout):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 127, "", str(exc)


class DockerUnavailable(RuntimeError):
    pass


def containers():
    """compose project -> service -> facts, for every container on the daemon.

    RAISES rather than returning empty on failure. An earlier cut swallowed the
    error, and a transient `docker ps` timeout (the daemon was busy recreating
    the hub) recorded every service in the fleet as "absent" — a confidently
    wrong baseline, which is worse than no baseline at all.
    """
    fmt = ("{{.Label \"com.docker.compose.project\"}}\t"
           "{{.Label \"com.docker.compose.service\"}}\t{{.Names}}\t{{.State}}\t"
           "{{.Status}}\t{{.Image}}")
    # Docker Desktop's latency here is wildly variable under load — the same
    # call measured 0.2s and 18s minutes apart on this machine. Retry before
    # giving up, because the failure mode (everything reads absent) is severe.
    rc, out, err = 124, "", "not attempted"
    for attempt in range(3):
        rc, out, err = sh(["docker", "ps", "-a", "--format", fmt], timeout=90)
        if rc == 0:
            break
        time.sleep(2 * (attempt + 1))
    if rc != 0:
        raise DockerUnavailable(
            f"`docker ps` failed (rc={rc}): {err or 'no output'}. "
            f"Refusing to record — every service would read as absent.")
    found = {}
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        proj, svc, name, state, status, image = parts[:6]
        if not proj:
            continue
        health = None
        m = re.search(r"\((healthy|unhealthy|health: starting)\)", status)
        if m:
            health = m.group(1)
        found.setdefault(proj, {})[svc] = {
            "container": name, "state": state, "health": health, "image": image,
            "status": status,
        }
    return found


def inspect_all(names):
    """Env and configured user for every container, in ONE docker call.

    Reading POSTGRES_USER/POSTGRES_DB with `docker exec printenv` cost two extra
    daemon round-trips per database; on a contended Docker Desktop that was a
    third of the recording's daemon traffic for information already sitting in
    the container config.
    """
    if not names:
        return {}
    rc, out, _ = sh(["docker", "inspect"] + list(names), timeout=90)
    if rc != 0:
        return {}
    try:
        blobs = json.loads(out)
    except ValueError:
        return {}
    info = {}
    for b in blobs:
        name = (b.get("Name") or "").lstrip("/")
        cfg = b.get("Config") or {}
        env = {}
        for item in cfg.get("Env") or []:
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v
        info[name] = {"env": env, "user": cfg.get("User") or ""}
    return info


# ---------------------------------------------------------------------------
# probes
# ---------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an ANSWER, not something to chase.

    The hub's MkDocs serves `/` -> 302 -> `/README/` -> 302 -> … ; following that
    hung the probe for the full timeout and reported a healthy service as broken.
    What this probe asks is "does this port speak HTTP", and a 302 in 4ms answers
    it — where the redirect leads is the application's business.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def probe_http(port, path="/"):
    url = f"http://127.0.0.1:{port}{path}"
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-smoke/1.0"})
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT) as r:
            body = r.read(4096)
            status = r.status
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        # A 3xx/4xx/5xx is still a SERVING port — that is what this probe asks.
        hdrs = exc.headers
        body, status = b"", exc.code
        ctype = hdrs.get("Content-Type", "") if hdrs else ""
        loc = hdrs.get("Location") if hdrs else None
        out = {"kind": "http", "url": url, "ok": True, "status": status,
               "status_class": f"{status // 100}xx",
               "content_type": (ctype or "").split(";")[0], "bytes": 0,
               "ms": int((time.time() - t0) * 1000)}
        if loc:
            out["location"] = loc
        return out
    except Exception as exc:
        return {"kind": "http", "url": url, "ok": False, "error": type(exc).__name__,
                "detail": str(exc)[:120], "ms": int((time.time() - t0) * 1000)}
    out = {"kind": "http", "url": url, "ok": True, "status": status,
           "status_class": f"{status // 100}xx", "content_type": ctype.split(";")[0],
           "bytes": len(body), "ms": int((time.time() - t0) * 1000)}
    m = re.search(rb"<title[^>]*>(.{0,120}?)</title>", body, re.I | re.S)
    if m:
        out["title"] = " ".join(m.group(1).decode("utf-8", "replace").split())
    return out


def probe_tcp(port):
    t0 = time.time()
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=TCP_TIMEOUT):
            return {"kind": "tcp", "port": int(port), "ok": True,
                    "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"kind": "tcp", "port": int(port), "ok": False,
                "error": type(exc).__name__, "ms": int((time.time() - t0) * 1000)}


def probe_postgres(container, env=None):
    """A real query through the container's own psql — no host client needed.

    Both -U and -d come from the container's own env: psql defaults the database
    name to the USER name, so `-U seed_user` alone fails with
    `database "seed_user" does not exist` on every server whose db is named
    something else.
    """
    env = env or {}
    args = ["docker", "exec", container, "psql", "-At"]
    if env.get("POSTGRES_USER"):
        args += ["-U", env["POSTGRES_USER"]]
    args += ["-d", env.get("POSTGRES_DB") or "postgres"]
    rc, out, err = sh(args + ["-c", "select current_setting('server_version')"])
    if rc != 0:
        return {"kind": "postgres", "ok": False, "error": (err or out)[:160]}
    ver = out.split()[0] if out else ""
    rc2, dbs, _ = sh(args + ["-c", "select string_agg(datname,',' order by datname) "
                                    "from pg_database where not datistemplate"])
    return {"kind": "postgres", "ok": True, "server_version": ver,
            "major": ver.split(".")[0], "databases": sorted(dbs.split(",")) if rc2 == 0 and dbs else []}


def probe_redis(container):
    rc, out, err = sh(["docker", "exec", container, "redis-cli", "PING"])
    if rc != 0 or out.strip().upper() != "PONG":
        return {"kind": "redis", "ok": False, "error": (err or out)[:160]}
    rc2, info, _ = sh(["docker", "exec", container, "redis-cli", "INFO", "server"])
    ver = ""
    if rc2 == 0:
        m = re.search(r"redis_version:([0-9.]+)", info)
        ver = m.group(1) if m else ""
    return {"kind": "redis", "ok": True, "pong": True, "redis_version": ver,
            "major": ver.split(".")[0] if ver else ""}


def probe_exec(container):
    """Can we actually get a shell in? Records the user the process runs as —
    UPS-REPO-31 wants non-root, and this is the only place it is observable."""
    rc, out, err = sh(["docker", "exec", container, "sh", "-c",
                       "id -un 2>/dev/null || id -u"])
    if rc != 0:
        return {"kind": "exec", "ok": False, "error": (err or out)[:160]}
    return {"kind": "exec", "ok": True, "user": out.split("\n")[-1].strip()}


# ---------------------------------------------------------------------------
# one service
# ---------------------------------------------------------------------------
def service_profiles(reg, project, service):
    """The compose profiles gating a service, if any.

    A service behind a profile is OPTIONAL by design — `--profile celery` starts
    djangoerp's worker, nothing else does. Recording it as plainly "absent" would
    make 7 of the fleet's 8 stopped services look like defects, when only one
    (zer0-image-generator/web, unprofiled and failing to build) actually is.
    """
    pspec = (reg.get("projects") or {}).get(project) or {}
    rel = pspec.get("compose")
    if not rel:
        return []
    full = os.path.join(HUB, rel)
    if not os.path.exists(full):
        return []
    try:
        with open(full) as fh:
            doc = yaml.safe_load(fh) or {}
    except yaml.YAMLError:
        return []
    svc = (doc.get("services") or {}).get(service) or {}
    prof = svc.get("profiles") or []
    return [str(x) for x in prof] if isinstance(prof, list) else [str(prof)]


def probe_service(project, service, alloc, facts, profiles=None, info=None):
    """Everything observable about one allocated service."""
    rec = {"project": project, "service": service}
    band = (alloc or {}).get("band")
    port = (alloc or {}).get("port")
    if band:
        rec["band"] = band
    if port:
        rec["port"] = port

    if facts:
        rec["container"] = facts["container"]
        rec["state"] = facts["state"]
        rec["image"] = facts["image"]
        if facts.get("health"):
            rec["health"] = facts["health"]
    else:
        rec["state"] = "absent"

    running = bool(facts) and facts["state"] == "running"
    probes = []

    if port and band in HTTP_BANDS:
        probes.append(probe_http(port))
    elif port and band == "database":
        probes.append(probe_tcp(port))
        if running:
            probes.append(probe_postgres(facts["container"],
                                         (info or {}).get("env")))
    elif port and band == "cache":
        probes.append(probe_tcp(port))
        if running:
            probes.append(probe_redis(facts["container"]))
    elif port:
        probes.append(probe_tcp(port))

    if running:
        probes.append(probe_exec(facts["container"]))

    rec["probes"] = probes
    rec["ok"] = running and all(p.get("ok") for p in probes)
    # `absent` (never started, or behind a compose profile) is a different fact
    # from `broken` (running, but something it should answer does not). Only the
    # second is an incident; conflating them makes the record useless as a signal.
    if profiles:
        rec["profiles"] = profiles
    if not facts:
        rec["verdict"] = "optional" if profiles else "absent"
    elif facts["state"] != "running":
        rec["verdict"] = "stopped"
    elif rec["ok"]:
        rec["verdict"] = "ok"
    else:
        rec["verdict"] = "broken"
    return rec


def build(reg, only=None):
    """Probe every allocated service, concurrently — 40+ services serially would
    be minutes of mostly-waiting."""
    live = containers()
    jobs = []
    for pname, pspec in (reg.get("projects") or {}).items():
        pspec = pspec or {}
        if only and pname != only:
            continue
        label = PROJECT_LABEL.get(pname, pname)
        pf = live.get(label, {})
        allocs = dict((pspec.get("services") or {}))
        for dname, d in (pspec.get("debug") or {}).items():
            allocs.setdefault(f"{dname}", d)
        for sname, alloc in allocs.items():
            if (alloc or {}).get("served_by") == "devenv":
                continue
            if pspec.get("host") == "devenv":
                # Served from inside the shared workspace container by a command a
                # human starts; there is no container of its own to interrogate.
                continue
            jobs.append((pname, sname, alloc, pf.get(sname),
                         service_profiles(reg, pname, sname)))

    info = inspect_all([f["container"] for j in jobs if (f := j[3])])
    results = []
    # 6 workers, but the daemon gate above serializes the docker calls — the
    # parallelism is only for HTTP/TCP, which never touch it.
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(probe_service, *j,
                            info=info.get(j[3]["container"]) if j[3] else None): j
                for j in jobs}
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: (r["project"], r["service"]))

    # Containers that exist but have no allocation — recorded so the fleet's real
    # surface is visible, not just the part the registry knows about.
    extra = []
    for pname, pspec in (reg.get("projects") or {}).items():
        if only and pname != only:
            continue
        label = PROJECT_LABEL.get(pname, pname)
        known = set((pspec or {}).get("services") or {}) | set((pspec or {}).get("debug") or {})
        for svc, f in (live.get(label) or {}).items():
            if svc not in known:
                extra.append({"project": pname, "service": svc, "state": f["state"],
                              "image": f["image"], "container": f["container"],
                              **({"health": f["health"]} if f.get("health") else {})})
    extra.sort(key=lambda r: (r["project"], r["service"]))
    return results, extra


# ---------------------------------------------------------------------------
# baseline: what `check` holds the fleet to
# ---------------------------------------------------------------------------
def expectation(rec):
    """The STABLE part of an observation. Latency, byte counts, patch versions and
    container ids are deliberately excluded — they move on their own."""
    exp = {"state": rec.get("state"), "ok": rec.get("ok"),
           "verdict": rec.get("verdict")}
    if rec.get("health"):
        exp["health"] = rec["health"]
    for p in rec.get("probes", []):
        k = p["kind"]
        if k == "http":
            exp["http"] = p.get("status_class") if p.get("ok") else "unreachable"
        elif k == "tcp":
            exp["tcp"] = bool(p.get("ok"))
        elif k == "postgres":
            exp["postgres_major"] = p.get("major") if p.get("ok") else "unreachable"
        elif k == "redis":
            exp["redis_major"] = p.get("major") if p.get("ok") else "unreachable"
        elif k == "exec":
            exp["exec_user"] = p.get("user") if p.get("ok") else "unreachable"
    return exp


def key(rec):
    return f"{rec['project']}/{rec['service']}"


def load_baseline():
    if not os.path.exists(SMOKE_YML):
        return None
    with open(SMOKE_YML) as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def summarize(rows):
    out = {"services": len(rows)}
    for v in ("ok", "broken", "stopped", "optional", "absent"):
        out[v] = sum(1 for r in rows if r.get("verdict") == v)
    return out


def cmd_record(reg, args):
    results, extra = build(reg, args.project)
    doc = {
        "schema": "fleet-smoke/v1",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("Observed by tools/fleet_smoke.py against the LOCAL fleet stack. "
                 "`services` is the full recording; `expectations` is the stable "
                 "subset that `fleet-smoke check` asserts. Latency, byte counts, "
                 "patch versions and container ids are recorded but never asserted."),
        "summary": summarize(results),
        "services": results,
        "unallocated_containers": extra,
        "expectations": {key(r): expectation(r) for r in results},
    }
    if args.project:
        base = load_baseline() or {}
        if base.get("services"):
            keep = [s for s in base["services"] if s["project"] != args.project]
            doc["services"] = sorted(keep + results, key=lambda r: (r["project"], r["service"]))
            doc["expectations"] = {key(r): expectation(r) for r in doc["services"]}
            doc["summary"] = summarize(doc["services"])
    with open(SMOKE_YML, "w") as fh:
        fh.write("---\n")
        yaml.safe_dump(doc, fh, sort_keys=False, default_flow_style=False, width=100)
    s = doc["summary"]
    print(f"  recorded {s['services']} services -> _data/smoke.yml")
    print(f"    ok={s['ok']}  broken={s['broken']}  stopped={s['stopped']}  "
          f"optional={s['optional']}  absent={s['absent']}")
    broken = [r for r in results if r.get("verdict") == "broken"]
    if broken:
        print("  RUNNING BUT NOT ANSWERING:")
        for r in broken:
            why = next((p for p in r.get("probes", []) if not p.get("ok")), None)
            detail = f"{why['kind']}: {why.get('error') or why.get('detail','')}" if why else "?"
            print(f"    ✗ {key(r)}: {detail}")
    gone = [r for r in results if r.get("verdict") in ("absent", "stopped")]
    if gone:
        print("  NOT RUNNING AND NOT OPTIONAL:")
        for r in gone:
            print(f"    ✗ {key(r)} ({r.get('verdict')})")
    opt = [r for r in results if r.get("verdict") == "optional"]
    if opt:
        print(f"  optional, profile-gated ({len(opt)}): "
              + ", ".join(f"{key(r)}[{','.join(r['profiles'])}]" for r in opt))
    return 0


def cmd_check(reg, args):
    base = load_baseline()
    if not base:
        print("  no baseline — run: tools/dash dev smoke record")
        return 2
    results, _ = build(reg, args.project)
    expected = base.get("expectations") or {}
    regressions, unknown, fixed = [], [], []
    for r in results:
        k = key(r)
        got = expectation(r)
        want = expected.get(k)
        if want is None:
            unknown.append(k)
            continue
        diff = {f: (want.get(f), got.get(f)) for f in set(want) | set(got)
                if want.get(f) != got.get(f)}
        if not diff:
            continue
        # Only a move AWAY from a healthy baseline is a regression.
        if want.get("ok") and not got.get("ok"):
            regressions.append((k, diff, r))
        elif not want.get("ok") and got.get("ok"):
            fixed.append(k)
        else:
            regressions.append((k, diff, r))

    for k, diff, r in regressions:
        print(f"  ✗ {k}")
        for f, (w, g) in sorted(diff.items()):
            print(f"      {f}: expected {w!r}, got {g!r}")
        for p in r.get("probes", []):
            if not p.get("ok"):
                print(f"      probe {p['kind']}: {p.get('error') or p.get('detail','')}")
    for k in fixed:
        print(f"  ~ {k}: now healthy but the baseline says it was not — re-record")
    for k in unknown:
        print(f"  ~ {k}: not in the baseline — re-record")
    if not regressions:
        print(f"  ✓ {len(results)} services match the recorded baseline"
              f"{' (' + str(len(fixed) + len(unknown)) + ' improved/new)' if fixed or unknown else ''}")
    return 1 if regressions else 0


def cmd_show(reg, args):
    base = load_baseline()
    if not base:
        print("  no baseline — run: tools/dash dev smoke record")
        return 2
    print(f"  recorded {base.get('recorded_at')} — {base.get('summary')}")
    print(f"  {'SERVICE':34} {'STATE':9} {'HEALTH':9} PROBES")
    print("  " + "-" * 88)
    for r in base.get("services", []):
        if args.project and r["project"] != args.project:
            continue
        bits = []
        for p in r.get("probes", []):
            k = p["kind"]
            if not p.get("ok"):
                bits.append(f"{k}:FAIL")
            elif k == "http":
                bits.append(f"http:{p.get('status')}")
            elif k == "tcp":
                bits.append("tcp:open")
            elif k == "postgres":
                bits.append(f"pg:{p.get('server_version')}")
            elif k == "redis":
                bits.append(f"redis:{p.get('redis_version')}")
            elif k == "exec":
                bits.append(f"user:{p.get('user')}")
        mark = " " if r["ok"] else "!"
        print(f" {mark}{key(r):34} {r.get('state',''):9} {r.get('health') or '-':9} {' '.join(bits)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Exercise and record the local fleet stack")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("record", "check", "show"):
        p = sub.add_parser(name)
        p.add_argument("--project", help="limit to one project")
    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 0
    with open(PORTS_YML) as fh:
        reg = yaml.safe_load(fh) or {}
    try:
        return {"record": cmd_record, "check": cmd_check, "show": cmd_show}[args.cmd](reg, args)
    except DockerUnavailable as exc:
        sys.stderr.write(f"fleet_smoke: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
