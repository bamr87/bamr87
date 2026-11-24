#!/usr/bin/env python3
"""
Fixture tests for tools/fleet-config.py — the per-repo AI auth order (`ai_auth:`)
and the per-workspace Anthropic API keys (`api_keys:`, `dash keys`).

Guards the properties that make the order safe to change fleet-wide:

  * precedence is `repos:` > `groups:` > `default:`, and a group can select by
    registry category as well as by name;
  * a repo claimed by two groups with DIFFERENT orders, an unknown method, and
    a key that names no fleet repo are all reported as errors, never resolved
    silently;
  * the secret writers send a repo only the credentials its order uses — while
    the hub, the copy the fleet is written from, always keeps every one;
  * the projected variable is `CLAUDE_AUTH_ORDER=<order>` per repo, and nothing
    at all is projected while `ai_auth:` is undeclared or has errors.

It also holds the shape of `observability.activity:`, the activity replay
store's switch and caps (HUB-072, #618): off by default, every cap a positive
integer, sources inside the envelope's enum, and the one redaction list
referenced rather than copied. tools/test_activity_contract.py checks the same
block against the schema's fixtures.

No network, no gh, no pytest — PyYAML only:

    python3 tools/test_fleet_config.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fleet_config", HERE / "fleet-config.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)

REGISTRY = [
    {"name": "alpha", "repo_url": "https://github.com/bamr87/alpha", "category": "docs"},
    {"name": "beta", "repo_url": "https://github.com/bamr87/beta", "category": "docs"},
    {"name": "gamma", "repo_url": "https://github.com/bamr87/gamma", "category": "dev-tools"},
    {"name": "delta", "repo_url": "https://github.com/bamr87/delta", "category": "dev-tools"},
    {"name": "mirror", "repo_url": "https://github.com/someone/mirror", "category": "docs"},
]
HUB = "bamr87/bamr87"


def cfg(**ai_auth) -> dict:
    base = {"hub": {"repo": HUB}}
    if ai_auth:
        base["ai_auth"] = {"methods": {"oauth": "CLAUDE_CODE_OAUTH_TOKEN",
                                       "api_key": "ANTHROPIC_API_KEY"}, **ai_auth}
    return base


def orders(c: dict) -> tuple[dict[str, str], list[str]]:
    resolved, errors = fc.resolve_auth(c, REGISTRY)
    return {nwo.split("/")[-1]: ",".join(r["order"]) + "@" + r["source"]
            for nwo, r in resolved.items()}, errors


def test_default_applies_everywhere_including_the_hub():
    got, errors = orders(cfg(default="oauth,api_key"))
    assert not errors, errors
    assert got == {"bamr87": "oauth,api_key@default", "alpha": "oauth,api_key@default",
                   "beta": "oauth,api_key@default", "gamma": "oauth,api_key@default",
                   "delta": "oauth,api_key@default"}, got
    assert "mirror" not in got, "an external mirror is not ours to configure"


def test_precedence_repo_beats_group_beats_default():
    got, errors = orders(cfg(
        default="oauth,api_key",
        groups={"metered": {"order": "api_key,oauth", "repos": ["alpha", "beta"]},
                "tools": {"order": "api_key", "categories": ["dev-tools"]}},
        repos={"beta": "oauth", "bamr87/delta": "oauth,api_key"}))
    assert not errors, errors
    assert got["alpha"] == "api_key,oauth@group:metered", got
    assert got["beta"] == "oauth@repo", got          # repo beats its group
    assert got["gamma"] == "api_key@group:tools", got  # selected by category
    assert got["delta"] == "oauth,api_key@repo", got  # owner/repo key form
    assert got["bamr87"] == "oauth,api_key@default", got


def test_list_and_string_orders_are_the_same_thing():
    a, _ = orders(cfg(default=["api_key", "oauth"]))
    b, _ = orders(cfg(default="api_key, oauth"))
    assert a == b and a["alpha"].startswith("api_key,oauth"), (a, b)


def test_errors_are_reported_not_resolved_silently():
    _, errors = orders(cfg(
        default="oauth,bedrock",
        groups={"a": {"order": "api_key", "repos": ["alpha"]},
                "b": {"order": "oauth", "categories": ["docs"]},
                "empty": {"order": "oauth"}},
        repos={"nosuch": "oauth"}))
    text = "\n".join(errors)
    assert "unknown method 'bedrock'" in text, text
    assert "bamr87/alpha: in groups a, b with different orders" in text, text
    assert "ai_auth.groups.empty: names neither repos nor categories" in text, text
    assert "'nosuch' is not a fleet repo" in text, text


def test_same_order_in_two_groups_is_not_a_conflict():
    _, errors = orders(cfg(groups={"a": {"order": "api_key", "repos": ["alpha"]},
                                   "b": {"order": "api_key", "categories": ["docs"]}}))
    assert not errors, errors


def test_secrets_follow_the_order_but_the_hub_keeps_everything():
    c = cfg(default="oauth,api_key", repos={"alpha": "api_key", "beta": "oauth"})
    resolved, _ = fc.resolve_auth(c, REGISTRY)
    want = lambda nwo, s: fc.secret_wanted(c, resolved, nwo, s, HUB)  # noqa: E731
    assert want("bamr87/alpha", "ANTHROPIC_API_KEY") and not want("bamr87/alpha", "CLAUDE_CODE_OAUTH_TOKEN")
    assert want("bamr87/beta", "CLAUDE_CODE_OAUTH_TOKEN") and not want("bamr87/beta", "ANTHROPIC_API_KEY")
    assert want("bamr87/gamma", "CLAUDE_CODE_OAUTH_TOKEN") and want("bamr87/gamma", "ANTHROPIC_API_KEY")
    # the hub is the master copy: it holds every fleet secret whatever its order
    c2 = cfg(repos={"bamr87": "api_key"})
    r2, _ = fc.resolve_auth(c2, REGISTRY)
    assert fc.secret_wanted(c2, r2, HUB, "CLAUDE_CODE_OAUTH_TOKEN", HUB)
    # a secret that is not an auth method is never filtered
    assert want("bamr87/alpha", "FLEET_TOKEN")


def test_rotation_targets_drop_repos_whose_order_leaves_the_secret_out():
    c = cfg(repos={"alpha": "api_key"})
    token = {"name": "CLAUDE_CODE_OAUTH_TOKEN", "scope": "fleet"}
    names = {r["name"] for r in fc.rotation_targets(c, REGISTRY, token)}
    assert "alpha" not in names and {"beta", "gamma", "delta", "bamr87"} <= names, names
    key = {"name": "ANTHROPIC_API_KEY", "scope": "fleet"}
    assert "alpha" in {r["name"] for r in fc.rotation_targets(c, REGISTRY, key)}


def test_the_projected_variable_is_per_repo_and_only_when_declared():
    assert fc.auth_variables(cfg(), REGISTRY) == {}, "an undeclared ai_auth must project nothing"
    c = cfg(default="oauth,api_key", repos={"alpha": "api_key,oauth"})
    got = fc.auth_variables(c, REGISTRY)
    assert got["bamr87/alpha"] == {"CLAUDE_AUTH_ORDER": "api_key,oauth"}, got
    assert got["bamr87/beta"] == {"CLAUDE_AUTH_ORDER": "oauth,api_key"}, got
    broken = cfg(default="oauth,nope")
    assert fc.auth_variables(broken, REGISTRY) == {}, "a config with errors must project nothing"


def test_the_live_fleet_contract_resolves_cleanly():
    """The committed ai_auth: block must always resolve without errors."""
    live = fc.load(fc.FLEET)
    registry = fc.load(fc.REGISTRY)
    registry = registry["projects"] if isinstance(registry, dict) else registry
    resolved, errors = fc.resolve_auth(live, registry)
    assert not errors, errors
    assert resolved, "no repos resolved from the live registry"


# --------------------------------------------------------------------------- #
# rotation ledger — post-write rows (`dash secrets rotate`)
# --------------------------------------------------------------------------- #
ROT_TOKEN = {"name": "RELEASE_PLEASE_TOKEN", "scope": "fleet",
             "_rotation": {"max_age_days": 45, "lifetime_days": 365}}


def survey_rows() -> list[dict]:
    """What a survey sees BEFORE the writes (the 2026-11-02 run's shape)."""
    return [
        {"nwo": "bamr87/had", "state": fc.S_OK, "age_days": 3,
         "updated_at": "2026-10-30T02:12:00Z", "behind_hub": False},
        {"nwo": "bamr87/old", "state": fc.S_STALE, "age_days": 86,
         "updated_at": "2026-08-07T04:28:46Z", "behind_hub": True},
        {"nwo": "bamr87/new", "state": fc.S_MISSING, "age_days": None,
         "updated_at": None, "behind_hub": False},
        {"nwo": "bamr87/broke", "state": fc.S_MISSING, "age_days": None,
         "updated_at": None, "behind_hub": False},
    ]


def test_an_applied_rotation_publishes_the_rows_it_left_behind():
    e = fc.ledger_entry(ROT_TOKEN, survey_rows(), "seed", False,
                        ["bamr87/old", "bamr87/new", "bamr87/broke"], ["bamr87/broke"], [],
                        applied=True, written_at="2026-11-02T02:20:00Z")
    rows = {r["nwo"]: r for r in e["repos"]}
    assert rows["bamr87/new"]["state"] == "ok" and rows["bamr87/new"]["age_days"] == 0
    assert rows["bamr87/new"]["updated_at"] == "2026-11-02T02:20:00Z"
    assert rows["bamr87/new"]["observed_state"] == "missing"
    assert rows["bamr87/old"]["state"] == "ok" and rows["bamr87/old"]["observed_age_days"] == 86
    assert rows["bamr87/old"]["behind_hub"] is False
    # A failed write keeps what was seen, and carries no observed_* fields.
    assert rows["bamr87/broke"]["state"] == "missing" and rows["bamr87/broke"]["action"] == "failed"
    assert "observed_state" not in rows["bamr87/broke"]
    assert e["oldest_age_days"] == 3, e["oldest_age_days"]          # not the replaced 86
    assert e["observed_oldest_age_days"] == 86
    assert e["counts"] == {"repos": 4, "ok": 3, "stale": 0, "missing": 1, "unreachable": 0,
                           "written": 3, "failed": 1}


def test_a_dry_run_ledger_still_reports_what_it_observed():
    e = fc.ledger_entry(ROT_TOKEN, survey_rows(), "seed", False,
                        ["bamr87/old", "bamr87/new"], [], [])
    rows = {r["nwo"]: r for r in e["repos"]}
    assert rows["bamr87/new"]["state"] == "missing" and rows["bamr87/new"]["action"] == "written"
    assert "observed_state" not in rows["bamr87/new"]
    assert e["oldest_age_days"] == 86 and "observed_oldest_age_days" not in e
    assert e["counts"]["missing"] == 2 and e["counts"]["stale"] == 1


# --------------------------------------------------------------------------- #
# api_keys: — Console keys per workspace (`dash keys`)
# --------------------------------------------------------------------------- #
from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
KREG = REGISTRY + [{"name": "2005", "repo_url": "https://github.com/year-of-ai/2005", "category": "docs"}]
POLICY = {"lifetime_days": 7, "renew_before_days": 2}


def kcfg(**extra) -> dict:
    c = cfg()
    c["api_keys"] = {"workspaces": {"ws-a": {"repos": ["alpha"]},
                                    "year": {"owners": ["year-of-ai"], "repos": ["year-of-ai/site"]}},
                     **extra}
    return c


def key(kid, ws, value, *, status="active", created=-1.0, life=7.0):
    created_at = NOW + timedelta(days=created)
    return {"id": kid, "name": kid, "status": status, "created_at": created_at.isoformat(),
            "expires_at": None if life is None else (created_at + timedelta(days=life)).isoformat(),
            "partial_key_hint": value[:10] + "..." + value[-4:], "scope_workspace_id": ws}


def test_key_targets_claim_by_name_owner_and_explicit_slug_the_rest_default():
    targets, errors = fc.key_targets(kcfg(), KREG)
    assert not errors, errors
    slot = {nwo: t["slot"] for nwo, t in targets.items()}
    assert slot["bamr87/alpha"] == "ws-a", slot
    assert slot["year-of-ai/2005"] == "year" and slot["year-of-ai/site"] == "year", slot
    assert slot["bamr87/beta"] == "default" and slot["bamr87/bamr87"] == "default", slot


def test_key_targets_report_conflicts_and_unknown_repos():
    c = kcfg()
    c["api_keys"]["workspaces"]["ws-b"] = {"repos": ["alpha", "nosuch"]}
    _, errors = fc.key_targets(c, KREG)
    text = "\n".join(errors)
    assert "bamr87/alpha: claimed by workspaces ws-a and ws-b" in text, text
    assert "'nosuch' is not a registry repo" in text, text


def test_key_targets_honour_the_ai_auth_order():
    c = kcfg()
    c["ai_auth"] = {"methods": {"oauth": "CLAUDE_CODE_OAUTH_TOKEN", "api_key": "ANTHROPIC_API_KEY"},
                    "repos": {"beta": "oauth"}}
    targets, _ = fc.key_targets(c, KREG)
    assert targets["bamr87/beta"]["skip"], "a repo whose order leaves api_key out must not get a key"
    assert not targets["bamr87/alpha"]["skip"]


def test_hint_matching_and_candidates_never_take_admin_or_oauth_values():
    v = "sk-ant-api03-abcdefgh-XYZ1"
    assert fc.hint_matches("sk-ant-api...XYZ1", v) and not fc.hint_matches("sk-ant-api...XYZ2", v)
    assert not fc.hint_matches(None, v) and not fc.hint_matches("sk-ant-api", v)
    cands = fc.key_candidates({"ANTHROPIC_API_KEY": v, "ANTHROPIC_API_KEY_OLD": "sk-ant-admin01-x",
                               "ANTHROPIC_API_KEY_O": "sk-ant-oat01-x", "OTHER": v,
                               "ANTHROPIC_API_KEY_NOTAKEY": "hello"}, "ANTHROPIC_API_KEY")
    assert cands == {"ANTHROPIC_API_KEY": v}, cands


def test_plan_takes_the_newest_active_key_and_applies_the_policy():
    ws = {"ws-a": "W_A", "year": "W_Y"}
    old, new = "sk-ant-api03-old-aaaa1111", "sk-ant-api03-new-bbbb2222"
    forever, dflt = "sk-ant-api03-forever-cccc", "sk-ant-api03-dflt-dddd4444"
    keys = [key("k_old", "W_A", old, created=-6), key("k_new", "W_A", new, created=-0.5),
            key("k_forever", "W_Y", forever, life=None),
            key("k_dflt", "W_DEFAULT", dflt, created=-6.5)]
    values = {"A": old, "B": new, "C": forever, "D": dflt}
    plan = fc.plan_keys(["default", "ws-a", "year"], ws, keys, values, POLICY, now=NOW)
    assert plan["ws-a"]["key"]["id"] == "k_new" and plan["ws-a"]["issues"] == [], plan["ws-a"]
    assert plan["ws-a"]["others_active"] == ["k_old"], plan["ws-a"]
    assert "never-expires" in plan["year"]["issues"], plan["year"]
    # an unnamed workspace is the Default one
    assert plan["default"]["key"]["id"] == "k_dflt" and "renew-soon" in plan["default"]["issues"], plan["default"]
    long = fc.plan_keys(["ws-a"], ws, [key("k30", "W_A", new, life=30)], {"B": new}, POLICY, now=NOW)
    assert "lifetime-too-long" in long["ws-a"]["issues"], long
    gone = fc.plan_keys(["ws-a"], ws, [key("kx", "W_A", new, status="expired")], {"B": new}, POLICY, now=NOW)
    assert gone["ws-a"]["key"] is None and gone["ws-a"]["issues"] == ["expired-in-env"], gone
    missing = fc.plan_keys(["ws-a"], ws, [], {}, POLICY, now=NOW)
    assert missing["ws-a"]["issues"] == ["no-key-in-env"], missing


def test_watch_judges_the_deployed_keys_from_the_ledger():
    v = "sk-ant-api03-deployed-eeee5555"
    ledger = {"slots": {"ws-a": {"key_id": "k1"}, "year": {"key_id": "k_gone"}}}
    keys = [key("k1", "W_A", v, created=-5.5)]
    plan = fc.watch_plan(["default", "ws-a", "year"], ledger, keys, {"ANTHROPIC_API_KEY": v}, POLICY, now=NOW)
    assert plan["default"]["issues"] == ["not-deployed"], plan["default"]
    assert plan["ws-a"]["issues"] == ["renew-soon"] and plan["ws-a"]["key"]["env"] == "ANTHROPIC_API_KEY", plan["ws-a"]
    assert plan["year"]["issues"] == ["disabled"], plan["year"]


def test_a_managed_secret_is_left_to_its_owner():
    c = {"tokens": [{"name": "ANTHROPIC_API_KEY", "scope": "fleet", "managed_by": "keys",
                     "rotation": {"enabled": True}},
                    {"name": "CLAUDE_CODE_OAUTH_TOKEN", "scope": "fleet", "rotation": {"enabled": True}}]}
    names = [t["name"] for t in fc.rotating_tokens(c)]
    assert names == ["CLAUDE_CODE_OAUTH_TOKEN"], names
    assert [t["name"] for t in fc.rotating_tokens(c, ["ANTHROPIC_API_KEY"])] == [], \
        "--only must not smuggle a managed secret into the weekly rotation"
    plan = fc.push_plan(c["tokens"], {"ANTHROPIC_API_KEY": "sk-ant-api03-x", "CLAUDE_CODE_OAUTH_TOKEN": "t"})
    assert plan["push"] == ["CLAUDE_CODE_OAUTH_TOKEN"] and plan["managed"] == ["ANTHROPIC_API_KEY"], plan
    assert "ANTHROPIC_API_KEY" not in plan["ignored"], plan


def test_the_live_api_keys_contract_resolves_cleanly():
    live = fc.load(fc.FLEET)
    targets, errors = fc.key_targets(live, fc.load(fc.REGISTRY))
    assert not errors, errors
    assert {t["slot"] for t in targets.values()} >= {"default", "bamr87"}, targets


def test_the_live_api_keys_contract_names_no_moved_repo():
    """#337: bash-365.com moved from amr-bash/ to the bash-365 org and joined the
    registry, but its workspace still claimed the old owner/repo, so `dash keys
    rotate` targeted a name GitHub's GraphQL API no longer resolves. A repo the
    registry knows is claimed by its registry name, which follows a transfer."""
    live = fc.load(fc.FLEET)
    registry = fc.load(fc.REGISTRY)
    targets, _ = fc.key_targets(live, registry)
    slot = {nwo: t["slot"] for nwo, t in targets.items()}
    assert slot.get("bash-365/bash-365.com") == "bash-365.com", \
        {n: s for n, s in slot.items() if "bash-365" in n}
    assert not [n for n in targets if n.split("/")[0] == "amr-bash"], sorted(targets)

    by_name = {str(p.get("name")): fc.owner_repo(p.get("repo_url") or "") for p in registry}
    stale = [f"{ws}: {entry} (the registry has {by_name[entry.split('/')[-1]]})"
             for ws, spec in live["api_keys"]["workspaces"].items()
             for entry in (spec or {}).get("repos") or []
             if "/" in entry and by_name.get(entry.split("/")[-1]) not in (None, entry)]
    assert not stale, f"an explicit owner/repo shadows a moved registry repo: {stale}"


def test_inventory_reads_the_workspace_from_scope_and_tolerates_org_scoped_keys():
    """#522: the SDK's BetaAPIKey has no top-level workspace_id; an
    organization-scoped key has none at all. Neither may crash the watch."""
    from types import SimpleNamespace as NS

    def k(kid, scope, **extra):
        return NS(id=kid, name=kid, status="active", created_at=NOW, expires_at=None,
                  partial_key_hint="sk-ant-api03-ab...wxyz", scope=scope, **extra)

    keys = [k("ws", NS(type="workspace", workspace_id="wrkspc_A")),
            k("org", NS(type="organization")),
            k("legacy", None, workspace_id="wrkspc_B")]
    admin = NS(beta=NS(organization=NS(workspaces=NS(list=lambda limit: [NS(name="A", id="wrkspc_A")]),
                                       api_keys=NS(list=lambda limit: keys))))
    workspaces, inv = fc.console_inventory(admin)
    assert workspaces == {"A": "wrkspc_A"}, workspaces
    assert [r["scope_workspace_id"] for r in inv] == ["wrkspc_A", None, "wrkspc_B"], inv


# --------------------------------------------------------------------------- #
# observability.activity — the activity replay store's switch and caps (#618)
# --------------------------------------------------------------------------- #
ACTIVITY_CAPS = ("max_events_per_s", "payload_max_bytes", "spool_max_events", "stream_maxlen", "hook_budget_ms")


def _dotted(doc: dict, path: str):
    for part in path.split("."):
        assert isinstance(doc, dict) and part in doc, f"{path}: no {part!r}"
        doc = doc[part]
    return doc


def _activity() -> dict:
    act = _dotted(fc.load(fc.FLEET), "observability.activity")
    assert isinstance(act, dict), "observability.activity must be a mapping"
    return act


def test_the_activity_block_ships_off_and_bounded():
    """Off until Amr approves the deploy step (§ 10.5); every cap a positive
    integer the code enforces (NFR13); retention by monthly partition, with
    rollups kept longer than raw rows."""
    act = _activity()
    assert act.get("enabled") is False, "activity capture stays off until the deploy step is approved"
    assert act.get("profile") == "activity", act.get("profile")
    caps = act.get("caps") or {}
    for key in ACTIVITY_CAPS:
        val = caps.get(key)
        assert isinstance(val, int) and not isinstance(val, bool) and val > 0, f"caps.{key} = {val!r}"
    assert caps["hook_budget_ms"] <= 50, "a hook must return within 50 ms (#620 acceptance, NFR4)"
    ret = act.get("retention") or {}
    assert ret.get("partition") == "month", ret
    assert 0 < ret.get("raw_days", 0) < ret.get("rollup_days", 0), ret
    bus, store = act.get("bus") or {}, act.get("store") or {}
    assert bus.get("channel") and bus.get("stream"), bus
    assert store.get("service") == "db", "the store lives in the shared Postgres, no new engine"
    assert act.get("resource_samples") == "metrics", "container samples belong to Prometheus, not the ledger"


def test_the_activity_sources_are_an_allowlist_inside_the_envelope():
    act = _activity()
    path = fc.REPO_ROOT / str(act.get("schema") or "")
    assert path.is_file(), f"observability.activity.schema names no file: {act.get('schema')!r}"
    schema = json.loads(path.read_text(encoding="utf-8"))
    known = set(schema["properties"]["source"]["enum"])
    sources = act.get("sources") or []
    assert sources and len(set(sources)) == len(sources), sources
    assert set(sources) <= known, f"not in {act['schema']}: {sorted(set(sources) - known)}"
    assert "harness" not in sources, "harness is reserved for the harness protocol (#626)"


def test_the_activity_block_references_the_one_redaction_list():
    live = fc.load(fc.FLEET)
    ref = _activity().get("redact")
    assert ref == "observability.logs.redact", "one redaction list for every plane: referenced, never copied"
    prefixes = _dotted(live, ref)
    assert isinstance(prefixes, list) and prefixes and all(isinstance(p, str) and p for p in prefixes), prefixes


# --------------------------------------------------------------------------- #
# push — file-backed values and the shape check (`dash secrets push`)
#
# The release app's private key is a PEM file: many lines, where a dotenv value
# is one. The key text is assembled here rather than written out, so no file in
# the repo holds something a secret scanner reads as a private key.
# --------------------------------------------------------------------------- #
import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402


def _pem(kind: str = "RSA ", lines: int = 3, sep: str = "\n") -> str:
    body = sep.join("QUJD" * 16 for _ in range(lines))
    return f"-----BEGIN {kind}PRIVATE KEY-----{sep}{body}{sep}-----END {kind}PRIVATE KEY-----"


def _live_policy(name: str) -> dict:
    token = next(t for t in fc.load(fc.FLEET)["tokens"] if t["name"] == name)
    return fc.token_rotation_policy(token)


def _key_ok(value: str) -> bool:
    pol = _live_policy("RELEASE_APP_PRIVATE_KEY")
    return fc.value_looks_right(value, pol["value_prefixes"], pol["value_pattern"])


def test_a_secret_named_by_file_is_read_from_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "app.pem").write_text(_pem() + "\n")
        got, errors = fc.file_backed_values({"KEY_FILE": "app.pem", "OTHER": "x"}, ["KEY", "OTHER"], base)
        assert not errors, errors
        assert got["KEY"] == _pem(), "the file's contents, without the trailing newline"
        assert got["OTHER"] == "x" and got["KEY_FILE"] == "app.pem"
        # An absolute path is taken as written.
        got, errors = fc.file_backed_values({"KEY_FILE": str(base / "app.pem")}, ["KEY"], Path("/nonexistent"))
        assert not errors and got["KEY"] == _pem(), errors


