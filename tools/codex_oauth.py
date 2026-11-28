"""codex_oauth.py — the OpenAI ChatGPT-login bundle (CODEX_AUTH_JSON) in the weekly rotation.

`tools/fleet-config.py rotate` is the fleet's one refresher of this bundle
(`openai_auth:` and the CODEX_AUTH_JSON entry in `_data/fleet.yml`,
docs/OPENAI-AUTH.md). This module is the provider-specific half it loads by
path: what a bundle must look like, how a refresh rewrites it, and when a run
may refresh at all. The grant itself (`oauth_refresh`), the log scrubber
(`mask`) and the clock are fleet-config's and are passed in, so the tests can
replace each one and this file holds no credential plumbing of its own.

The rules:
  - a ChatGPT login writes `tokens: {id_token, access_token, refresh_token,
    account_id}` and `last_refresh`; an API-key login writes OPENAI_API_KEY and
    no refresh token, and never reaches the fleet;
  - OpenAI's refresh tokens rotate, so a refresh consumes the stored one: only
    an applying run refreshes (a dry run that did would leave every stored copy
    dead), and the caller writes the new bundle hub-first to every repo;
  - a refresh that fails falls back to propagating the seeded bundle and is
    flagged `needs-reseed`, because consumers stop using it within days.
"""
from __future__ import annotations

import json
import os

KIND = "codex_auth_json"  # rotation.refresh.kind in the token contract


def parse(text: str, mask) -> tuple[dict | None, str]:
    """(bundle, "") for a refreshable ChatGPT login, else (None, why). Masks every token."""
    try:
        bundle = json.loads(text)
    except (TypeError, ValueError):
        return None, "the value is not JSON (expected the auth.json `codex login` writes)"
    if not isinstance(bundle, dict):
        return None, "the value is not a JSON object"
    tokens = bundle.get("tokens")
    if not isinstance(tokens, dict) or not tokens.get("refresh_token"):
        return None, "no tokens.refresh_token in the bundle (an API-key login, or a truncated paste)"
    if bundle.get("OPENAI_API_KEY"):
        return None, "the bundle carries an OPENAI_API_KEY; seed a ChatGPT login, never a key"
    for key in ("access_token", "refresh_token", "id_token"):
        if tokens.get(key):
            mask(str(tokens[key]))
    return bundle, ""


def refresh(policy: dict, text: str, *, grant, mask, now) -> tuple[str | None, str]:
    """Run the grant on the bundle's refresh token and return the new auth.json.

    UNOFFICIAL, on the same footing as the Claude grant: it is the endpoint the
    Codex CLI refreshes with. The result is one compact line, stamped with
    `last_refresh` (what every consumer judges freshness by), so the log
    scrubber masks it whole.
    """
    bundle, why = parse(text, mask)
    if bundle is None:
        return None, why
    tokens = dict(bundle["tokens"])
    result, why = grant(policy, tokens["refresh_token"])
    if result is None:
        return None, why
    tokens["access_token"] = result["access_token"]
    for key in ("refresh_token", "id_token"):
        if result.get(key):
            tokens[key] = result[key]
    fresh = {**bundle, "tokens": tokens, "last_refresh": now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    value = json.dumps(fresh, separators=(",", ":"))
    mask(value)
    return value, f"refreshed the ChatGPT OAuth bundle via {result['endpoint']}"


def resolve(token: dict, policy: dict, source: str, apply: bool, *, grant, mask, now,
            log=print) -> tuple[str | None, str, bool, str] | None:
    """fleet-config's resolve_value for this kind: a (value, source, minted, note)
    decision, or None to fall through to the seeded value. A failed refresh is
    left on `token["_refresh_failed"]` for the run's `needs-reseed` flag."""
    secret = policy.get("secret") or token["name"]
    seeded = os.environ.get(secret, "").strip()
    if not seeded:
        if source == "refresh":
            return None, "refresh", False, f"{secret} is not in the environment — nothing to refresh"
        return None
    if not apply:
        mask(seeded)
        if source == "refresh":
            return None, "refresh", False, ("dry run: the ChatGPT OAuth bundle is refreshed only with "
                                            "--apply (the grant consumes its refresh token)")
        log("  \033[2mdry run: would refresh the ChatGPT OAuth bundle; planning with the seeded value\033[0m")
        return seeded, "seed", False, "using the seeded value from the environment"
    value, why = refresh(policy, seeded, grant=grant, mask=mask, now=now)
    if value:
        return value, "refresh", True, why
    token["_refresh_failed"] = why
    if source == "refresh":
        return None, "refresh", False, f"refresh grant failed: {why}"
    log(f"  \033[2mrefresh grant unavailable ({why}) — falling back to the seeded value\033[0m")
    return None
