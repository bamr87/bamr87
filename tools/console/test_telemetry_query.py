"""telemetry_query.py: one case per limit, contract cases over recorded response shapes, and no network.

    python3 tools/console/test_telemetry_query.py

Every store answers from test_telemetry_query_fixtures.json through a stand-in
for urllib.request.urlopen, and a socket guard fails any test that would open
a connection, so nothing here reaches Prometheus, Elasticsearch or Phoenix.
The console-route cases run only where FastAPI is installed (.venv-console, CI).
"""
from __future__ import annotations

import inspect
import io
import json
import os
import re
import socket
import sys
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import telemetry_query as tq  # noqa: E402

# Built here, never committed whole: a token-shaped literal in a fixture is what
# secret scanning (and the redactor under test) exists to catch.
GHP = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0" * 2
SKANT = "sk-" + "ant-api03-" + "Zx9_" * 8
EMAIL = "someone@example.com"
SID = "0b6c1f2e-1111-4a2b-9c3d-123456789abc"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
TEN_UTC = datetime(2026, 11, 15, 10, tzinfo=timezone.utc).timestamp()


def fixtures() -> dict:
    text = (HERE / "test_telemetry_query_fixtures.json").read_text()
    return json.loads(text.replace("__GHP__", GHP).replace("__SKANT__", SKANT))


FX = fixtures()


