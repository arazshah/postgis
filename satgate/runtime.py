"""پیکربندی زنده‌ی دروازه: پنل مدیریت می‌فرستد (`PUT /v1/config`) و فقط در **حافظه** می‌ماند.

- هیچ کلید یا رمزی روی دیسک دروازه نوشته نمی‌شود؛ با راه‌اندازی دوباره، پنل در اولین درخواست (پاسخ ۴۰۹) دوباره می‌فرستد.
- بدون پیکربندی، دروازه با پیش‌فرض‌ها کار می‌کند (منبع‌های بدون حساب روشن، نشانی کاتالوگ‌ها از متغیر محیطی یا پیش‌فرض).
- سقف‌های سخت‌افزاری و امنیتی (مساحت، حجم، کلید مشترک) همچنان فقط روی خود دروازه‌اند؛ پنل فقط می‌تواند کمتر بخواهد.
"""
from __future__ import annotations

import ipaddress
import os
import threading
import time
from urllib.parse import urlparse

from . import protocol
from .spec import MISSIONS, PROVIDERS, Source

VERSION = 1
MAX_CRED_LEN = 600
# نشانی پیش‌فرض کاتالوگ هر تأمین‌کننده؛ متغیرهای قدیمی SATGATE_STAC_URL و SATGATE_LANDSAT_STAC_URL فقط پیش‌فرض‌اند
_ENV_URL = {"earthsearch": "SATGATE_STAC_URL", "planetary": "SATGATE_LANDSAT_STAC_URL"}


class ConfigError(ValueError):
    pass


def safe_url(url: str) -> str:
    """نشانی کاتالوگ: فقط https روی نام میزبان عمومی (نه IP، نه localhost، نه نشانی با رمز)."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or u.username or u.password or "." not in host or host.endswith(".local"):
        raise ConfigError("نشانی کاتالوگ باید https و با نام میزبان عمومی باشد.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return url
    raise ConfigError("نشانی کاتالوگ نباید IP باشد.")


def validate(doc) -> dict:
    """پیکربندی را بررسی و پاک‌سازی می‌کند؛ ConfigError با پیام فارسی."""
    if not isinstance(doc, dict) or doc.get("v") != VERSION:
        raise ConfigError("نسخه‌ی پیکربندی پشتیبانی نمی‌شود.")
    out: dict = {"v": VERSION, "providers": {}, "missions": {}}
    provs, miss = doc.get("providers") or {}, doc.get("missions") or {}
    if not isinstance(provs, dict) or not isinstance(miss, dict):
        raise ConfigError("ساختار پیکربندی نامعتبر است.")
    for key, p in provs.items():
        if key not in PROVIDERS or not isinstance(p, dict):
            raise ConfigError(f"تأمین‌کننده‌ی ناشناخته: {str(key)[:30]}")
        spec = PROVIDERS[key]
        allowed = {c[0] for c in spec.creds}
        cred = p.get("cred") or {}
        if not isinstance(cred, dict) or set(cred) - allowed or any(not isinstance(v, str) or len(v) > MAX_CRED_LEN for v in cred.values()):
            raise ConfigError(f"اعتبارنامه‌ی {spec.title} نامعتبر است.")
        out["providers"][key] = {"enabled": bool(p.get("enabled", True)), "url": safe_url(p.get("url", "")),
                                 "cred": {k: v.strip() for k, v in cred.items() if v.strip()}}
    for key, m in miss.items():
        if key not in MISSIONS or not isinstance(m, dict):
            raise ConfigError(f"ماهواره‌ی ناشناخته: {str(key)[:30]}")
        prefer = str(m.get("prefer") or "")
        if prefer and MISSIONS[key].source(prefer) is None:
            raise ConfigError(f"تأمین‌کننده‌ی ترجیحی {prefer} برای {MISSIONS[key].title} معتبر نیست.")
        try:
            km2 = max(float(m.get("max_km2") or 0), 0.0)
        except (TypeError, ValueError):
            raise ConfigError("سقف مساحت نامعتبر است.") from None
        out["missions"][key] = {"enabled": bool(m.get("enabled", True)), "prefer": prefer, "max_km2": km2}
    return out


class Runtime:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.doc: dict = {}
        self.hash = ""
        self.at = 0.0

    def apply(self, doc) -> str:
        clean = validate(doc)
        with self._lock:
            self.doc, self.hash, self.at = clean, protocol.config_hash(doc), time.time()
        return self.hash

    # ------------------------------------------------------------ تأمین‌کننده
    def _prov(self, key: str) -> dict:
        return (self.doc.get("providers") or {}).get(key) or {}

    def provider_enabled(self, key: str) -> bool:
        spec = PROVIDERS.get(key)
        if spec is None or not spec.implemented:
            return False
        p = self._prov(key)
        if not p.get("enabled", True):
            return False
        # تأمین‌کننده‌ی حساب‌دار تا اعتبارنامه نرسیده کار نمی‌کند
        return not spec.account or bool(p.get("cred"))

    def provider_url(self, key: str) -> str:
        spec = PROVIDERS[key]
        env = os.environ.get(_ENV_URL.get(key, ""), "") if key in _ENV_URL else ""
        return (self._prov(key).get("url") or env or spec.stac_url).rstrip("/")

    def cred(self, provider: str, name: str) -> str:
        return (self._prov(provider).get("cred") or {}).get(name, "")

    # ------------------------------------------------------------ ماهواره
    def _mission(self, key: str) -> dict:
        return (self.doc.get("missions") or {}).get(key) or {}

    def mission_enabled(self, key: str) -> bool:
        return key in MISSIONS and bool(self._mission(key).get("enabled", True))

    def max_km2(self, key: str) -> float:
        return float(self._mission(key).get("max_km2") or 0)

    def sources(self, key: str) -> list[Source]:
        """منبع‌های فعال ماهواره به ترتیب اولویت (ترجیح مدیر اول)."""
        m = MISSIONS.get(key)
        if m is None or not self.mission_enabled(key):
            return []
        srcs = [s for s in m.sources if self.provider_enabled(s.provider)]
        prefer = self._mission(key).get("prefer")
        return sorted(srcs, key=lambda s: s.provider != prefer) if prefer else srcs

    def public(self) -> dict:
        """وضعیت بدون اعتبارنامه برای GET /v1/config."""
        provs = {k: {"enabled": self.provider_enabled(k), "url": self.provider_url(k),
                     "cred": sorted((self._prov(k).get("cred") or {}).keys())} for k in PROVIDERS}
        return {"hash": self.hash, "at": int(self.at), "providers": provs}


RUNTIME = Runtime()
