"""دریافت داده‌ی دستگاه (`[[ingest]]`، docs/plugins/ingest.md): نشانی عمومی `POST /ingest/` با توکن هر پایگاه.

اصل: **دستگاه هرگز SQL یا نام ستون نمی‌دهد.** توکن فقط یک (پایگاه، پلاگین، صفحه، نقطه) را باز می‌کند؛ هسته مقدارها را طبق فیلدهای
اعلام‌شده اعتبارسنجی و با INSERT پارامتری (همه یا هیچ) می‌نویسد. handler سطح ۲ (اختیاری) فقط بدنه را به ردیف تبدیل می‌کند.
- توکن: `gpi_` + ۲۵۶ بیت تصادفی؛ فقط SHA-256 ذخیره می‌شود و یک‌بار دیده می‌شود؛ در هدر `Authorization: Bearer` می‌آید (نه در URL).
- همه‌ی خطاهای احراز هویت و دسترسی یک پاسخ دارند (۴۰۴): توکن نامعتبر، ابطال‌شده، پلاگین خاموش یا بی‌مجوز یکی دیده می‌شوند.
- سقف‌ها: حجم بدنه، ردیف در درخواست، درخواست در دقیقه برای هر توکن، تلاش ناموفق در دقیقه برای هر نشانی، سقف ماهانه‌ی مجوز.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass

from django.core.cache import cache
from django.utils import timezone

from . import entitlements, metering, pagekit, tables, workspace

PREFIX = "gpi_"
MAX_BODY = 256 * 1024
MAX_ACTIVE_TOKENS = 5
FAIL_PER_MIN = 30
TOUCH_EVERY = 60  # ثانیه؛ last_used_at را پرتکرار ننویس
METRIC = "ingest_rows"


class IngestError(Exception):
    """خطای قابل‌گزارش به دستگاه: status و پیام کوتاه (بدون جزئیات داخلی)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------- مدیریت توکن
def create_token(ws, plugin: str, page: str, key: str, user, label: str = "") -> tuple[object, str]:
    """(ردیف، توکن خام). توکن خام دیگر قابل بازیابی نیست."""
    from .models import IngestToken

    active = IngestToken.objects.filter(workspace_id=ws.pk, plugin_id=plugin, page=page, key=key, revoked_at__isnull=True).count()
    if active >= MAX_ACTIVE_TOKENS:
        raise IngestError(400, f"حداکثر {MAX_ACTIVE_TOKENS} توکن فعال برای هر نقطه؛ اول یکی را باطل کنید.")
    raw = PREFIX + secrets.token_urlsafe(32)
    row = IngestToken.objects.create(plugin_id=plugin, page=page, key=key, workspace_id=ws.pk, prefix=raw[:8], token_hash=_hash(raw),
                                     label=(label or "").strip()[:60], created_by=user if getattr(user, "is_authenticated", False) else None)
    return row, raw


def revoke_token(ws, token_id) -> bool:
    from .models import IngestToken

    return bool(IngestToken.objects.filter(pk=token_id, workspace_id=ws.pk, revoked_at__isnull=True).update(revoked_at=timezone.now()))


def tokens_for(ws, plugin: str, page: str, key: str):
    from .models import IngestToken

    return list(IngestToken.objects.filter(workspace_id=ws.pk, plugin_id=plugin, page=page, key=key, revoked_at__isnull=True))


# ---------------------------------------------------------------------- دریافت
@dataclass
class Context:
    token: object
    ws: object
    spec: object
    page: object