def test_a_file_pointer_that_cannot_supply_a_value_is_an_error_not_a_skip():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "empty.pem").write_text("\n")
        (base / "app.pem").write_text(_pem())
        _, errors = fc.file_backed_values({"KEY_FILE": "missing.pem"}, ["KEY"], base)
        assert len(errors) == 1 and "missing.pem" in errors[0], errors
        _, errors = fc.file_backed_values({"KEY_FILE": "empty.pem"}, ["KEY"], base)
        assert len(errors) == 1 and "empty" in errors[0], errors
        got, errors = fc.file_backed_values({"KEY": "inline", "KEY_FILE": "app.pem"}, ["KEY"], base)
        assert len(errors) == 1 and "both set" in errors[0], errors
        assert got["KEY"] == "inline", "an ambiguous pair must not be resolved either way"
        assert all(_pem() not in e for e in errors), "an error never quotes a value"
        # A name nobody asked for is left alone, broken pointer and all.
        _, errors = fc.file_backed_values({"KEY_FILE": "missing.pem"}, ["OTHER"], base)
        assert not errors, errors


def test_a_file_pointer_is_not_reported_as_a_stray_key():
    tokens = [{"name": "RELEASE_APP_PRIVATE_KEY", "scope": "fleet"}]
    values = {"RELEASE_APP_PRIVATE_KEY": _pem(), "RELEASE_APP_PRIVATE_KEY_FILE": "app.pem", "JEKYLL_PORT": "4000"}
    plan = fc.push_plan(tokens, values)
    assert plan["push"] == ["RELEASE_APP_PRIVATE_KEY"], plan
    assert plan["ignored"] == ["JEKYLL_PORT"], plan


