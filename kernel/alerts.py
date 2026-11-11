"""هشدار دوره‌ای با handler سطح ۲: worker هر دقیقه می‌گذرد، handler را برای پایگاه‌های دارای مجوز اجرا می‌کند و پیام می‌فرستد.

- handler مقدار `{"alerts": [{"title": ..., "body": ...}]}` برمی‌گرداند (حداکثر ۳ مورد)؛ هسته به **مالک پایگاه داده** اعلان می‌دهد.
- فقط پایگاه‌هایی که **مجوز معتبر نوع «فضای کار»** برای آن پلاگین دارند اجرا می‌شوند (فروش افزونه همین مجوز را می‌دهد)؛
  دسترسی به همه/پلن/سازمان برای هشدار خودکار عمداً شمرده نمی‌شود تا هزینه‌ی اجرا کنترل‌شده بماند.
- هر اجرا با همان پل SQL فقط‌خواندنی و همان سقف‌های سطح ۲ است؛ نتیجه‌ی یکسان تا ۲۴ ساعت دوباره فرستاده نمی‌شود؛ هر tick حداکثر ۲۰ اجرا.
- خطای یک handler جلوی بقیه را نمی‌گیرد و در وضعیت ثبت می‌شود (پیام کوتاه).
"""
from __future__ import annotations

import datetime
import hashlib
import logging
from dataclasses import dataclass

from django.utils import timezone

from . import entitlements, metering, workspace
from .plugins import registry

log = logging.getLogger(__name__)
POINT = "runner.alert"
MAX_RUNS_PER_TICK, MAX_ALERTS, RESEND_HOURS = 20, 3, 24
MIN_EVERY, MAX_EVERY = 5, 1440


@dataclass(frozen=True)
class Alert:
    plugin: str
    handler: str
    every_minutes: int


def register(plugin: str, handler: str, every_minutes: int) -> None:
    registry.add(POINT, f"{plugin}:{handler}", Alert(plugin, handler, int(every_minutes)), plugin=plugin, replace=True)


def alerts() -> list[Alert]:
    return registry.values(POINT)


def _workspace_ids(plugin: str) -> list[int]:
    """پایگاه‌های دارای مجوز معتبر نوع «فضای کار» برای پلاگین."""
    st = entitlements.state(plugin)
    if st is None:
        return []
    now = timezone.now()
    out = []
    for g in st.grants:
        if g.kind == "workspace" and g.subject.isdigit() and (g.expires_at is None or g.expires_at > now):
            out.append(int(g.subject))
    return sorted(set(out))


def _clean(items) -> list[tuple[str, str]]:
    out = []
    for a in (items if isinstance(items, list) else [])[:50]:
        if isinstance(a, dict) and str(a.get("title", "")).strip():
            out.append((str(a["title"]).strip()[:120], str(a.get("body", "")).strip()[:400]))
            if len(out) == MAX_ALERTS:
                break
    return out


def run_one(alert: Alert, ws, state, now) -> bool:
    """یک اجرا؛ True اگر پیامی فرستاده شد. هرگز استثنا نمی‌دهد."""
    from . import pagekit
    from .runner import client

    state.last_run = now
    try:
        out = client.execute(alert.plugin, alert.handler, {}, lambda q, a: pagekit.read_select(ws, q, a), ws.pk)
        found = _clean(out.get("alerts") if isinstance(out, dict) else None)
        state.last_error = ""
    except Exception as exc:  # noqa: BLE001 - runner خاموش، کد معیوب، پایگاه ناپیدا…
        state.last_error = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
        state.save()
        return False  # سلامت را client.execute (فقط برای خطای خود کد) ثبت کرده
    metering.record(alert.plugin, "alert_runs", ws=ws)
    sent = False
    if found:
        digest = hashlib.sha1(repr(found).encode()).hexdigest()  # noqa: S324 - فقط تشخیص تکرار
        fresh = state.last_sent is None or now - state.last_sent > datetime.timedelta(hours=RESEND_HOURS)
        owner = getattr(ws, "owner", None)
        if owner is not None and (digest != state.last_hash or fresh):
            for title, body in found:
                workspace.notify_user(owner, title, body or title)
            state.last_hash, state.last_sent, sent = digest, now, True
    elif state.last_hash:
        state.last_hash = ""  # وضعیت خوب شد؛ هشدار بعدی دوباره فرستاده شود
    state.save()
    return sent


def tick(now=None) -> dict:
    from .models import PluginAlertState

    now = now or timezone.now()
    ran = sent = 0
    for alert in alerts():
        if not entitlements.is_enabled(alert.plugin):
            continue
        for pk in _workspace_ids(alert.plugin):
            if ran >= MAX_RUNS_PER_TICK:
                return {"ran": ran, "sent": sent, "capped": True}
            state, _ = PluginAlertState.objects.get_or_create(plugin_id=alert.plugin, handler=alert.handler, workspace_id=pk)
            if state.last_run and now - state.last_run < datetime.timedelta(minutes=alert.every_minutes):
                continue
            ws = workspace.peek(pk)
            if ws is None or not getattr(ws, "is_live", False):
                continue
            ran += 1
            sent += bool(run_one(alert, ws, state, now))
    return {"ran": ran, "sent": sent}