def _client_key(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (xff.split(",")[-1].strip() or request.META.get("REMOTE_ADDR", "")) or "?"  # آخرین عنصر را پروکسیِ خودمان اضافه کرده


def _minute() -> int:
    return int(time.time() // 60)


def _bump(key: str, ttl: int = 120) -> int:
    try:
        return cache.incr(key)
    except ValueError:
        cache.add(key, 0, ttl)
        try:
            return cache.incr(key)
        except ValueError:
            return 1


def authenticate(request) -> Context:
    """توکن ← زمینه‌ی کار؛ IngestError(404) برای هر شکست (یکسان)، ۴۲۹ برای تلاش ناموفق بیش از حد."""
    from .models import IngestToken

    bucket = f"ingf:{_client_key(request)}:{_minute()}"
    if (cache.get(bucket) or 0) >= FAIL_PER_MIN:
        raise IngestError(429, "تلاش بیش از حد.")
    auth = request.headers.get("Authorization", "")
    raw = auth[7:].strip() if auth[:7].lower() == "bearer " else ""

    def fail():
        _bump(bucket)
        return IngestError(404, "یافت نشد.")

    if not raw.startswith(PREFIX) or len(raw) > 80:
        raise fail()
    tok = IngestToken.objects.filter(token_hash=_hash(raw), revoked_at__isnull=True).first()
    if tok is None:
        raise fail()
    page = pagekit.get(tok.plugin_id, tok.page)
    spec = pagekit.get_ingest(page, tok.key) if page else None
    ws = workspace.peek(tok.workspace_id)
    if spec is None or ws is None or not getattr(ws, "is_live", False) or not entitlements.allowed(tok.plugin_id, ws=ws):
        raise fail()
    return Context(tok, ws, spec, page)


def _rows_from_body(ctx: Context, body: bytes, content_type: str) -> list:
    spec = ctx.spec
    if spec.handler:
        from .runner import client

        try:
            out = client.execute(ctx.token.plugin_id, spec.handler, {"content_type": (content_type or "")[:80], "size": len(body)},
                                 lambda q, a: pagekit.read_select(ctx.ws, q, a), ctx.ws.pk, file=body, io=True)
        except client.RunnerError as exc:
            raise IngestError(422, str(exc)) from exc
        rows = out.get("rows") if isinstance(out, dict) else None
        if not isinstance(rows, list):
            raise IngestError(422, "handler باید {rows: [{...}]} برگرداند.")
        return rows
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise IngestError(415, "بدنه باید JSON باشد.") from None
    return data if isinstance(data, list) else [data]


def receive(request) -> dict:
    """یک درخواست دریافت: احراز هویت، سقف‌ها، تبدیل، اعتبارسنجی، نوشتن (همه یا هیچ). {"inserted": n} یا IngestError."""
    ctx = authenticate(request)
    tok, spec, ws = ctx.token, ctx.spec, ctx.ws
    if (cache.get(f"ing:{tok.pk}:{_minute()}") or 0) >= spec.rate:
        raise IngestError(429, "سقف درخواست در دقیقه پر است.")
    _bump(f"ing:{tok.pk}:{_minute()}")
    within, _now, _cap = metering.check(tok.plugin_id, METRIC, ws=ws)
    if not within:
        raise IngestError(429, "سقف ماهانه پر است.")
    length = request.META.get("CONTENT_LENGTH")
    if length and length.isdigit() and int(length) > MAX_BODY:
        raise IngestError(413, "بدنه بزرگ است.")
    body = request.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise IngestError(413, "بدنه بزرگ است.")
    if not body.strip():
        raise IngestError(400, "بدنه خالی است.")
    rows = _rows_from_body(ctx, body, request.content_type or "")
    if not rows:
        raise IngestError(400, "ردیفی نیست.")
    if len(rows) > spec.max_rows:
        raise IngestError(413, f"حداکثر {spec.max_rows} ردیف در هر درخواست.")
    values, errors = [], []
    for i, r in enumerate(rows, 1):
        try:
            values.append(pagekit.read_ingest_row(spec, r))
        except ValueError as exc:
            errors.append(f"ردیف {i}: {exc}")
            if len(errors) >= 3:
                break
    if errors:
        raise IngestError(422, "؛ ".join(errors))
    try:
        if ctx.page.tables:
            tables.ensure(ws, tok.plugin_id, ctx.page.tables)
        pagekit.insert_rows(ws, spec, values)
    except tables.TableError as exc:
        workspace.log_event("plugin_ingest", f"{tok.plugin_id}/{tok.page}/{tok.key}: {exc}", database=ws, success=False)
        raise IngestError(503, "نقطه‌ی دریافت آماده نیست.") from exc
    except pagekit.SpecError as exc:
        workspace.log_event("plugin_ingest", f"{tok.plugin_id}/{tok.page}/{tok.key}: {exc}", database=ws, success=False)
        raise IngestError(503, "نقطه‌ی دریافت درست پیکربندی نشده است.") from exc
    except Exception as exc:  # noqa: BLE001  خطای پایگاه داده (قید، نوع، سهمیه): پیام کوتاه، جزئیات در گزارش
        msg = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        workspace.log_event("plugin_ingest", f"{tok.plugin_id}/{tok.page}/{tok.key}: {msg}", database=ws, success=False)
        raise IngestError(422, "پایگاه داده ردیف‌ها را نپذیرفت.") from exc
    metering.record(tok.plugin_id, METRIC, len(values), ws=ws)
    if cache.add(f"ingt:{tok.pk}", 1, TOUCH_EVERY):
        type(tok).objects.filter(pk=tok.pk).update(last_used_at=timezone.now())
    return {"inserted": len(values)}
