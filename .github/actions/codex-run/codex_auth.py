#!/usr/bin/env python3
"""codex_auth.py — the stdlib half of the codex-run action.

Everything the runner needs to know about a Codex ChatGPT-login bundle
(`auth.json`) without ever printing a token, plus the post-run chores that are
easier in Python than in bash. No third-party imports: it runs on a bare
GitHub-hosted runner and on a Mac with the system python3.

  inspect      read the bundle from $CODEX_AUTH_JSON (or --file), mask every
               token, and write one JSON verdict to --out (stdout carries the
               `::add-mask::` commands, which must reach the runner, so the
               verdict cannot share it): is it a ChatGPT login with a refresh
               token, how old is `last_refresh`, how long does the access
               token have left, and the refresh token's fingerprint (sha256
               prefix — never the token). Exit 0 always; `ok` says.
  fingerprint  the refresh token's fingerprint of an auth.json on disk, so the
               runner can tell whether Codex rotated it during the run.
  redact       copy stdin to stdout with every token from the bundle, every
               JWT-shaped string and every common API-key shape replaced. The
               reviewer reads untrusted pull-request text; what it writes back
               is filtered before it reaches a comment.
  find-image   the PNG a `$imagegen` run produced: the exact path asked for,
               else the newest PNG in the work dir, else the newest under
               $CODEX_HOME/generated_images, newer than a start marker.
  sidecar      write <image>.prompt.json, the provenance record every
               AI-painted image in the fleet carries.

The freshness rule is the fleet's, not Codex's: the hub's weekly rotation is
the one place the bundle is refreshed (docs/OPENAI-AUTH.md). A consumer that
let Codex refresh it would rotate the fleet's one refresh token from inside a
job whose new token nobody stores, so `inspect` refuses a bundle before Codex
would refresh it on its own.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JWT_RX = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
KEY_RXS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),               # OpenAI / Anthropic keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),           # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
]
REDACTED = "[redacted]"


def in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def mask(value: str) -> None:
    """Register a value with the Actions log scrubber, one line at a time."""
    if value and in_actions():
        for line in str(value).splitlines():
            if line.strip():
                print(f"::add-mask::{line}", flush=True)


def fingerprint(token: str | None) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:12] if token else ""


def load_bundle(text: str) -> tuple[dict | None, str]:
    try:
        bundle = json.loads(text)
    except (TypeError, ValueError):
        return None, "CODEX_AUTH_JSON is not JSON (expected the auth.json `codex login` writes)"
    if not isinstance(bundle, dict):
        return None, "CODEX_AUTH_JSON is not a JSON object"
    return bundle, ""


def jwt_exp(token: str | None) -> int | None:
    """The `exp` claim of a JWT, read without verifying it (we only need the clock)."""
    if not token or token.count(".") != 2:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
        exp = claims.get("exp")
        return int(exp) if isinstance(exp, (int, float)) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def parse_ts(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # Codex writes RFC 3339 with up to nanoseconds; Python takes microseconds.
        v = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def verdict(text: str, max_age_days: float, min_ttl_minutes: float,
            now: datetime | None = None) -> dict:
    """Decide whether a consumer may use this bundle. Never raises."""
    now = now or datetime.now(timezone.utc)
    out = {"ok": False, "reason": "", "auth_mode": None, "age_days": None,
           "access_ttl_minutes": None, "refresh_fp": ""}
    if not text or not text.strip():
        out["reason"] = "no CODEX_AUTH_JSON (seed it: tools/openai-auth.sh seed --apply)"
        return out
    bundle, why = load_bundle(text)
    if bundle is None:
        out["reason"] = why
        return out
    tokens = bundle.get("tokens") if isinstance(bundle.get("tokens"), dict) else {}
    for key in ("access_token", "refresh_token", "id_token"):
        mask(tokens.get(key) or "")
    if bundle.get("OPENAI_API_KEY"):
        mask(str(bundle["OPENAI_API_KEY"]))
        out["reason"] = ("CODEX_AUTH_JSON carries an OPENAI_API_KEY: the fleet runs OpenAI on the "
                         "ChatGPT OAuth login only, never a metered key — re-seed from a ChatGPT login")
        return out
    out["auth_mode"] = bundle.get("auth_mode") or ("chatgpt" if tokens else None)
    if not tokens.get("refresh_token") or not tokens.get("access_token"):
        out["reason"] = "CODEX_AUTH_JSON has no ChatGPT tokens (an API-key login, or a truncated paste)"
        return out
    out["refresh_fp"] = fingerprint(tokens["refresh_token"])
    last = parse_ts(bundle.get("last_refresh"))
    if last is not None:
        out["age_days"] = round((now - last).total_seconds() / 86400, 2)
    exp = jwt_exp(tokens.get("access_token"))
    if exp is not None:
        out["access_ttl_minutes"] = round((exp - now.timestamp()) / 60, 1)
    if out["age_days"] is None:
        out["reason"] = "CODEX_AUTH_JSON has no readable last_refresh, so its freshness cannot be judged"
        return out
    if out["age_days"] >= max_age_days:
        out["reason"] = (f"CODEX_AUTH_JSON was last refreshed {out['age_days']} days ago (limit "
                         f"{max_age_days}): the hub's weekly re-mint (token-rotation.yml) is overdue. "
                         "Consumers never refresh it themselves, since that would rotate the fleet's "
                         "one refresh token — dispatch token-rotation with apply, or re-seed")
        return out
    ttl = out["access_ttl_minutes"]
    if ttl is not None and ttl < min_ttl_minutes:
        out["reason"] = (f"the access token in CODEX_AUTH_JSON expires in {ttl} minutes (minimum "
                         f"{min_ttl_minutes}); waiting for the hub's re-mint rather than refreshing here")
        return out
    out["ok"] = True
    out["reason"] = (f"ChatGPT login, refreshed {out['age_days']}d ago"
                     + (f", access token good for {round(ttl / 60, 1)}h" if ttl is not None else ""))
    return out


def redact(text: str, bundle_text: str = "") -> str:
    secrets: list[str] = []
    bundle, _ = load_bundle(bundle_text) if bundle_text else (None, "")
    if isinstance(bundle, dict):
        tokens = bundle.get("tokens") if isinstance(bundle.get("tokens"), dict) else {}
        secrets = [str(v) for k, v in tokens.items() if k != "account_id" and v]
        if bundle.get("OPENAI_API_KEY"):
            secrets.append(str(bundle["OPENAI_API_KEY"]))
    for s in sorted(secrets, key=len, reverse=True):
        if len(s) >= 8:
            text = text.replace(s, REDACTED)
    text = JWT_RX.sub(REDACTED, text)
    for rx in KEY_RXS:
        text = rx.sub(REDACTED, text)
    return text


def is_png(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(8) == PNG_MAGIC
    except OSError:
        return False


def find_image(want: Path, workdir: Path, codex_home: Path | None, since: float) -> Path | None:
    """The image a run produced, newest first, PNG by its magic bytes."""
    if want.is_file() and is_png(want) and want.stat().st_mtime >= since:
        return want

    def newest(paths):
        fresh = [p for p in paths if p.is_file() and p.stat().st_mtime >= since and is_png(p)]
        return max(fresh, key=lambda p: p.stat().st_mtime) if fresh else None

    hit = newest(workdir.glob("*.png"))
    if hit:
        return hit
    if codex_home and (codex_home / "generated_images").is_dir():
        return newest((codex_home / "generated_images").rglob("*.png"))
    return None


def write_sidecar(image: Path, prompt: str, model: str, driver: str, repo: str) -> Path:
    data = image.read_bytes()
    sidecar = image.with_name(image.name + ".prompt.json")
    record = {
        "source": "openai-codex (ChatGPT OAuth login, built-in $imagegen)",
        "model": model,
        "driver_model": driver,
        "prompt": prompt,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "repo": repo,
        "billing": "ChatGPT plan usage (no metered API spend)",
        "note": "AI-generated raster. The page that embeds it must caption it as such.",
    }
    sidecar.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return sidecar


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect")
    p.add_argument("--file", help="read the bundle from this file instead of $CODEX_AUTH_JSON")
    p.add_argument("--max-age-days", type=float, default=7.5)
    p.add_argument("--min-ttl-minutes", type=float, default=30)
    p.add_argument("--out", help="write the verdict here (default: stdout, outside Actions only)")

    p = sub.add_parser("fingerprint")
    p.add_argument("file")

    p = sub.add_parser("redact")
    p.add_argument("--in-place", help="redact this file in place instead of stdin → stdout")

    p = sub.add_parser("find-image")
    p.add_argument("--want", required=True)
    p.add_argument("--workdir", required=True)
    p.add_argument("--codex-home", default="")
    p.add_argument("--since", type=float, required=True, help="epoch seconds the run started")

    p = sub.add_parser("sidecar")
    p.add_argument("image")
    p.add_argument("--prompt", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--driver", default="")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))

    a = ap.parse_args(argv)
    if a.cmd == "inspect":
        text = Path(a.file).read_text(encoding="utf-8") if a.file else os.environ.get("CODEX_AUTH_JSON", "")
        result = json.dumps(verdict(text, a.max_age_days, a.min_ttl_minutes))
        if a.out:
            Path(a.out).write_text(result + "\n", encoding="utf-8")
        else:
            print(result)
        return 0
    if a.cmd == "fingerprint":
        try:
            bundle, _ = load_bundle(Path(a.file).read_text(encoding="utf-8"))
        except OSError:
            bundle = None
        tokens = (bundle or {}).get("tokens") or {}
        print(fingerprint(tokens.get("refresh_token") if isinstance(tokens, dict) else None))
        return 0
    if a.cmd == "redact":
        bundle_text = os.environ.get("CODEX_AUTH_JSON", "")
        if a.in_place:
            path = Path(a.in_place)
            if path.is_file():
                path.write_text(redact(path.read_text(encoding="utf-8"), bundle_text), encoding="utf-8")
            return 0
        sys.stdout.write(redact(sys.stdin.read(), bundle_text))
        return 0
    if a.cmd == "find-image":
        hit = find_image(Path(a.want), Path(a.workdir),
                         Path(a.codex_home) if a.codex_home else None, a.since)
        if not hit:
            return 1
        print(hit)
        return 0
    if a.cmd == "sidecar":
        print(write_sidecar(Path(a.image), a.prompt, a.model, a.driver, a.repo))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
