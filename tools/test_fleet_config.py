#!/usr/bin/env python3
"""
Fixture tests for tools/fleet-config.py — the per-repo AI auth order (`ai_auth:`).

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

No network, no gh, no pytest — PyYAML only:

    python3 tools/test_fleet_config.py
"""
from __future__ import annotations

import importlib.util
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
    print(f"{'FAIL' if failures else 'OK'} — fleet-config auth-order tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
