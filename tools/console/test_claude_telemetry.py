"""claude_telemetry.py: Prometheus/ES reads shaped for the console, no identity leaks, cost labelled."""
import json, os, sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_telemetry as ct  # noqa: E402

PROM = {
    'count by (__name__)': [{"metric": {"__name__": "claude_code_session_count_total"}, "value": [0, "1"]},
                            {"metric": {"__name__": "claude_code_cost_usage_USD_total"}, "value": [0, "1"]}],
    "token_usage": [{"metric": {"type": "cacheRead", "model": "m1"}, "value": [0, "10130"]},
                    {"metric": {"type": "output", "model": "m1"}, "value": [0, "4"]}],
    "cost_usage": [{"metric": {"model": "m1"}, "value": [0, "0.1015"]}],
    "session_count": [{"metric": {}, "value": [0, "1"]}],
}
SID = "abcdef12-3456-7890-abcd-ef1234567890"
ES = {"hits": {"hits": [{"_source": {"@timestamp": "t", "event": {"action": "api_request"},
                                     "claude": {"session_id": SID, "model": "m1", "cost_usd": 0.1, "user_email": "x@y",
                                                "input_tokens": 2}}}]},
      "aggregations": {"a": {"buckets": [{"key": "api_request", "doc_count": 1}]},
                       "sessions": {"s": {"buckets": [{"key": SID, "doc_count": 1, "last": {"value_as_string": "t"},
                                                       "cost": {"value": 0.1}, "in": {"value": 2}, "out": {"value": 4},
                                                       "cr": {"value": 10130}, "cc": {"value": 9633},
                                                       "models": {"buckets": [{"key": "m1"}]}}]}}}}


def fake_prom(q):
    for k, v in PROM.items():
        if k in q:
            return v
    return []


class Telemetry(unittest.TestCase):
    def setUp(self):
        ct._cache.clear()

    def test_metrics_totals_and_cost_label(self):
        with mock.patch.object(ct, "_prom_vec", fake_prom):
            m = ct.metrics("1h")
        self.assertEqual(m["totals"]["tokens"], 10134)
        self.assertEqual(m["totals"]["sessions"], 1)
        self.assertEqual(m["cost"]["label"], "API-equivalent (estimate)")
        self.assertEqual(m["totals"]["cost_usd_api_equivalent"], 0.1015)
        self.assertEqual(m["tokens"][0]["type"], "cacheRead")

    def test_window_validated(self):
        with self.assertRaises(ValueError):
            ct.metrics("30d")

    def test_events_shape_no_identity(self):
        with mock.patch.object(ct, "_es", lambda body: ES):
            e = ct.events("24h", None, 5)
        self.assertEqual(e["counts"], {"api_request": 1})
        self.assertEqual(e["sessions"][0]["session"], SID[:8])
        self.assertEqual(e["sessions"][0]["tokens"]["cache_read"], 10130)
        self.assertNotIn("x@y", json.dumps(e))
        self.assertNotIn(SID, json.dumps(e))

    def test_session_filter_rejects_junk(self):
        with self.assertRaises(ValueError):
            ct.events("24h", "a b\"}", 5)

    def test_snapshot_degrades(self):
        def boom(*a, **k):
            raise OSError("down")
        with mock.patch.object(ct, "_prom_vec", boom), mock.patch.object(ct, "_es", boom):
            s = ct.snapshot("24h")
        self.assertIn("error", s["series"])
        self.assertIn("error", s["events"])
        self.assertIn("error", s["metrics"]["sessions"])


if __name__ == "__main__":
    unittest.main()
