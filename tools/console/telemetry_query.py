"""Read-only query tools over the fleet's three telemetry planes (bamr87/bamr87#447).

claude_telemetry.py answers one fixed question (the /live section). These answer
the caller's own question, inside hard limits, so an agent can audit raw
telemetry without Grafana, Kibana or Phoenix:

  prom_query    PromQL against Prometheus /api/v1/query | /api/v1/query_range
  logs_search   filters + simple_query_string against Elasticsearch logs-fleet.*
  traces_query  spans or traces of the Phoenix project claude-code-otel

The limits (each one held by test_telemetry_query.py):
  * every metric selector names a claude_code_* metric. A __name__ matcher, a
    bare {...} selector, an unknown function and info() (which joins
    target_info) are refused before any request is sent;
  * a window is at most 30 days: a range query's start..end, every [range] and
    subquery inside the PromQL, and a log search's since..until;
  * at most 200 series (then truncated: true), 100 log hits, 50 spans or traces;
  * every HTTP call times out after 10 s;
  * the index is always logs-fleet.* and the Phoenix project always
    claude-code-otel: neither is a parameter;
  * an identity label (email, account, organisation and user ids, the OS user)
    cannot be named anywhere in a query, so its value cannot be matched,
    grouped on or copied into another label (label_replace, label_join);
    identity labels and log fields are dropped from every answer, and every
    returned string passes redact() for secret-shaped values and email
    addresses. redact() reads at most MAX_FIELD_CHARS + 4 KiB of a string, so
    its cost does not grow with the length of a log line.

Endpoints are claude_telemetry's (PROMETHEUS_URL, ELASTICSEARCH_URL) and
core.py's Phoenix (PHOENIX_COLLECTOR_ENDPOINT). PHOENIX_API_KEY is sent as a
bearer token when it is set and is never returned or echoed in an error. Cost
values are Claude Code's own list-price figures: "API-equivalent (estimate)".
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import claude_telemetry as ct

COST_LABEL = ct.COST_LABEL
TIMEOUT_S = 10
MAX_WINDOW_S = 30 * 86400
MAX_SERIES = 200
MAX_POINTS = 500          # per series in a range query: the step is raised to fit
MAX_HITS = 100
MAX_SPANS = 50
MAX_QUERY_CHARS = 2000
MAX_TEXT_CHARS = 200
MAX_FIELD_CHARS = 2000    # one returned string (a log line, a status message)
LOG_INDEX = "logs-fleet.*"
PHOENIX_PROJECT = "claude-code-otel"

# Prometheus' copy of Claude Code's identity attributes (dots became underscores),
# plus the OS account the process ran as.
IDENTITY_LABELS = frozenset({
    "user_email", "user_id", "user_account_id", "user_account_uuid", "organization_id", "process_owner",
    "user.email", "user.id", "user.account_id", "user.account_uuid", "organization.id",
})

# What a log hit may carry back. Everything else (user.*, claude.user_*, host
# facts, the tool parameters) stays in Elasticsearch.
LOG_FIELDS = (
    "@timestamp", "message", "log.level", "event.action", "event.dataset", "event.module",
    "fleet.repo", "fleet.project", "service.name", "trace.id", "span.id",
    "ci.run_id", "ci.run_attempt", "ci.workflow", "ci.job", "ci.step", "ci.conclusion",
    "llm.model", "llm.cost_usd", "llm.turns", "llm.session_id", "claude.session_id",
) + tuple(f"claude.{f}" for f in ct.EVENT_FIELDS)
LOG_EXCLUDES = ("user.*", "claude.user_*", "claude.organization_*", "claude.process_owner")
LEVELS = ("trace", "debug", "info", "warn", "error", "fatal", "critical")


class UpstreamError(RuntimeError):
    """The telemetry store did not answer usefully: down, timed out, refused auth, or not JSON."""


# --------------------------------------------------------------------------- redaction
# Every pattern is linear in the length it reads: a repetition that must be
# followed by something it cannot itself match (the JWT header before its dot,
# an email's local part before its @) is bounded, so a long run of such
# characters is not rescanned from every position in it.
_REDACTIONS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]+"), "github_pat_[REDACTED]"),
    (re.compile(r"\b(gh[pousr])_[A-Za-z0-9]{20,}"), r"\1_[REDACTED]"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{20,}"), "AIza[REDACTED]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{5,1024}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"), "[REDACTED_JWT]"),
    (re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){0,8}\.[A-Za-z]{2,63}"),
     "[REDACTED_EMAIL]"),
)
# How far past the cut the patterns read, so a secret that starts in the part a
# caller sees is matched whole. Nothing beyond it is scanned.
_REDACT_LOOKAHEAD = 4096


def _redact_text(s: str) -> str:
    """`s` up to MAX_FIELD_CHARS with every secret-shaped value and email masked whole, then '…[cut]'."""
    view = s[:MAX_FIELD_CHARS + _REDACT_LOOKAHEAD]
    spans = sorted((m.start(), m.end(), m.expand(repl)) for rx, repl in _REDACTIONS for m in rx.finditer(view))
    out: list[str] = []
    pos = 0
    for start, end, mask in spans:
        if start < pos:  # overlaps a value already masked: the mask covers both
            pos = max(pos, end)
            continue
        if start >= MAX_FIELD_CHARS:
            break
        out += [view[pos:start], mask]
        pos = end
    shown = max(pos, MAX_FIELD_CHARS)
    out.append(view[pos:shown])
    text = "".join(out)
    return text + "…[cut]" if len(s) > shown else text


def redact(obj):
    """Mask secret-shaped values and email addresses in every string of `obj`, and cut long strings."""
    if isinstance(obj, str):
        return _redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- time
_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
# Bounded on purpose: CodeQL reported the unbounded (\d+unit)+ form, and the
# unanchored findall over it, as polynomial ReDoS (py/polynomial-redos). No part
# of a real duration needs more than 10 digits, nor a duration more than 8 parts.
_DURATION_PART = r"\d{1,10}(?:ms|[smhdwy])"
_DURATION = re.compile(rf"(?:{_DURATION_PART}){{1,8}}")
_DURATION_PARTS = re.compile(r"(\d{1,10})(ms|[smhdwy])")


def duration_s(text: str) -> float:
    """'90s', '1h30m', '7d' or plain seconds ('300') -> seconds."""
    s = str(text).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    if not _DURATION.fullmatch(s):
        raise ValueError(f"not a duration: {text!r} (use 90s, 15m, 1h30m, 7d)")
    return sum(int(n) * _UNITS[u] for n, u in _DURATION_PARTS.findall(s))


def timestamp(value: str | float | None, now: float) -> float | None:
    """'now', 'now-6h', '6h' (= now-6h), unix seconds or ISO 8601 -> unix seconds."""
    if value is None or value == "":
        return None
    s = str(value).strip()
    if s == "now":
        return now
    if s.startswith("now-"):
        return now - duration_s(s[4:])
    if re.fullmatch(r"\d{9,}(?:\.\d+)?", s):
        return float(s)
    if _DURATION.fullmatch(s):
        return now - duration_s(s)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"not a time: {value!r} (use now, now-6h, 6h, unix seconds or ISO 8601)") from None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def window(since, until, now: float, default_since: str) -> tuple[float, float]:
    start = timestamp(since if since not in (None, "") else default_since, now)
    end = timestamp(until, now) or now
    if end <= start:
        raise ValueError("the window is empty: since/start must be before until/end")
    if end - start > MAX_WINDOW_S:
        raise ValueError(f"the window is {round((end - start) / 86400, 1)} days; the limit is 30")
    return start, end


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- HTTP
def _http_json(source: str, url: str, body: dict | None = None, headers: dict | None = None):
    hdrs = {"Accept": "application/json", **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        finally:
            e.close()
        if not isinstance(detail, dict):
            detail = {}
        reason = detail.get("error") or detail.get("detail") or e.reason
        if isinstance(reason, dict):  # Elasticsearch: {"error": {"type", "reason", ...}}
            reason = reason.get("reason") or reason.get("type")
        if e.code in (400, 422):
            raise ValueError(f"{source} refused the query: {redact(str(reason))}") from None
        hint = " — set PHOENIX_API_KEY for the console" if source == "phoenix" and e.code in (401, 403) else ""
        raise UpstreamError(f"{source} answered {e.code}: {redact(str(reason))}{hint}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpstreamError(f"{source} unreachable: {getattr(e, 'reason', e)}") from None
    except ValueError as e:  # the body was not JSON
        raise UpstreamError(f"{source} answered something other than JSON: {e}") from None


# --------------------------------------------------------------------------- PromQL
METRIC_RX = re.compile(r"^claude_code_[A-Za-z0-9_]+$")
# A number is a hex literal, a duration (1h30m) or a float (1.5, 1e3), tried in
# that order. The earlier single alternative let one digit run be split between
# a leading \d+ and a repeated (\d+unit)*, which CodeQL reported as polynomial
# ReDoS; here no unbounded digit run is followed by another that can read it.
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`)
  | (?P<num>0[xX][0-9a-fA-F]+|(?:""" + _DURATION_PART + r"""){1,8}|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_:]*)
  | (?P<op>=~|!~|!=|==|<=|>=|[-+*/%^<>=,(){}\[\]@:])
""", re.X)
# PromQL strings take Go's escapes, so "\x75ser_email" names user_email.
_ESCAPE = re.compile(r"""\\(?:([abfnrtv\\'"])|x([0-9a-fA-F]{2})|([0-7]{3})|u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|(.))""",
                     re.S)
