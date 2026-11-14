"""منابع ماهواره در پنل: تنظیم هر تأمین‌کننده و ماهواره (kernel.conf)، ساخت پیکربندی دروازه و فرستادن آن.

- همه‌ی تنظیم‌ها از پنل مدیریت است (نه متغیر محیطی دروازه)؛ کلیدها رمزنگاری‌شده در `kernel.conf` می‌مانند.
- پیکربندی با `PUT /v1/config` به دروازه می‌رود و آنجا فقط در حافظه می‌ماند. هر کار چکیده‌ی پیکربندی را می‌برد؛
  اگر دروازه چیز دیگری داشت (مثلاً تازه بالا آمده) ۴۰۹ می‌دهد و `client` خودکار دوباره می‌فرستد.
- مقدارهای محرمانه هرگز در کش نمی‌روند: کش فقط چکیده و تنظیم‌های غیرمحرمانه را نگه می‌دارد.
"""
from __future__ import annotations

from django.core.cache import cache

from kernel import conf
from satgate import protocol, spec

PLUGIN = "satellite"
CACHE_KEY, TTL = "satsrc:v1", 60
URL_PROVIDERS = ("earthsearch", "planetary")      # نشانی کاتالوگ فقط برای این‌ها قابل تغییر است


def declare(plugin_id: str = PLUGIN) -> None:
    """گزینه‌های هر تأمین‌کننده و ماهواره را اعلام می‌کند (از plugin.py)."""
    for p in spec.PROVIDERS.values():
        conf.option(plugin_id, f"prov_{p.key}_enabled", f"{p.title}: روشن", kind="bool", default=True)
        if p.key in URL_PROVIDERS:
            conf.option(plugin_id, f"prov_{p.key}_url", f"{p.title}: نشانی کاتالوگ", kind="str", default="",
                        help=f"خالی = پیش‌فرض ({p.stac_url}). فقط https.")
        for name, label, secret in p.creds:
            conf.option(plugin_id, f"prov_{p.key}_{name}", f"{p.title}: {label}", kind="secret" if secret else "str", default="")
    for m in spec.MISSIONS.values():
        conf.option(plugin_id, f"m_{m.key}_enabled", f"{m.title}: روشن", kind="bool", default=True)
        conf.option(plugin_id, f"m_{m.key}_weight", f"{m.title}: هزینه از سهمیه", kind="int", default=m.weight, min=1, max=20)
        conf.option(plugin_id, f"m_{m.key}_max_km2", f"{m.title}: سقف مساحت (۰ = فقط سقف پلن)", kind="int", default=0, min=0, max=100000)
        if len(m.sources) > 1:
            conf.option(plugin_id, f"m_{m.key}_prefer", f"{m.title}: تأمین‌کننده‌ی اول", kind="choice", default=m.primary.provider,
                        choices=tuple((s.provider, spec.PROVIDERS[s.provider].title) for s in m.sources))


# ---------------------------------------------------------------------- ساخت پیکربندی
def build_config(values: dict | None = None) -> dict:
    """پیکربندی کامل دروازه از روی تنظیم‌های ذخیره‌شده (شامل اعتبارنامه؛ فقط برای ارسال به دروازه)."""
    v = conf.get_all(PLUGIN) if values is None else values
    doc: dict = {"v": 1, "providers": {}, "missions": {}}
    for p in spec.PROVIDERS.values():
        ent: dict = {"enabled": bool(v.get(f"prov_{p.key}_enabled", True))}
        if v.get(f"prov_{p.key}_url"):
            ent["url"] = v[f"prov_{p.key}_url"]
        cred = {name: str(v.get(f"prov_{p.key}_{name}") or "") for name, _, _ in p.creds}
        cred = {k: x for k, x in cred.items() if x}
        if cred:
            ent["cred"] = cred
        doc["providers"][p.key] = ent
    for m in spec.MISSIONS.values():
        ent = {"enabled": bool(v.get(f"m_{m.key}_enabled", True)), "max_km2": int(v.get(f"m_{m.key}_max_km2") or 0)}
        if len(m.sources) > 1:
            ent["prefer"] = v.get(f"m_{m.key}_prefer") or m.primary.provider
        doc["missions"][m.key] = ent
    return doc


def _snapshot() -> dict:
    """چکیده و تنظیم‌های غیرمحرمانه؛ ۶۰ ثانیه کش (در پروسه‌ی دیگر حداکثر همین‌قدر کهنه می‌ماند)."""
    snap = cache.get(CACHE_KEY)
    if snap is not None:
        return snap
    v = conf.get_all(PLUGIN)
    doc = build_config(v)
    snap = {"hash": protocol.config_hash(doc),
            "missions": {m.key: {"enabled": bool(v.get(f"m_{m.key}_enabled", True)), "weight": int(v.get(f"m_{m.key}_weight") or m.weight),
                                 "max_km2": int(v.get(f"m_{m.key}_max_km2") or 0)} for m in spec.MISSIONS.values()},
            "providers": {p.key: {"enabled": bool(v.get(f"prov_{p.key}_enabled", True)),
                                  "creds": sorted(n for n, _, _ in p.creds if v.get(f"prov_{p.key}_{n}"))} for p in spec.PROVIDERS.values()}}
    cache.set(CACHE_KEY, snap, TTL)
    return snap


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def config_hash() -> str:
    return _snapshot()["hash"]


def mission_enabled(key: str) -> bool:
    return bool(_snapshot()["missions"].get(key, {}).get("enabled"))


def weight(key: str) -> int:
    return max(int(_snapshot()["missions"].get(key, {}).get("weight") or 1), 1)


def max_km2(key: str) -> int:
    return int(_snapshot()["missions"].get(key, {}).get("max_km2") or 0)


def provider_state(key: str) -> dict:
    return _snapshot()["providers"].get(key, {"enabled": False, "creds": []})


# ---------------------------------------------------------------------- پلن
def plan_missions(plan) -> set[str] | None:
    """ماهواره‌های مجاز پلن؛ None = همه (خالی)."""
    raw = (getattr(plan, "sat_missions", "") or "").replace("،", ",")
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    return keys & set(spec.MISSIONS) if keys else None


def plan_allows(plan, key: str) -> bool:
    allowed = plan_missions(plan) if plan is not None else None
    return allowed is None or key in allowed


# ---------------------------------------------------------------------- ارسال به دروازه
def push() -> tuple[bool, str]:
    """پیکربندی فعلی را به دروازه می‌فرستد؛ (موفق؟، پیام فارسی)."""
    from . import client

    invalidate()
    doc = build_config()
    try:
        res = client.call("PUT", "/v1/config", doc, cfg=False)
    except client.GatewayError as exc:
        if exc.status == 404:
            return False, "دروازه نسخه‌ی قدیمی است و پیکربندی از پنل را نمی‌شناسد؛ آن را به‌روز کنید (docs/ ← satgate/README.md)."
        return False, str(exc)
    if res.get("hash") != protocol.config_hash(doc):
        return False, "دروازه چکیده‌ی دیگری برگرداند؛ نسخه‌ی پنل و دروازه یکی نیست."
    invalidate()
    return True, "پیکربندی به دروازه رسید."