def test_a_key_cut_off_after_its_first_line_is_not_a_key():
    assert _key_ok(_pem()), "a whole key, real newlines"
    assert _key_ok(_pem(kind="")), "PKCS#8 has no algorithm in its header"
    assert _key_ok(_pem(sep="\\n")), "one line with \\n escapes: the token action unescapes it"
    assert _key_ok(_pem(sep="\\n") + "\\n"), "the escaped form often ends in an escape"
    first_line = _pem().splitlines()[0]
    assert not _key_ok(first_line), "what a dotenv parser keeps of a pasted key"
    assert not _key_ok('"' + first_line), "the same paste, with its opening quote"
    assert not _key_ok(_pem().rsplit("-----END", 1)[0].rstrip()), "a key missing its last line"
    assert not _key_ok("github_pat_x"), "another credential in the key's place"


def test_a_client_id_is_shaped_like_one_and_a_pat_still_is():
    pol = _live_policy("RELEASE_APP_CLIENT_ID")
    assert fc.value_looks_right("Iv23liABCDEF", pol["value_prefixes"], pol["value_pattern"])
    assert fc.value_looks_right("Iv1.0123456789abcdef", pol["value_prefixes"], pol["value_pattern"])
    assert not fc.value_looks_right("1234567", pol["value_prefixes"], pol["value_pattern"]), \
        "the numeric App ID is the deprecated input"
    # No pattern declared: the prefix check alone decides, as it always did.
    assert fc.value_looks_right("github_pat_x", ["github_pat_", "ghp_"])
    assert not fc.value_looks_right(" github_pat_x", ["github_pat_"])
    assert "whole value" in fc.shape_hint({"value_prefixes": ["-----BEGIN "], "value_pattern": "x"})
    assert fc.shape_hint({"value_prefixes": []}) == "non-empty"