_ESCAPED = dict(zip("abfnrtv\\'\"", "\a\b\f\n\r\t\v\\'\""))


def _unquote(tok: str) -> str:
    """The value of a PromQL string token, its escapes decoded."""
    if tok[0] == "`":
        return tok[1:-1]

    def esc(m: re.Match) -> str:
        simple, hx, octal, u4, u8, bad = m.groups()
        if simple:
            return _ESCAPED[simple]
        if bad is not None:
            raise ValueError(f"unknown escape sequence \\{bad} in {tok}")
        code = int(octal, 8) if octal else int(hx or u4 or u8, 16)
        if code > 0x10FFFF:
            raise ValueError(f"escape out of range in {tok}")
        return chr(code)

    return _ESCAPE.sub(esc, tok[1:-1])


AGGREGATORS = frozenset({"sum", "min", "max", "avg", "group", "stddev", "stdvar", "count", "count_values",
                         "bottomk", "topk", "quantile", "limitk", "limit_ratio"})
KEYWORDS = frozenset({"and", "or", "unless", "bool", "offset", "atan2", "anchored", "smoothed", "inf", "nan"})
GROUPING = frozenset({"by", "without", "on", "ignoring", "group_left", "group_right"})
# Every PromQL function that reads only the series it is given. info() is left
# out on purpose: it joins target_info, a series outside the allowlist.
FUNCTIONS = frozenset({
    "abs", "absent", "absent_over_time", "acos", "acosh", "asin", "asinh", "atan", "atanh", "avg_over_time",
    "ceil", "changes", "clamp", "clamp_max", "clamp_min", "cos", "cosh", "count_over_time", "day_of_month",
    "day_of_week", "day_of_year", "days_in_month", "deg", "delta", "deriv", "double_exponential_smoothing",
    "end", "exp", "first_over_time", "floor", "histogram_avg", "histogram_count", "histogram_fraction",
    "histogram_quantile", "histogram_stddev", "histogram_stdvar", "histogram_sum", "holt_winters", "hour",
    "idelta", "increase", "irate", "label_join", "label_replace", "last_over_time", "ln", "log10", "log2",
    "mad_over_time", "max_over_time", "min_over_time", "minute", "month", "pi", "predict_linear",
    "present_over_time", "quantile_over_time", "rad", "rate", "resets", "round", "scalar", "sgn", "sin", "sinh",
    "sort", "sort_by_label", "sort_by_label_desc", "sort_desc", "sqrt", "start", "stddev_over_time",
    "stdvar_over_time", "step", "sum_over_time", "tan", "tanh", "time", "timestamp", "ts_of_max_over_time",
    "ts_of_min_over_time", "ts_of_last_over_time", "vector", "year",
})
_MATCHER = ("ident", "op", "str")


