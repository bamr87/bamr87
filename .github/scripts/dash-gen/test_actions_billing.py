#!/usr/bin/env python3
"""
Fixture tests for the billing half of actions_analytics.py — the one number in
the Actions report that is a meter reading rather than a proxy.

    python3 .github/scripts/dash-gen/test_actions_billing.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions_analytics as aa  # noqa: E402

ITEMS = [
    # two months, two repos, a non-Actions product and a storage SKU that must be ignored
    {"date": "2026-08-01T00:00:00Z", "product": "actions", "sku": "Actions Linux", "quantity": 21323.0,
     "unitType": "Minutes", "grossAmount": 127.9, "netAmount": 0.0, "repositoryName": "lifehacker.dev"},
    {"date": "2026-08-01T00:00:00Z", "product": "actions", "sku": "Actions Linux", "quantity": 568.0,
     "unitType": "Minutes", "grossAmount": 3.4, "netAmount": 0.0, "repositoryName": "zpl-viewer"},
    {"date": "2026-08-01T00:00:00Z", "product": "actions", "sku": "Actions storage", "quantity": 2604.8,
     "unitType": "GigabyteHours", "grossAmount": 0.87, "netAmount": 0.0, "repositoryName": "it-journey"},
    {"date": "2026-08-01T00:00:00Z", "product": "copilot", "sku": "Copilot Premium Request", "quantity": 262.0,
     "unitType": "Requests", "grossAmount": 10.48, "netAmount": 0.0, "repositoryName": ""},
    {"date": "2026-09-01T00:00:00Z", "product": "actions", "sku": "Actions Linux", "quantity": 6208.0,
     "unitType": "Minutes", "grossAmount": 37.2, "netAmount": 0.0, "repositoryName": "zer0-mistakes"},
    {"date": "2026-09-01T00:00:00Z", "product": "actions", "sku": "Actions Linux", "quantity": 31.0,
     "unitType": "Minutes", "grossAmount": 0.19, "netAmount": 0.0, "repositoryName": "zpl-viewer"},
]


def test_summary_folds_only_actions_minutes_by_month_and_repo():
    s = aa.summarize_billing(ITEMS, dt.date(2026, 9, 5))
    assert s["this_month"] == "2026-09" and s["previous_month"] == "2026-08", s
    assert s["minutes_this_month"] == 6239.0, s["minutes_this_month"]
    assert s["minutes_previous_month"] == 21891.0, s["minutes_previous_month"]
    assert set(s["months"]) == {"2026-08", "2026-09"}
    assert s["months"]["2026-08"]["gross_usd"] == 131.3 and s["months"]["2026-08"]["net_usd"] == 0.0
    # storage and Copilot never enter the minutes
    filed = s["account_total_filed_under_previous_month"]
    assert "it-journey" not in filed
    assert list(filed) == ["lifehacker.dev", "zpl-viewer"]   # sorted, largest first
    assert s["days_elapsed"] == 5
    assert s["run_rate_monthly"] == round(6239.0 / 5 * aa.AVG_DAYS_PER_MONTH, 1)


def test_summary_survives_an_empty_or_odd_response():
    s = aa.summarize_billing([], dt.date(2026, 9, 5))
    assert s["minutes_this_month"] == 0.0 and s["previous_month"] is None
    assert s["minutes_previous_month"] is None and s["account_total_filed_under_this_month"] == {}
    s = aa.summarize_billing([{"product": "actions"}, {"date": "bad"}], dt.date(2026, 9, 5))
    assert s["months"] == {}


def test_the_meter_is_published_as_account_level_never_as_shares():
    """The meter files the account's whole total under one repository name —
    lifehacker.dev 43,924 of October's 44,563, bamr87 11,920 of November's
    first 11,925 — so v1's `by_repo_*` read as shares were not. The map is kept
    for audit under a name that says what it is, with the scope stated."""
    s = aa.summarize_billing(ITEMS, dt.date(2026, 9, 5))
    assert s["scope"] == "account"
    assert not any(k.startswith("by_repo") for k in s), sorted(s)
    assert s["account_total_filed_under_this_month"] == {"zer0-mistakes": 6208.0, "zpl-viewer": 31.0}
    assert "not per-repo shares" in s["filed_under_note"]
    # an errored meter says its scope too, so no reader mistakes it for a repo figure
    err = aa.collect_billing(_GH(_Requester(exc=RuntimeError("403"))))
    assert err["scope"] == "account" and "error" in err


class _Requester:
    def __init__(self, payload=None, exc=None):
        self.payload, self.exc, self.calls = payload, exc, []

    def requestJsonAndCheck(self, verb, url):
        self.calls.append((verb, url))
        if self.exc:
            raise self.exc
        return {}, self.payload


class _User:
    login = "bamr87"


class _GH:
    def __init__(self, requester):
        self.requester = requester

    def get_user(self):
        return _User()


def test_collect_asks_the_users_endpoint_once_and_never_raises():
    r = _Requester(payload={"usageItems": ITEMS})
    # pinned date: the fixture's "previous month" is 2026-08 only while today is in 2026-09
    s = aa.collect_billing(_GH(r), dt.date(2026, 9, 5))
    assert r.calls == [("GET", "/users/bamr87/settings/billing/usage")], r.calls
    assert "error" not in s and s["minutes_previous_month"] == 21891.0
    # a token without the scope (or a moved endpoint) degrades to an error field
    s = aa.collect_billing(_GH(_Requester(exc=RuntimeError("410 moved"))))
    assert s["error"].startswith("RuntimeError") and "source" in s


# --------------------------------------------------------------------------- #
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
    print("OK — actions billing tests" if not failures else f"FAIL — {failures} billing test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
