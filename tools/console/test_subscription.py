"""The Claude subscription as a discounted rate off API list prices (subscription.py)."""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subscription as sub  # noqa: E402

OCT30 = dt.datetime(2026, 10, 30, 18, 0, tzinfo=dt.timezone.utc)


class WindowTests(unittest.TestCase):
    def test_todays_24h_example(self):
        w = sub.window(92.91, 1.0, 200, OCT30)
        self.assertEqual(w["subscription_usd"], 6.45)          # 200 / 31
        self.assertEqual(w["api_equiv_usd"], 92.91)
        self.assertEqual(w["effective_discount_pct"], 93.1)
        self.assertEqual(w["value_multiple"], 14.4)
        self.assertAlmostEqual(w["rate_multiplier"], 6.45 / 92.91, places=4)

    def test_never_summed(self):
        m = sub.model({"monthly_ai_usd": 200}, OCT30, windows={"24h": (92.91, 1.0, "24h")})
        w = m["windows"]["24h"]
        self.assertTrue(m["never_summed"])
        self.assertFalse(any(isinstance(v, (int, float)) and abs(v - (w["api_equiv_usd"] + w["subscription_usd"])) < 0.01
                             for v in w.values()))

    def test_zero_usage_has_no_discount(self):
        w = sub.window(0.0, 1.0, 200, OCT30)
        self.assertIsNone(w["effective_discount_pct"])
        self.assertIn("no usage", w["note"])

    def test_missing_inputs_degrade(self):
        self.assertIn("no API-equivalent", sub.window(None, 1.0, 200, OCT30)["note"])
        self.assertIn("unset", sub.window(10, 1.0, None, OCT30)["note"])

    def test_usage_above_fee_is_negative_discount(self):
        self.assertLess(sub.window(1.0, 1.0, 200, OCT30)["effective_discount_pct"], 0)


class HeadroomTests(unittest.TestCase):
    def test_no_reference_is_honest(self):
        h = sub.headroom(1000.0, OCT30)
        self.assertFalse(h["plan_limit_data"])
        self.assertIsNone(h["pace_pct_of_reference"])
        self.assertIn("no plan-limit data", h["note"])
        self.assertAlmostEqual(h["projected_month_api_equiv_usd"], 1000 / h["month_elapsed_days"] * 31, delta=0.5)

    def test_reference_compares_pace(self):
        h = sub.headroom(1000.0, OCT30, reference_usd=2000)
        self.assertIsNotNone(h["pace_pct_of_reference"])
        self.assertIsNone(h["note"])


class MeteredTests(unittest.TestCase):
    def test_not_tracked_is_na(self):
        m = sub.metered()
        self.assertFalse(m["tracked"])
        self.assertIsNone(m["spend_usd"])
        self.assertFalse(m["cap_set"])
        self.assertIn("not tracked", m["note"])

    def test_model_reads_optional_cap_without_defaulting(self):
        m = sub.model({"monthly_ai_usd": 200}, OCT30)
        self.assertIsNone(m["metered_api"]["cap_usd"])
        self.assertIsNone(m["headroom"]["reference_usd"])
        m = sub.model({"monthly_ai_usd": 200, "monthly_metered_api_usd": 25}, OCT30)
        self.assertEqual(m["metered_api"]["cap_usd"], 25.0)


class StateTests(unittest.TestCase):
    def test_load_state_carries_subscription_block(self):
        import core
        st = core.load_state(OCT30)
        s = st["subscription"]
        self.assertEqual(s["labels"]["api_equiv"], sub.LABEL_API_EQUIV)
        self.assertIn("metered_api", s)


class LiveTests(unittest.TestCase):
    def test_claude_live_labels_estimate_and_models_24h(self):
        from unittest import mock
        import live
        vals = {"24h]": 92.91, "1h]": 0.0}
        def fake(q):
            return next((v for k, v in vals.items() if k in q and "cost" in q), 1000.0 if "cost" in q else 5.0)
        with mock.patch.object(live, "_prom", side_effect=fake), \
             mock.patch.object(live.core, "load_yaml", return_value={"harnesses": {"budget": {"monthly_ai_usd": 200}}}):
            d = live.claude_live(OCT30)
        self.assertEqual(d["cost_kind"], sub.LABEL_API_EQUIV)
        self.assertEqual(d["api_equiv_usd_24h"], 92.91)
        self.assertEqual(d["cost_usd_24h"], 92.91)              # kept for compatibility
        w = d["subscription"]["windows"]["24h"]
        self.assertEqual((w["subscription_usd"], w["effective_discount_pct"]), (6.45, 93.1))
        self.assertEqual(d["subscription"]["headroom"]["mtd_api_equiv_usd"], 1000.0)
        self.assertFalse(d["subscription"]["metered_api"]["tracked"])


if __name__ == "__main__":
    unittest.main()