def check_promql(query: str) -> list[str]:
    """The claude_code_* metrics `query` selects; ValueError for anything else it could select."""
    q = query or ""
    if not q.strip():
        raise ValueError("query is empty")
    if len(q) > MAX_QUERY_CHARS:
        raise ValueError(f"query is {len(q)} characters; the limit is {MAX_QUERY_CHARS}")
    toks: list[tuple[str, str]] = []
    pos = 0
    while pos < len(q):
        m = _TOKEN.match(q, pos)
        if not m:
            raise ValueError(f"unexpected {q[pos]!r} at {pos} (comments and UTF-8 names are not accepted)")
        if m.lastgroup != "ws":
            toks.append((m.lastgroup, m.group()))
        pos = m.end()

    # An identity label may not appear anywhere: not as a matcher (which can guess
    # its value a prefix at a time), in by/without/on/ignoring/group_* lists, nor
    # as a string argument (label_replace and label_join would copy its value
    # into a label the answer keeps; sort_by_label would order by it).
    for kind, val in toks:
        name = val if kind == "ident" else _unquote(val) if kind == "str" else None
        if name in IDENTITY_LABELS:
            raise ValueError(f"{name!r} is an identity label: a query may not match, group on or copy it")

    metrics: list[str] = []
    prev_metric = False
    i = 0
    while i < len(toks):
        kind, val = toks[i]
        nxt = toks[i + 1][1] if i + 1 < len(toks) else ""
        if kind == "ident":
            low = val.lower()
            if low in GROUPING:
                i += 1
                if nxt == "(":
                    i += 1
                    while i < len(toks) and toks[i][1] != ")":
                        if toks[i][0] not in ("ident", "str") and toks[i][1] != ",":
                            raise ValueError(f"{val}(...) takes label names, not {toks[i][1]!r}")
                        i += 1
                    i += 1
                prev_metric = False
                continue
            if low in KEYWORDS or low in AGGREGATORS:
                prev_metric = False
                i += 1
                continue
            if nxt == "(":
                if val not in FUNCTIONS:
                    raise ValueError(f"function {val}() is not allowed here")
                prev_metric = False
                i += 1
                continue
            if not METRIC_RX.match(val):
                raise ValueError(f"metric {val!r} is outside the allowlist: only claude_code_* metrics")
            metrics.append(val)
            prev_metric = True
            i += 1
            continue
        if val == "{":
            if not prev_metric:
                raise ValueError("a {...} selector must follow a claude_code_* metric name")
            i += 1
            while i < len(toks) and toks[i][1] != "}":
                if toks[i][1] == ",":
                    i += 1
                    continue
                trio = toks[i:i + 3]
                if len(trio) < 3 or tuple(k for k, _ in trio) != _MATCHER or trio[1][1] not in ("=", "!=", "=~", "!~"):
                    raise ValueError("label matchers must be label=\"value\" (=, !=, =~ or !~)")
                if trio[0][1] == "__name__":
                    raise ValueError("a __name__ matcher can select any metric; name the claude_code_* metric instead")
                i += 3
            if i >= len(toks):
                raise ValueError("unclosed {")
            i += 1
            prev_metric = False
            continue
        if val == "[":
            i += 1
            first = True
            while i < len(toks) and toks[i][1] != "]":
                k, v = toks[i]
                if v == ":":
                    first = False
                elif k != "num":
                    raise ValueError(f"a [range] takes durations, not {v!r}")
                elif first and duration_s(v) > MAX_WINDOW_S:
                    raise ValueError(f"range [{v}] is longer than 30 days")
                i += 1
            if i >= len(toks):
                raise ValueError("unclosed [")
            i += 1
            prev_metric = False
            continue
        prev_metric = False
        i += 1
    if not metrics:
        raise ValueError("the query selects no claude_code_* metric")
    return sorted(set(metrics))


