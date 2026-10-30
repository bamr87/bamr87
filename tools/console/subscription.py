"""The Claude subscription as a discounted rate off API list prices.

Every dollar figure the fleet measures for Claude — the OTel metric
`claude_code.cost.usage` (Prometheus `claude_code_cost_usage_USD_total`), the
CLI's `total_cost_usd` in CI, the lake's session totals — is Claude Code's OWN
estimate: tokens priced at API list rates. It is emitted under subscription
(OAuth / Claude Max) logins too, so it is an **API-equivalent value, not a
bill**. The bill is the flat subscription, `harnesses.budget.monthly_ai_usd`
in `_data/fleet.yml`.

This module turns the two into one comparable pair for a window:

* ``api_equiv_usd``      — what the window's usage would cost at API list prices
* ``subscription_usd``   — the flat fee prorated to the same window
* ``effective_discount`` — 1 - subscription / api_equiv (how far below list you paid)
* ``rate_multiplier``    — subscription / api_equiv (effective price per $1 of list)
* ``value_multiple``     — api_equiv / subscription

The two are NEVER summed: they are two prices for the same usage. Real metered
API spend (runs authenticated with an ANTHROPIC_API_KEY) is a separate ledger
with its own optional cap; when no data records the auth method it is reported
as not tracked rather than guessed. Pure functions, stdlib only.
"""
from __future__ import annotations

import calendar
import datetime as dt

LABEL_API_EQUIV = "API-equivalent (estimate, not billed)"
LABEL_SUBSCRIPTION = "Subscription (flat, billed)"
LABEL_METERED = "Metered API spend (billed per token)"


def days_in_month(now: dt.datetime) -> int:
    return calendar.monthrange(now.year, now.month)[1]


def month_elapsed_days(now: dt.datetime) -> float:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return max((now - start).total_seconds() / 86400.0, 1 / 24)


def _num(v) -> float | None:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def window(api_equiv_usd, window_days: float, monthly_usd, now: dt.datetime, *, label: str = "") -> dict:
    """One window's pair: API-equivalent value vs the prorated flat fee."""
    api = _num(api_equiv_usd)
    monthly = _num(monthly_usd)
    dim = days_in_month(now)
    sub = round(monthly * window_days / dim, 2) if monthly is not None else None
    out = {
        "label": label,
        "window_days": round(window_days, 3),
        "api_equiv_usd": round(api, 2) if api is not None else None,
        "subscription_usd": sub,
        "effective_discount_pct": None,
        "rate_multiplier": None,
        "value_multiple": None,
        "note": None,
    }
    if api is None:
        out["note"] = "no API-equivalent data for this window"
    elif sub is None:
        out["note"] = "subscription fee unset (harnesses.budget.monthly_ai_usd)"
    elif api <= 0:
        out["note"] = "no usage in window — the flat fee bought nothing measurable here"
    else:
        out["effective_discount_pct"] = round((1 - sub / api) * 100, 1)
        out["rate_multiplier"] = round(sub / api, 4)
        out["value_multiple"] = round(api / sub, 2) if sub else None
    return out


def headroom(mtd_api_equiv_usd, now: dt.datetime, reference_usd=None) -> dict:
    """Subscription headroom. The fee is flat, so 'remaining dollars' is meaningless;
    what can run out is the plan's usage allowance, which no source here reports.
    With a configured reference (API-equivalent $/month treated as the usage
    ceiling) the pace is compared to it; without one only the pace is shown."""
    mtd = _num(mtd_api_equiv_usd)
    ref = _num(reference_usd)
    elapsed, dim = month_elapsed_days(now), days_in_month(now)
    pace = round(mtd / elapsed * dim, 2) if mtd is not None else None
    out = {
        "mtd_api_equiv_usd": round(mtd, 2) if mtd is not None else None,
        "month_elapsed_days": round(elapsed, 2),
        "projected_month_api_equiv_usd": pace,
        "reference_usd": ref,
        "pace_pct_of_reference": None,
        "plan_limit_data": False,
        "note": None,
    }
    if ref is None:
        out["note"] = ("no plan-limit data: Claude Max reports no usage allowance to the fleet; "
                       "set harnesses.budget.subscription_reference_api_equiv_usd to compare pace")
    elif pace is not None and ref > 0:
        out["pace_pct_of_reference"] = round(pace / ref * 100, 1)
    return out


def metered(metered_usd=None, cap_usd=None) -> dict:
    """Real per-token API billing — runs on an ANTHROPIC_API_KEY. Kept apart from
    the subscription; never inferred from API-equivalent estimates."""
    usd, cap = _num(metered_usd), _num(cap_usd)
    tracked = usd is not None
    return {
        "label": LABEL_METERED,
        "tracked": tracked,
        "spend_usd": round(usd, 2) if tracked else None,
        "cap_usd": cap,
        "cap_set": cap is not None,
        "note": None if tracked else
            "not tracked: no ledger records the Claude auth method (oauth vs api_key) per run",
    }


def model(budget: dict | None, now: dt.datetime, *, windows: dict | None = None,
          mtd_api_equiv_usd=None, metered_usd=None) -> dict:
    """The whole block. ``windows`` maps a key to (api_equiv_usd, window_days, label)."""
    b = budget if isinstance(budget, dict) else {}
    monthly = _num(b.get("monthly_ai_usd"))
    return {
        "labels": {"api_equiv": LABEL_API_EQUIV, "subscription": LABEL_SUBSCRIPTION,
                   "metered": LABEL_METERED},
        "subscription_monthly_usd": monthly,
        "days_in_month": days_in_month(now),
        "windows": {k: window(a, d, monthly, now, label=lbl) for k, (a, d, lbl) in (windows or {}).items()},
        "headroom": headroom(mtd_api_equiv_usd, now, b.get("subscription_reference_api_equiv_usd")),
        "metered_api": metered(metered_usd, b.get("monthly_metered_api_usd")),
        "never_summed": True,
    }