def test_the_release_app_never_asks_for_a_re_mint_and_always_propagates():
    """An app's client ID and key do not expire: `lifetime_days: 0` is what
    keeps the weekly loop from opening a "needs-mint" issue a year from now."""
    live = fc.load(fc.FLEET)
    rotating = {t["name"]: t for t in fc.rotating_tokens(live)}
    for name in ("RELEASE_APP_CLIENT_ID", "RELEASE_APP_PRIVATE_KEY"):
        assert name in rotating, f"{name} must ride the weekly rotation"
        assert rotating[name]["scope"] == "fleet" and not rotating[name].get("required"), name
        pol = rotating[name]["_rotation"]
        old = [{"nwo": "bamr87/bamr87", "state": fc.S_OK, "age_days": 4000}]
        assert not fc.needs_human_mint(old, pol, "bamr87/bamr87", False), name
    wf = (fc.REPO_ROOT / ".github" / "workflows" / "token-rotation.yml").read_text()
    for name in ("RELEASE_APP_CLIENT_ID", "RELEASE_APP_PRIVATE_KEY"):
        assert f"{name}: ${{{{ secrets.{name} }}}}" in wf, f"{name} is never handed to the rotation"


def test_a_multi_line_value_is_masked_line_by_line():
    """`::add-mask::` reads one line. A PEM key handed over whole would mask
    its first line and print every other line into the Actions log."""
    value = _pem()
    before = os.environ.get("GITHUB_ACTIONS")
    os.environ["GITHUB_ACTIONS"] = "true"
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fc.mask(value + "\n\n")
    finally:
        if before is None:
            del os.environ["GITHUB_ACTIONS"]
        else:
            os.environ["GITHUB_ACTIONS"] = before
    printed = out.getvalue().splitlines()
    assert printed == [f"::add-mask::{line}" for line in value.splitlines()], printed