def prom_query(query: str, start: str | None = None, end: str | None = None, step: str | None = None) -> dict:
    """PromQL over claude_code_* metrics: an instant query at `end` (default now), or a range query from
    `start` to `end` when `start` is given (window <= 30 days, at most MAX_POINTS points per series)."""
    metrics = check_promql(query)
    now = time.time()
    if start not in (None, ""):
        t0, t1 = window(start, end, now, default_since="1h")
        st = max(duration_s(step) if step else 0.0, math.ceil((t1 - t0) / MAX_POINTS), 1.0)
        path, params = "query_range", {"query": query, "start": t0, "end": t1, "step": st}
        shape = {"start": _iso(t0), "end": _iso(t1), "step_s": st}
    else:
        t1 = timestamp(end, now) or now
        path, params = "query", {"query": query, "time": t1}
        shape = {"time": _iso(t1)}
    params["timeout"] = f"{TIMEOUT_S}s"  # Prometheus stops evaluating when the client stops waiting
    doc = _http_json("prometheus", f"{ct.PROM}/api/v1/{path}?" + urllib.parse.urlencode(params))
    if doc.get("status") != "success":
        raise UpstreamError(f"prometheus: {doc.get('errorType')}: {doc.get('error')}")
    data = doc.get("data") or {}
    rtype, result = data.get("resultType"), data.get("result")
    out = {"query": query, "metrics": metrics, "result_type": rtype, **shape, "cost_label": COST_LABEL}
    if rtype in ("scalar", "string"):
        return redact({**out, "value": result, "series": [], "series_total": 0, "truncated": False})
    rows = result or []
    series = []
    for x in rows[:MAX_SERIES]:
        row = {"metric": {k: v for k, v in (x.get("metric") or {}).items() if k not in IDENTITY_LABELS}}
        for k in ("value", "values", "histogram", "histograms"):
            if k in x:
                row[k] = x[k]
        series.append(row)
    out.update(series=series, series_total=len(rows), truncated=len(rows) > MAX_SERIES)
    if doc.get("warnings"):
        out["warnings"] = doc["warnings"]
    return redact(out)