class Upstream:
    """urllib.request.urlopen's stand-in: records each request, answers with `answer(url, body)`."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, req, timeout=None, **_):
        url = req.full_url
        body = json.loads(req.data) if req.data else None
        self.calls.append({"url": url, "timeout": timeout, "body": body, "headers": dict(req.header_items())})
        doc = self.answer(url, body)
        if isinstance(doc, BaseException):
            raise doc
        return io.BytesIO(json.dumps(doc).encode())

    def query(self, n: int = -1) -> dict:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.calls[n]["url"]).query))

    def query_all(self, n: int = -1) -> list[tuple[str, str]]:
        return urllib.parse.parse_qsl(urllib.parse.urlsplit(self.calls[n]["url"]).query)


def http_error(url: str, code: int, doc: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(json.dumps(doc).encode()))


class Offline(unittest.TestCase):
    """Every case runs with the network refused and urlopen replaced."""

    def setUp(self):
        def refuse(*a, **k):
            raise AssertionError("a test opened a network connection")
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection",
                       "socket.getaddrinfo"):
            p = mock.patch(target, side_effect=refuse)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"PHOENIX_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def upstream(self, answer) -> Upstream:
        up = Upstream(answer if callable(answer) else (lambda url, body: answer))
        p = mock.patch("urllib.request.urlopen", up)
        p.start()
        self.addCleanup(p.stop)
        return up

    def refused(self, fn, *a, **kw) -> str:
        with self.assertRaises(ValueError) as cm:
            fn(*a, **kw)
        return str(cm.exception)


# ------------------------------------------------------------------ one case per limit
class Limits(Offline):
    def test_the_guard_refuses_a_socket(self):
        with self.assertRaises(AssertionError):
            socket.create_connection(("127.0.0.1", 9))

    def test_a_metric_outside_claude_code_is_refused(self):
        up = self.upstream(FX["prometheus"]["vector"])
        for q in ("up", "rate(node_cpu_seconds_total[5m])", "claude_code_session_count_total + process_open_fds",
                  "claude_codex_total", "sum by (model) (ALERTS)", "job:claude_code_cost:rate5m"):
            self.assertIn("allowlist", self.refused(tq.prom_query, q), q)
        self.assertEqual(up.calls, [], "a refused query must never reach Prometheus")
        self.assertEqual(tq.prom_query("sum by (model) (increase(claude_code_cost_usage_USD_total[1d] anchored))")
                         ["metrics"], ["claude_code_cost_usage_USD_total"])

    def test_a_name_matcher_or_bare_selector_is_refused(self):
        up = self.upstream(FX["prometheus"]["vector"])
        for q in ('{__name__=~"claude_code_.*"}', 'count({__name__!=""})', '{job="otel-collector"}',
                  'claude_code_session_count_total{__name__=~".+"}', "info(claude_code_session_count_total)",
                  'claude_code_session_count_total # and up', "vector(1)"):
            self.refused(tq.prom_query, q)
        self.assertIn("__name__", self.refused(tq.prom_query, 'claude_code_session_count_total{__name__=~".+"}'))
        # a bare matcher beside an allowed metric would still select every metric of that job
        self.assertIn("must follow", self.refused(tq.prom_query, 'claude_code_session_count_total or {job="prometheus"}'))
        self.assertEqual(up.calls, [])
        # grouping by __name__ selects nothing new: still only claude_code_* series
        self.assertEqual(tq.check_promql("count by (__name__) (claude_code_session_count_total)"),
                         ["claude_code_session_count_total"])

    def test_more_than_200_series_is_truncated_and_flagged(self):
        many = {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"session_id": f"s{i}", "user_email": EMAIL}, "value": [1, str(i)]} for i in range(250)]}}
        self.upstream(many)
        r = tq.prom_query("claude_code_session_count_total")
        self.assertEqual((len(r["series"]), r["series_total"], r["truncated"]), (200, 250, True))
        self.upstream(FX["prometheus"]["vector"])
        self.assertFalse(tq.prom_query("claude_code_token_usage_tokens_total")["truncated"])

    def test_a_window_over_30_days_is_refused(self):
        up = self.upstream(FX["prometheus"]["matrix"])
        self.assertIn("30", self.refused(tq.prom_query, "claude_code_session_count_total", start="now-31d"))
        self.assertIn("30 days", self.refused(tq.prom_query, "increase(claude_code_session_count_total[31d])"))
        self.refused(tq.prom_query, "max_over_time(claude_code_session_count_total[45d:1h])")
        self.refused(tq.logs_search, since="31d")
        self.refused(tq.traces_query, since="2000h")
        self.assertEqual(up.calls, [])
        tq.prom_query("claude_code_session_count_total", start="now-30d")                     # exactly 30 is fine
        tq.prom_query("increase(claude_code_session_count_total[30d])")
        self.assertEqual(len(up.calls), 2)

    def test_every_request_times_out_after_10_seconds(self):
        up = self.upstream(lambda url, body: FX["elasticsearch"]["search"] if "_search" in url
                           else FX["phoenix"]["spans"] if "/spans" in url
                           else FX["phoenix"]["traces"] if "/traces" in url else FX["prometheus"]["vector"])
        tq.prom_query("claude_code_session_count_total")
        tq.prom_query("claude_code_session_count_total", start="1h")
        tq.logs_search()
        tq.traces_query(trace_id=TRACE)
        tq.traces_query(session=SID)
        tq.traces_query(slowest=True)
        self.assertEqual([c["timeout"] for c in up.calls], [10] * 6)
        # and the stores stop work they would finish for nobody
        self.assertEqual([up.query(i)["timeout"] for i in (0, 1)], ["10s", "10s"])
        self.assertEqual(up.calls[2]["body"]["timeout"], "10s")

    def test_the_index_is_always_logs_fleet(self):
        up = self.upstream(FX["elasticsearch"]["search"])
        tq.logs_search(repo="bamr87/bamr87", text="error")
        self.assertEqual(urllib.parse.urlsplit(up.calls[0]["url"]).path, "/logs-fleet.*/_search")
        self.assertNotIn("index", inspect.signature(tq.logs_search).parameters, "the caller never picks the index")
        self.assertEqual(tq.logs_search()["index"], "logs-fleet.*")

    def test_more_than_100_hits_is_capped(self):
        hit = FX["elasticsearch"]["search"]["hits"]["hits"][0]
        flood = {"hits": {"total": {"value": 150, "relation": "eq"}, "hits": [hit] * 150}}
        up = self.upstream(flood)
        r = tq.logs_search(limit=500)
        self.assertEqual(up.calls[0]["body"]["size"], 100)
        self.assertEqual((r["returned"], r["total"], r["truncated"]), (100, 150, True))

    def test_secrets_and_emails_are_redacted(self):
        self.upstream(FX["elasticsearch"]["search"])
        out = json.dumps(tq.logs_search(since="2h"))
        for secret in (GHP, SKANT, EMAIL, "abcdefghijklmnop0123456789", "eyJhbGciOiJIUzI1NiJ9"):
            self.assertNotIn(secret, out)
        for mask in ("ghp_[REDACTED]", "sk-ant-[REDACTED]", "[REDACTED_EMAIL]", "Bearer [REDACTED]", "[REDACTED_JWT]"):
            self.assertIn(mask, out)
        self.upstream(FX["phoenix"]["spans"])
        self.assertNotIn(GHP, json.dumps(tq.traces_query(trace_id=TRACE)))

    def test_identity_never_comes_back(self):
        self.upstream(FX["prometheus"]["vector"])
        labels = set().union(*(s["metric"] for s in tq.prom_query("claude_code_token_usage_tokens_total")["series"]))
        self.assertFalse(labels & tq.IDENTITY_LABELS, labels)
        self.assertIn("model", labels)
        up = self.upstream(FX["elasticsearch"]["search"])
        r = tq.logs_search()
        self.assertFalse({k for h in r["hits"] for k in h} - set(tq.LOG_FIELDS) - {"index"})
        self.assertNotIn("user", json.dumps(up.calls[0]["body"]["_source"]["includes"]))
        self.assertIn("user.*", up.calls[0]["body"]["_source"]["excludes"])
        self.upstream(FX["phoenix"]["spans"])
        self.assertNotIn("8f0e7d6c-2222", json.dumps(tq.traces_query(trace_id=TRACE)))

    def test_the_phoenix_project_is_fixed_to_claude_code_otel(self):
        up = self.upstream(lambda url, body: FX["phoenix"]["traces"] if "/traces" in url else FX["phoenix"]["spans"])
        tq.traces_query(trace_id=TRACE)
        tq.traces_query(session=SID)
        tq.traces_query(slowest=True)
        tq.traces_query()
        for c in up.calls:
            self.assertTrue(urllib.parse.urlsplit(c["url"]).path.startswith("/v1/projects/claude-code-otel/"), c["url"])
        self.assertNotIn("project", inspect.signature(tq.traces_query).parameters)
        contract = (HERE.parents[1] / "_data" / "fleet.yml").read_text()
        self.assertEqual(re.search(r"^\s*phoenix_project:\s*(\S+)", contract, re.M).group(1), tq.PHOENIX_PROJECT)

    def test_more_than_50_rows_is_capped(self):
        span = FX["phoenix"]["spans"]["data"][1]
        up = self.upstream({"data": [span] * 60, "next_cursor": "x"})
        r = tq.traces_query(session=SID, limit=500)
        self.assertEqual((up.query()["limit"], r["returned"], r["more"]), ("50", 50, True))

    def test_the_phoenix_key_is_sent_and_never_echoed(self):
        key = "phx-" + "k" * 24
        up = self.upstream(lambda url, body: http_error(url, 401, FX["phoenix"]["unauthorized"]))
        with mock.patch.dict(os.environ, {"PHOENIX_API_KEY": key}):
            with self.assertRaises(tq.UpstreamError) as cm:
                tq.traces_query(slowest=True)
        self.assertEqual(up.calls[0]["headers"].get("Authorization"), f"Bearer {key}")
        self.assertNotIn(key, str(cm.exception))
        self.assertIn("PHOENIX_API_KEY", str(cm.exception))
        bare = self.upstream(FX["phoenix"]["traces"])
        tq.traces_query()
        self.assertNotIn("Authorization", bare.calls[0]["headers"], "no key, no header")


# ------------------------------------------------------------------ contract cases on the recorded shapes
class Prometheus(Offline):
    def test_instant_vector(self):
        up = self.upstream(FX["prometheus"]["vector"])
        r = tq.prom_query("claude_code_token_usage_tokens_total", end="2026-11-15T10:00:00Z")
        self.assertEqual(urllib.parse.urlsplit(up.calls[0]["url"]).path, "/api/v1/query")
        self.assertEqual(float(up.query()["time"]), TEN_UTC)
        self.assertEqual(r["result_type"], "vector")
        self.assertEqual(r["series"][0], {"metric": {"model": "claude-opus-5", "session_id": SID, "type": "cacheRead",
                                                      "app_version": "2.1.300"}, "value": [1763200000.123, "10130"]})
        self.assertEqual(r["cost_label"], "API-equivalent (estimate)")

    def test_range_query_raises_the_step_to_keep_500_points(self):
        up = self.upstream(FX["prometheus"]["matrix"])
        r = tq.prom_query("claude_code_cost_usage_USD_total", start="now-30d", step="1s")
        q = up.query()
        self.assertEqual(urllib.parse.urlsplit(up.calls[0]["url"]).path, "/api/v1/query_range")
        self.assertGreaterEqual(float(q["step"]), 30 * 86400 / 500)
        self.assertAlmostEqual(float(q["end"]) - float(q["start"]), 30 * 86400, delta=2)
        self.assertEqual(r["series"][0]["values"][-1], [1763200000, "0.1015"])
        r = tq.prom_query("claude_code_cost_usage_USD_total", start="2026-11-15T09:00:00Z",
                          end="2026-11-15T10:00:00Z", step="5m")
        self.assertEqual((float(up.query()["step"]), r["step_s"]), (300.0, 300.0))

    def test_scalar_and_a_refusal(self):
        self.upstream(FX["prometheus"]["scalar"])
        self.assertEqual(tq.prom_query("scalar(sum(claude_code_session_count_total))")["value"],
                         [1763200000.123, "2"])
        self.upstream(lambda url, body: http_error(url, 400, FX["prometheus"]["bad_data"]))
        self.assertIn("parse error", self.refused(tq.prom_query, "sum(claude_code_session_count_total))"))

    def test_promql_shapes_the_checker_accepts(self):
        for q in ("sum by (model, type) (increase(claude_code_token_usage_tokens_total[24h] anchored))",
                  'topk(5, sum without (session_id) (rate(claude_code_active_time_seconds_total{type="cli"}[5m])))',
                  "claude_code_commit_count_total offset 1h unless on (session_id) claude_code_session_count_total",
                  'label_replace(claude_code_session_count_total, "s", "$1", "session_id", "(.{8}).*")',
                  "max_over_time(sum(claude_code_session_count_total)[6h:5m]) @ end()",
                  "histogram_quantile(0.9, sum by (le) (rate(claude_code_x_bucket[1h])))",
                  "claude_code_session_count_total > bool 0"):
            self.assertTrue(tq.check_promql(q), q)

    def test_an_unreachable_prometheus_is_an_upstream_error(self):
        self.upstream(lambda url, body: urllib.error.URLError("connection refused"))
        with self.assertRaises(tq.UpstreamError) as cm:
            tq.prom_query("claude_code_session_count_total")
        self.assertIn("prometheus unreachable", str(cm.exception))


class Elasticsearch(Offline):
    def test_hits_are_flat_allowlisted_rows_newest_first(self):
        up = self.upstream(FX["elasticsearch"]["search"])
        r = tq.logs_search(since="2026-11-15T09:00:00Z", until="2026-11-15T11:00:00Z")
        body = up.calls[0]["body"]
        self.assertEqual(body["sort"][0]["@timestamp"]["order"], "desc")
        self.assertEqual(body["query"]["bool"]["filter"][0]["range"]["@timestamp"],
                         {"gte": int((TEN_UTC - 3600) * 1000), "lt": int((TEN_UTC + 3600) * 1000),
                          "format": "epoch_millis"})
        first = r["hits"][0]
        self.assertEqual((first["index"], first["event.action"], first["claude.model"], first["claude.cost_usd"]),
                         (".ds-logs-fleet.claude-default-2026.11.15-000001", "api_request", "claude-opus-5", 0.1015))
        self.assertNotIn("claude.tool_parameters", first)
        self.assertEqual(r["hits"][2]["ci.run_id"], 19400000001)
        self.assertEqual((r["returned"], r["total"], r["truncated"], r["cost_label"]),
                         (3, 3, False, "API-equivalent (estimate)"))

    def test_each_filter_becomes_one_clause(self):
        up = self.upstream(FX["elasticsearch"]["search"])
        tq.logs_search(repo="bamr87/bamr87", run="19400000001", trace=TRACE.upper(), session="0b6c1f2e",
                       event="api_request", level="ERROR", text='"push rejected" -warning')
        q = up.calls[0]["body"]["query"]["bool"]
        flt = json.dumps(q["filter"])
        for clause in ('{"term": {"fleet.repo": "bamr87/bamr87"}}', '{"term": {"ci.run_id": 19400000001}}',
                       f'{{"term": {{"trace.id": "{TRACE}"}}}}', '{"prefix": {"claude.session_id": "0b6c1f2e"}}',
                       '{"term": {"event.action": "api_request"}}', '{"term": {"log.level": "error"}}'):
            self.assertIn(clause, flt)
        sqs = q["must"][0]["simple_query_string"]
        self.assertEqual((sqs["query"], sqs["fields"], sqs["default_operator"]),
                         ('"push rejected" -warning', ["message"], "and"))
        self.assertNotIn("FUZZY", sqs["flags"])

    def test_bad_filters_are_refused_before_the_request(self):
        up = self.upstream(FX["elasticsearch"]["search"])
        for kw in ({"run": "12 OR 1"}, {"level": "loud"}, {"trace": "not-hex"}, {"session": 'a"}'},
                   {"repo": "a b"}, {"event": "Api Request"}, {"text": "x" * 201}, {"since": "yesterday"},
                   {"since": "1h", "until": "2h"}):
            self.refused(tq.logs_search, **kw)
        self.assertEqual(up.calls, [])

    def test_a_query_elasticsearch_refuses_is_the_callers_error(self):
        self.upstream(lambda url, body: http_error(url, 400, FX["elasticsearch"]["bad_query"]))
        self.assertIn("unknown token", self.refused(tq.logs_search, text="a"))


class Phoenix(Offline):
    def test_a_trace_is_its_spans_with_kind_model_tokens_latency_and_status(self):
        up = self.upstream(FX["phoenix"]["spans"])
        r = tq.traces_query(trace_id=TRACE.upper())
        self.assertEqual(urllib.parse.urlsplit(up.calls[0]["url"]).path, "/v1/projects/claude-code-otel/spans")
        self.assertIn(("trace_id", TRACE), up.query_all())
        agent, llm, tool = r["spans"]
        self.assertEqual((agent["span_kind"], agent["latency_ms"], agent["session"]), ("AGENT", 4250.0, SID))
        self.assertEqual((llm["span_kind"], llm["model"], llm["status"], llm["latency_ms"]),
                         ("LLM", "claude-opus-5", "OK", 2500.0))
        self.assertEqual(llm["tokens"], {"prompt": 19765, "completion": 4, "total": 19769, "cache_read": 10130,
                                         "cache_write": 9633})
        # nested attributes (Phoenix's other serialisation) read the same
        self.assertEqual((tool["tool"], tool["model"], tool["status"], tool["latency_ms"]),
                         ("Bash", "claude-opus-5", "ERROR", 1500.0))
        self.assertEqual((r["mode"], r["returned"], r["more"]), ("trace", 3, False))

    def test_a_session_is_an_attribute_filter_with_the_id_quoted(self):
        up = self.upstream(FX["phoenix"]["spans"])
        r = tq.traces_query(session=SID, since="7d")
        q = up.query_all()
        self.assertIn(("attribute", f'session.id:"{SID}"'), q)
        self.assertIn(("order", "desc"), q)
        self.assertEqual(r["mode"], "session")
        self.refused(tq.traces_query, session='x" OR 1')
        self.refused(tq.traces_query, trace_id="abc")

    def test_slowest_traces_sort_by_latency(self):
        up = self.upstream(FX["phoenix"]["traces"])
        r = tq.traces_query(slowest=True, limit=2)
        q = up.query()
        self.assertEqual(urllib.parse.urlsplit(up.calls[0]["url"]).path, "/v1/projects/claude-code-otel/traces")
        self.assertEqual((q["sort"], q["order"], q["limit"]), ("latency_ms", "desc", "2"))
        self.assertEqual(r["traces"][0], {"trace_id": TRACE, "start_time": "2026-11-15T10:00:00+00:00",
                                          "latency_ms": 90000.0,
                                          "tokens": {"prompt": 39530, "completion": 812, "total": 40342}})
        self.assertEqual((r["mode"], r["more"]), ("slowest", True))
        tq.traces_query()
        self.assertEqual(up.query()["sort"], "start_time")


# ------------------------------------------------------------------ the console routes (FastAPI only)
class Routes(Offline):
    def setUp(self):
        super().setUp()
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi not installed (use .venv-console)")
        import app as console_app
        tok = mock.patch.dict(os.environ, {"DASH_CONSOLE_TOKEN": ""})
        tok.start()
        self.addCleanup(tok.stop)
        self.client = TestClient(console_app.app, base_url="http://127.0.0.1:4001")

    def test_prom_route(self):
        self.upstream(FX["prometheus"]["vector"])
        r = self.client.get("/api/telemetry/prom", params={"query": "claude_code_token_usage_tokens_total"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["series_total"], 2)
        r = self.client.get("/api/telemetry/prom", params={"query": "up"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("allowlist", r.json()["detail"])
        self.assertEqual(self.client.get("/api/telemetry/prom", params={"query": "x" * 2001}).status_code, 422)

    def test_logs_route(self):
        self.upstream(FX["elasticsearch"]["search"])
        r = self.client.get("/api/telemetry/logs", params={"level": "error", "limit": 5})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(GHP, r.text)
        self.assertEqual(self.client.get("/api/telemetry/logs", params={"limit": 101}).status_code, 422)

    def test_traces_route_and_an_unreachable_store(self):
        self.upstream(FX["phoenix"]["traces"])
        r = self.client.get("/api/telemetry/traces", params={"slowest": "true", "limit": 3})
        self.assertEqual((r.status_code, r.json()["mode"]), (200, "slowest"))
        self.assertEqual(self.client.get("/api/telemetry/traces", params={"limit": 51}).status_code, 422)
        self.upstream(lambda url, body: urllib.error.URLError("connection refused"))
        r = self.client.get("/api/telemetry/traces")
        self.assertEqual(r.status_code, 502)
        self.assertIn("phoenix unreachable", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