# --------------------------------------------------------------------------- #
# CODEX_AUTH_JSON — the OpenAI ChatGPT-login bundle (openai_auth:). It carries
# its own refresh token, the weekly loop is its one refresher, and a dry run
# must never refresh it: the grant consumes the refresh token it is handed.
# Token text is assembled here so no file holds something shaped like a JWT.
# --------------------------------------------------------------------------- #
def _codex_bundle(refresh: str = "rt-old", **extra) -> str:
    tokens = {"id_token": "id-old", "access_token": "at-old",
              "refresh_token": refresh, "account_id": "acct"}
    return json.dumps({"OPENAI_API_KEY": None, "tokens": tokens,
                       "last_refresh": "2026-11-01T00:00:00Z", **extra}, indent=2)


@contextlib.contextmanager
def _env(**values):
    before = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v is not None})
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_openai_bundle_rides_the_rotation_and_is_shaped_like_a_chatgpt_login():
    live = fc.load(fc.FLEET)
    rotating = {t["name"]: t for t in fc.rotating_tokens(live)}
    assert "CODEX_AUTH_JSON" in rotating, "the OpenAI bundle must ride the weekly rotation"
    tok = rotating["CODEX_AUTH_JSON"]
    pol = tok["_rotation"]
    assert tok["scope"] == "fleet" and not tok.get("required")
    assert pol["refresh"]["kind"] == fc.REFRESH_KIND_CODEX
    assert pol["refresh"]["secret"] == "CODEX_AUTH_JSON", "the bundle refreshes itself"
    assert live["openai_auth"]["secret"] == "CODEX_AUTH_JSON"
    compact = json.dumps(json.loads(_codex_bundle()), separators=(",", ":"))
    assert fc.value_looks_right(compact, pol["value_prefixes"], pol["value_pattern"])
    assert fc.value_looks_right(_codex_bundle(), pol["value_prefixes"], pol["value_pattern"]), \
        "auth.json as `codex login` writes it, indented"
    api_key_login = json.dumps({"OPENAI_API_KEY": "sk-x", "tokens": None})
    assert not fc.value_looks_right(api_key_login, pol["value_prefixes"], pol["value_pattern"]), \
        "an API-key login has no refresh token and must never reach the fleet"
    old = [{"nwo": "bamr87/bamr87", "state": fc.S_OK, "age_days": 4000}]
    assert not fc.needs_human_mint(old, pol, "bamr87/bamr87", False), "no fixed lifetime"
    wf = (fc.REPO_ROOT / ".github" / "workflows" / "token-rotation.yml").read_text()
    assert "CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}" in wf, "never handed to the rotation"
    allowed = live["ai_models"]["allowed"]["openai"]
    for role, model in live["openai_auth"]["models"].items():
        assert model in allowed, f"openai_auth.models.{role} {model!r} is not in ai_models.allowed.openai"


