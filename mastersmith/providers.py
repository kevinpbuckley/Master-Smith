"""What the two provider accounts have left. fal.ai and OpenRouter both answer a balance from the API key, so the
chat can show real money instead of the local ledger, the director can quote against it, and a build is refused
before it starts when either account cannot cover the worst case (a job that dies half-way through Blender wastes
the picture and the seed already paid for). Cached for a minute; a failed read is reported, never fatal."""
import os
import threading
import time

import requests

FAL_BALANCE = "https://rest.alpha.fal.ai/billing/user_balance"
OPENROUTER_CREDITS = "https://openrouter.ai/api/v1/credits"
OPENROUTER_KEY = "https://openrouter.ai/api/v1/auth/key"
TTL = 60.0
TIMEOUT = 10

_lock = threading.Lock()
_cache = {"at": 0.0, "data": None}


def _fal(key):
    r = requests.get(FAL_BALANCE, headers={"Authorization": "Key " + key}, timeout=TIMEOUT)
    r.raise_for_status()
    return {"usd": round(float(r.text.strip().strip('"')), 4)}


def _openrouter(key):
    h = {"Authorization": "Bearer " + key}
    r = requests.get(OPENROUTER_CREDITS, headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json().get("data") or {}
    out = {"usd": round(float(d.get("total_credits") or 0) - float(d.get("total_usage") or 0), 4),
           "bought_usd": round(float(d.get("total_credits") or 0), 2)}
    try:
        k = requests.get(OPENROUTER_KEY, headers=h, timeout=TIMEOUT).json().get("data") or {}
        out.update({"key_usage_today_usd": round(float(k.get("usage_daily") or 0), 4),
                    "key_usage_week_usd": round(float(k.get("usage_weekly") or 0), 4),
                    "key_usage_month_usd": round(float(k.get("usage_monthly") or 0), 4)})
        if k.get("limit") is not None:
            out["key_limit_usd"] = float(k["limit"])
            out["key_limit_remaining_usd"] = float(k.get("limit_remaining") or 0)
    except Exception:  # noqa: BLE001 - the key report is a bonus
        pass
    return out


def balances(force=False):
    """{"fal": {"usd", ...} | None, "openrouter": {...} | None, "errors": {name: text}, "checked": epoch seconds}"""
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["at"] < TTL:
            return _cache["data"]
        data = {"fal": None, "openrouter": None, "errors": {}, "checked": time.time()}
        for name, fn, env in (("fal", _fal, "FAL_KEY"), ("openrouter", _openrouter, "OPENROUTER_API_KEY")):
            key = os.environ.get(env, "")
            if not key:
                data["errors"][name] = "%s is not set" % env
                continue
            try:
                data[name] = fn(key)
            except Exception as exc:  # noqa: BLE001
                data["errors"][name] = str(exc)[:160]
        _cache.update(at=time.time(), data=data)
        return data


def short(data=None):
    """One line for a log or a reply: 'fal $135.59, OpenRouter $157.74'."""
    data = data or balances()
    bits = []
    for name, label in (("fal", "fal"), ("openrouter", "OpenRouter")):
        v = data.get(name)
        bits.append("%s $%.2f" % (label, v["usd"]) if v else "%s unknown" % label)
    return ", ".join(bits)


class ProviderBalanceLow(Exception):
    def __init__(self, needed_usd, data):
        self.needed_usd, self.data = needed_usd, data
        super().__init__("needs about $%.2f worst case; %s" % (needed_usd, short(data)))


def check_affordable(needed_usd, data=None):
    """Raise ProviderBalanceLow when a KNOWN balance is below the worst case. Unknown balances never block:
    a provider outage must not stop a build the money would cover."""
    data = data or balances()
    for name in ("fal", "openrouter"):
        v = data.get(name)
        if v and v["usd"] < needed_usd:
            raise ProviderBalanceLow(needed_usd, data)
    return data