# --------------------------------------------------------------------------- logs
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}(?:/[A-Za-z0-9._-]{1,100})?")
_HEX_ID = re.compile(r"[0-9a-fA-F]{16,64}")
_SESSION = re.compile(r"[0-9a-fA-F-]{4,64}")
_EVENT = re.compile(r"[a-z0-9_.]{1,64}")


def _pick(src: dict, dotted: str):
    if dotted in src:  # a flat dotted key
        return src[dotted]
    cur = src
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def logs_search(repo: str | None = None, run: str | int | None = None, trace: str | None = None,
                session: str | None = None, event: str | None = None, level: str | None = None,
                since: str | None = None, until: str | None = None, text: str | None = None,
                limit: int = 20) -> dict:
    """Newest-first log hits from logs-fleet.* (actions, containers, Claude Code events) matching every filter
    given; `text` is a simple_query_string over `message`. At most MAX_HITS hits, allowlisted fields, redacted."""
    now = time.time()
    t0, t1 = window(since, until, now, default_since="24h")
    size = max(1, min(int(limit), MAX_HITS))
    flt: list[dict] = [{"range": {"@timestamp": {"gte": int(t0 * 1000), "lt": int(t1 * 1000),
                                                   "format": "epoch_millis"}}}]
    echo: dict = {}
    if repo:
        if not _REPO.fullmatch(repo):
            raise ValueError("repo must be owner/name or a project name")
        flt.append({"bool": {"should": [{"term": {"fleet.repo": repo}}, {"term": {"fleet.project": repo}}],
                             "minimum_should_match": 1}})
        echo["repo"] = repo
    if run not in (None, ""):
        if not re.fullmatch(r"\d{1,20}", str(run)):
            raise ValueError("run must be a GitHub Actions run id (digits)")
        flt.append({"term": {"ci.run_id": int(run)}})
        echo["run"] = int(run)
    if trace:
        if not _HEX_ID.fullmatch(trace):
            raise ValueError("trace must be a hex trace id")
        flt.append({"term": {"trace.id": trace.lower()}})
        echo["trace"] = trace.lower()
    if session:
        if not _SESSION.fullmatch(session):
            raise ValueError("session must be a session id or its hex prefix")
        flt.append({"bool": {"should": [{"prefix": {"claude.session_id": session}},
                                        {"prefix": {"llm.session_id": session}}], "minimum_should_match": 1}})
        echo["session"] = session
    if event:
        if not _EVENT.fullmatch(event):
            raise ValueError("event must be an event.action such as api_request or tool_result")
        flt.append({"term": {"event.action": event}})
        echo["event"] = event
    if level:
        lvl = level.lower()
        if lvl not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}")
        flt.append({"term": {"log.level": lvl}})
        echo["level"] = lvl
    must: list[dict] = []
    if text:
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"text is longer than {MAX_TEXT_CHARS} characters")
        must.append({"simple_query_string": {"query": text, "fields": ["message"], "default_operator": "and",
                                             "lenient": True,
                                             "flags": "AND|OR|NOT|PHRASE|PREFIX|PRECEDENCE|WHITESPACE|ESCAPE"}})
        echo["text"] = text
    body = {
        "size": size, "timeout": f"{TIMEOUT_S}s", "track_total_hits": 10000,
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        "query": {"bool": {"filter": flt, **({"must": must} if must else {})}},
        "_source": {"includes": list(LOG_FIELDS), "excludes": list(LOG_EXCLUDES)},
    }
    url = f"{ct.ES}/{LOG_INDEX}/_search?ignore_unavailable=true&allow_no_indices=true"
    doc = _http_json("elasticsearch", url, body=body)
    raw = (doc.get("hits") or {}).get("hits") or []
    hits = []
    for h in raw[:size]:
        src = h.get("_source") or {}
        row = {"index": h.get("_index")}
        for f in LOG_FIELDS:
            v = _pick(src, f)
            if v is not None:
                row[f] = v
        hits.append(row)
    total = (doc.get("hits") or {}).get("total")
    total_n = total.get("value") if isinstance(total, dict) else total
    return redact({
        "index": LOG_INDEX, "filters": echo, "since": _iso(t0), "until": _iso(t1),
        "limit": size, "returned": len(hits), "total": total_n,
        "total_relation": total.get("relation") if isinstance(total, dict) else "eq",
        "truncated": bool(total_n and total_n > len(hits)), "cost_label": COST_LABEL, "hits": hits,
    })