def test_a_bundle_without_a_refresh_token_is_refused_before_any_grant():
    bundle, why = fc.codex_bundle(json.dumps({"OPENAI_API_KEY": "sk-x"}))
    assert bundle is None and "refresh_token" in why, why
    bundle, why = fc.codex_bundle("not json")
    assert bundle is None and "JSON" in why, why
    bundle, why = fc.codex_bundle(_codex_bundle(OPENAI_API_KEY="sk-x"))
    assert bundle is None and "OPENAI_API_KEY" in why, why
    bundle, why = fc.codex_bundle(_codex_bundle())
    assert bundle and not why


def test_a_dry_run_never_refreshes_the_openai_bundle():
    pol = _live_policy("CODEX_AUTH_JSON")
    calls = []
    real = fc.oauth_refresh
    fc.oauth_refresh = lambda *a, **k: calls.append(a) or (None, "unexpected")
    try:
        with _env(CODEX_AUTH_JSON=_codex_bundle()), contextlib.redirect_stdout(io.StringIO()):
            token = {"name": "CODEX_AUTH_JSON"}
            value, source, minted, _ = fc.resolve_value(token, pol, "auto", apply=False)
            assert not calls, "a dry run consumed the refresh token"
            assert value == _codex_bundle().strip() and source == "seed" and not minted
            value, source, minted, note = fc.resolve_value(token, pol, "refresh", apply=False)
            assert value is None and not minted and "--apply" in note, note
            assert not calls
    finally:
        fc.oauth_refresh = real


