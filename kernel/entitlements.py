"""موتور مجوز: «این کاربر/فضای کار می‌تواند این پلاگین را ببیند و استفاده کند؟»

- پلاگین سیستمی همیشه مجاز است و خاموش نمی‌شود.
- نبودن ردیف وضعیت = روشن و باز (رفتار همه‌ی پلاگین‌های امروز).
- خاموش = برای همه ناپدید. محدود = فقط دارندگان مجوز معتبر (همه، پلن، سازمان، کاربر، فضای کار).
- بررسی از حافظه‌ی پردازه است (بدون کوئری در هر درخواست) و هر چند ثانیه یا با تغییر مدل‌ها تازه می‌شود.
  در چند پردازه حداکثر `TTL` ثانیه طول می‌کشد تا تغییر در همه دیده شود.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.utils import timezone

from . import events
from .plugins import registry

if TYPE_CHECKING:
    from .models import Entitlement

log = logging.getLogger(__name__)
TTL = 20.0


@dataclass(frozen=True)
class Grant:
    kind: str
    subject: str
    expires_at: object
    limits: dict


@dataclass
class State:
    enabled: bool
    access: str
    grants: list[Grant] = field(default_factory=list)


_lock = threading.Lock()
_cache: dict = {"at": 0.0, "states": {}, "orgs": {}}


def invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0


def _load() -> dict:
    now = time.monotonic()
    if now - _cache["at"] < TTL and _cache["at"]:
        return _cache
    from .models import Entitlement, OrgMember, PluginState

    with _lock:
        if time.monotonic() - _cache["at"] < TTL and _cache["at"]:
            return _cache
        states = {s.plugin_id: State(s.enabled, s.access) for s in PluginState.objects.all()}
        by_id = {s.pk: s.plugin_id for s in PluginState.objects.only("pk", "plugin_id")}
        for e in Entitlement.objects.all():
            pid = by_id.get(e.state_id)
            if pid in states:
                states[pid].grants.append(Grant(e.kind, e.subject, e.expires_at, e.limits or {}))
        orgs: dict[int, set[str]] = {}
        for uid, oid in OrgMember.objects.values_list("user_id", "org_id"):
            orgs.setdefault(uid, set()).add(str(oid))
        _cache.update(at=time.monotonic(), states=states, orgs=orgs)
        _sync_packages()
    return _cache


def _sync_packages() -> None:
    """نسخه‌های فعال بسته‌ی پلاگین را در رجیستری همین پردازه به‌روز می‌کند (هم‌زمان با تازه‌سازی مجوزها)."""
    from . import pkg

    try:
        pkg.sync()
    except Exception:  # noqa: BLE001  خطای پایگاه داده (مثلاً هنگام مهاجرت) نباید درخواست را بشکند
        log.exception("plugin package sync failed")


def refresh() -> None:
    """اول هر درخواست: مجوزها و بسته‌های فعال تازه باشند (ارزان: فقط وقتی TTL گذشته)."""
    _load()


def state(plugin_id: str) -> State | None:
    return _load()["states"].get(plugin_id)


def _kind(plugin_id: str) -> str | None:
    p = registry.plugins.get(plugin_id)
    return p.kind if p else None


def _default_open(plugin_id: str) -> bool:
    """بدون ردیف وضعیت: پلاگین سطح ۳ بسته است (باید مدیر فعالش کند)؛ بقیه باز."""
    p = registry.plugins.get(plugin_id)
    return not (p and p.tier == 3)


def is_enabled(plugin_id: str) -> bool:
    if _kind(plugin_id) == "system":
        return True
    st = state(plugin_id)
    return _default_open(plugin_id) if st is None else st.enabled


def _subjects(user, ws) -> set[tuple[str, str]]:
    cache = _load()
    out = {("all", "")}
    users = []
    if user is not None and getattr(user, "is_authenticated", False):
        users.append(user.pk)
    if ws is not None:
        out.add(("workspace", str(ws.pk)))
        slug = getattr(getattr(ws, "plan", None), "slug", "")
        if slug:
            out.add(("plan", slug))
        if getattr(ws, "owner_id", None):
            users.append(ws.owner_id)
    for uid in users:
        out.add(("user", str(uid)))
        out |= {("org", o) for o in cache["orgs"].get(uid, ())}
    return out


def _valid_grants(plugin_id: str, user, ws, now=None) -> list[Grant]:
    st = state(plugin_id)
    if st is None:
        return []
    now = now or timezone.now()
    subjects = _subjects(user, ws)
    return [g for g in st.grants if (g.kind, g.subject if g.kind != "all" else "") in subjects
            and (g.expires_at is None or g.expires_at > now)]


def allowed(plugin_id: str, *, user=None, ws=None, now=None) -> bool:
    """مجاز بودن پلاگین برای کاربر و/یا فضای کار. پلاگین ناشناخته (نصب‌نشده) مجاز نیست."""
    kind = _kind(plugin_id)
    if kind is None:
        return False
    if kind == "system":
        return True
    st = state(plugin_id)
    if st is None:
        return _default_open(plugin_id)
    if not st.enabled:
        return False
    if st.access == "open":
        return True
    return bool(_valid_grants(plugin_id, user, ws, now))


def limits(plugin_id: str, *, user=None, ws=None) -> dict:
    """سقف‌های مجوزهای معتبر (در تداخل، بزرگ‌ترین مقدار عددی)."""
    out: dict = {}
    for g in _valid_grants(plugin_id, user, ws):
        for k, v in g.limits.items():
            if isinstance(v, (int, float)) and isinstance(out.get(k), (int, float)):
                out[k] = max(out[k], v)
            else:
                out.setdefault(k, v)
    return out


def grant(plugin_id: str, kind: str, subject: str = "", *, source: str = "purchase", days: int | None = None,
          limits: dict | None = None, note: str = "") -> Entitlement:
    """مجوز را می‌دهد یا تمدید می‌کند (قرارداد هسته برای صورتحساب و هر منبع دیگر).

    - پلاگین باید نصب و غیرسیستمی باشد (سیستمی مجوز نمی‌خواهد).
    - مجوز موجود با همان (دارنده، موضوع) تمدید می‌شود: انقضا از «بعد از انقضای فعلی» یا «اکنون» (هرکدام دیرتر) + days.
    - `days=None` یعنی بدون انقضا. سقف‌ها روی سقف‌های قبلی ادغام می‌شود.
    """
    import datetime

    from django.utils import timezone

    from .models import Entitlement, PluginState

    p = registry.plugins.get(plugin_id)
    if p is None or p.kind == "system":
        raise ValueError(f"پلاگین «{plugin_id}» نصب نیست یا مجوزپذیر نیست.")
    if kind not in Entitlement.Kind.values:
        raise ValueError("نوع دارنده نامعتبر است.")
    subject = "" if kind == Entitlement.Kind.ALL else str(subject)
    if kind != Entitlement.Kind.ALL and not subject:
        raise ValueError("شناسه‌ی دارنده لازم است.")
    st, _ = PluginState.objects.get_or_create(plugin_id=plugin_id)
    ent, created = Entitlement.objects.get_or_create(state=st, kind=kind, subject=subject, defaults={"source": source})
    now = timezone.now()
    if days is None:
        ent.expires_at = None
    elif created or ent.expires_at is not None:
        base = max(now, ent.expires_at) if ent.expires_at else now
        ent.expires_at = base + datetime.timedelta(days=days)
    ent.limits = {**(ent.limits or {}), **(limits or {})}
    ent.source = source
    if note:
        ent.note = note[:200]
    ent.save()
    invalidate()
    return ent


def workspace_deleted(*, ws, **_) -> None:
    from .models import Entitlement

    Entitlement.objects.filter(kind=Entitlement.Kind.WORKSPACE, subject=str(ws.pk)).delete()


events.listen(events.WORKSPACE_DELETED, "kernel.entitlements.workspace_deleted", plugin="kernel", order=10)