# --------------------------------------------------------------------------- traces
PHOENIX = (os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or "http://127.0.0.1:6006").rstrip("/")
_TRACE_ID = re.compile(r"[0-9a-fA-F]{32}")
_SESSION_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z._:-]{3,127}")


def _phoenix(path: str, params: list[tuple[str, str]]):
    headers = {}
    key = os.environ.get("PHOENIX_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = f"{PHOENIX}/v1/projects/{PHOENIX_PROJECT}/{path}?" + urllib.parse.urlencode(params)
    return _http_json("phoenix", url, headers=headers)


def _attr(attrs: dict, dotted: str):
    return _pick(attrs or {}, dotted)


def _ms(start: str | None, end: str | None) -> float | None:
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((b - a).total_seconds() * 1000, 1)


def _span_row(s: dict) -> dict:
    a = s.get("attributes") or {}
    ctx = s.get("context") or {}
    tokens = {k: _attr(a, f"llm.token_count.{p}") for k, p in (
        ("prompt", "prompt"), ("completion", "completion"), ("total", "total"),
        ("cache_read", "prompt_details.cache_read"), ("cache_write", "prompt_details.cache_write"))}
    row = {
        "name": s.get("name"), "span_kind": s.get("span_kind"), "status": s.get("status_code"),
        "status_message": s.get("status_message") or None,
        "trace_id": ctx.get("trace_id"), "span_id": ctx.get("span_id"), "parent_id": s.get("parent_id"),
        "start_time": s.get("start_time"), "latency_ms": _ms(s.get("start_time"), s.get("end_time")),
        "model": _attr(a, "llm.model_name") or _attr(a, "model"),
        "tokens": {k: v for k, v in tokens.items() if v is not None} or None,
        "tool": _attr(a, "tool.name"), "session": _attr(a, "session.id"),
    }
    return {k: v for k, v in row.items() if v is not None}


def _trace_row(t: dict) -> dict:
    return {"trace_id": t.get("trace_id"), "start_time": t.get("start_time"),
            "latency_ms": _ms(t.get("start_time"), t.get("end_time")),
            "tokens": {"prompt": t.get("token_count_prompt"), "completion": t.get("token_count_completion"),
                       "total": t.get("token_count_total")}}


def traces_query(session: str | None = None, trace_id: str | None = None, slowest: bool = False,
                 since: str | None = None, limit: int = 10) -> dict:
    """Phoenix project claude-code-otel. trace_id -> that trace's spans; session -> the session's spans
    (newest first); otherwise traces in the window, slowest first when `slowest`, else newest first."""
    n = max(1, min(int(limit), MAX_SPANS))
    now = time.time()
    out: dict = {"project": PHOENIX_PROJECT, "limit": n}
    if trace_id:
        if not _TRACE_ID.fullmatch(trace_id):
            raise ValueError("trace_id must be a 32-character hex OpenTelemetry trace id")
        params = [("limit", str(n)), ("sort", "start_time"), ("order", "asc"), ("trace_id", trace_id.lower())]
        doc = _phoenix("spans", params)
        out.update(mode="trace", trace_id=trace_id.lower())
    elif session:
        if not _SESSION_ID.fullmatch(session):
            raise ValueError("session must be a Claude Code session id")
        t0, t1 = window(since, None, now, default_since="24h")
        params = [("limit", str(n)), ("sort", "start_time"), ("order", "desc"), ("start_time", _iso(t0)),
                  ("end_time", _iso(t1)), ("attribute", "session.id:" + json.dumps(session))]
        doc = _phoenix("spans", params)
        out.update(mode="session", session=session, since=_iso(t0), until=_iso(t1))
    else:
        t0, t1 = window(since, None, now, default_since="24h")
        params = [("limit", str(n)), ("sort", "latency_ms" if slowest else "start_time"), ("order", "desc"),
                  ("start_time", _iso(t0)), ("end_time", _iso(t1))]
        doc = _phoenix("traces", params)
        rows = [_trace_row(t) for t in (doc.get("data") or [])[:n]]
        out.update(mode="slowest" if slowest else "recent", since=_iso(t0), until=_iso(t1),
                   traces=rows, returned=len(rows), more=bool(doc.get("next_cursor")))
        return redact(out)
    rows = [_span_row(s) for s in (doc.get("data") or [])[:n]]
    out.update(spans=rows, returned=len(rows), more=bool(doc.get("next_cursor")))
    return redact(out)