def test_an_applied_refresh_rewrites_the_tokens_and_stamps_last_refresh():
    pol = _live_policy("CODEX_AUTH_JSON")
    seen = {}

    def fake(policy, refresh_token):
        seen["policy"], seen["refresh_token"] = policy, refresh_token
        return {"access_token": "at-new", "refresh_token": "rt-new", "id_token": "id-new",
                "expires_in": 864000, "endpoint": policy["endpoints"][0]}, ""

    real = fc.oauth_refresh
    fc.oauth_refresh = fake
    try:
        with _env(CODEX_AUTH_JSON=_codex_bundle()), contextlib.redirect_stdout(io.StringIO()):
            token = {"name": "CODEX_AUTH_JSON"}
            value, source, minted, note = fc.resolve_value(token, pol, "auto", apply=True)
    finally:
        fc.oauth_refresh = real
    assert minted and source == "refresh", (source, note)
    assert note == "refreshed the ChatGPT OAuth bundle via " + pol["refresh"]["endpoints"][0], note
    assert seen["refresh_token"] == "rt-old" and seen["policy"].get("scope"), seen
    fresh = json.loads(value)
    assert "\n" not in value, "one line, so the log scrubber masks it whole"
    assert fresh["tokens"] == {"id_token": "id-new", "access_token": "at-new",
                               "refresh_token": "rt-new", "account_id": "acct"}, fresh
    assert fresh["last_refresh"] > "2026-11-01", "the stamp consumers judge freshness by"
    assert fc.value_looks_right(value, pol["value_prefixes"], pol["value_pattern"])


def test_a_failed_openai_refresh_falls_back_and_asks_for_a_reseed():
    pol = _live_policy("CODEX_AUTH_JSON")
    real = fc.oauth_refresh
    fc.oauth_refresh = lambda *a, **k: (None, "https://auth.openai.com/oauth/token → HTTP 401")
    try:
        with _env(CODEX_AUTH_JSON=_codex_bundle()), contextlib.redirect_stdout(io.StringIO()):
            token = {"name": "CODEX_AUTH_JSON"}
            value, source, minted, _ = fc.resolve_value(token, pol, "auto", apply=True)
            assert value and source == "seed" and not minted, "propagation still runs"
            assert "401" in token["_refresh_failed"]
            value, _, minted, note = fc.resolve_value({"name": "CODEX_AUTH_JSON"}, pol, "refresh", apply=True)
            assert value is None and not minted and "401" in note
    finally:
        fc.oauth_refresh = real
    assert "needs-reseed" in fc.REASON_TEXT


def test_the_refresh_grant_sends_a_scope_only_when_the_policy_names_one():
    sent = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.body

    def fake_urlopen(req, timeout=0):
        sent.append(json.loads(req.data.decode()))
        return Resp(b'{"access_token": "a", "refresh_token": "r", "id_token": "i"}')

    real = fc.urllib.request.urlopen
    fc.urllib.request.urlopen = fake_urlopen
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            got, _ = fc.oauth_refresh({"endpoints": ["https://x"], "client_id": "c", "scope": "openid"}, "r0")
            fc.oauth_refresh({"endpoints": ["https://x"], "client_id": "c"}, "r0")
    finally:
        fc.urllib.request.urlopen = real
    assert sent[0]["scope"] == "openid" and "scope" not in sent[1], sent
    assert got["id_token"] == "i"


def test_variable_overrides_are_per_repo_exceptions_to_the_canonical_values():
    repos = fc.fleet_repos(cfg(), REGISTRY)
    c = {**cfg(), "variables": {"PR_AI_REVIEW_ENABLED": "true", "NODE_VERSION": "20"},
         "variable_overrides": {"alpha": {"PR_AI_REVIEW_ENABLED": False}, "bamr87/gamma": {"NODE_VERSION": 22}}}
    got, errors = fc.variable_overrides(c, repos)
    assert errors == [], errors
    assert got == {"bamr87/alpha": {"PR_AI_REVIEW_ENABLED": "False"}, "bamr87/gamma": {"NODE_VERSION": "22"}}, got
    assert fc.variable_overrides(cfg(), repos) == ({}, []), "no overrides declared, nothing to except"


def test_variable_overrides_refuse_what_the_contract_does_not_declare():
    repos = fc.fleet_repos(cfg(), REGISTRY)
    c = {**cfg(), "variables": {"PR_AI_REVIEW_ENABLED": "true"}}
    for raw, why in (({"nowhere": {"PR_AI_REVIEW_ENABLED": "false"}}, "not a fleet repo"),
                     ({"mirror": {"PR_AI_REVIEW_ENABLED": "false"}}, "not a fleet repo"),
                     ({"alpha": {"SOMETHING_ELSE": "x"}}, "not declared in variables:"),
                     ({"alpha": {}}, "at least one"),
                     ({"alpha": "false"}, "at least one"),
                     (["alpha"], "must be a mapping")):
        got, errors = fc.variable_overrides({**c, "variable_overrides": raw}, repos)
        assert got == {} and any(why in e for e in errors), (raw, got, errors)


def test_the_live_variable_contract_is_clean():
    """The committed variables: and variable_overrides: blocks always resolve, and the fleet's PR
    review switches are projected on (the maintainer's ruling of 2026-11-23)."""
    live = fc.load(fc.FLEET)
    registry = fc.load(fc.REGISTRY)
    _, errors = fc.variable_overrides(live, fc.fleet_repos(live, registry))
    assert errors == [], errors
    for name in ("PR_AI_REVIEW_ENABLED", "PR_READINESS_ENABLED", "PR_AI_ANALYSIS_ENABLED"):
        assert str(live["variables"].get(name)) == "true", name


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
    print(f"{'FAIL' if failures else 'OK'} — fleet-config auth-order and activity-block tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
