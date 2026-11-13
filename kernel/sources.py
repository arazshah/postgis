"""ورود دوره‌ای از API بیرونی (`[[sources]]`، ADR-0009 مرحله‌ی ۲، docs/plugins/sources.md).

کد پلاگین شبکه ندارد؛ **هسته** واکشی می‌کند و فقط با INSERT پارامتری (همه یا هیچ) می‌نویسد.
امنیت واکشی (نقطه‌ی حساس):
- فقط https:443 و میزبانی که **مدیر در پنل تأیید کرده** (فهرست سفید دقیق) و سوئیچ «منابع بیرونی» روشن باشد.
- نام میزبان پیش از اتصال resolve می‌شود؛ هر نشانی غیرعمومی (خصوصی، loopback، link-local، متادیتای ابر) رد می‌شود و
  اتصال به **همان IP بررسی‌شده** برقرار می‌شود (ضد DNS-rebinding)؛ گواهی TLS راستی‌آزمایی می‌شود.
- redirect دنبال نمی‌شود؛ سقف حجم پاسخ و مهلت؛ متن پاسخ بیرونی هرگز به کاربر نشان داده نمی‌شود (پیام خطا ثابت و کوتاه).
- کلید API هر پایگاه رمزنگاری‌شده است و فقط داخل همین ماژول به درخواست می‌رسد.
- پس از چند خطای پیاپی منبع خاموش و مالک مطلع می‌شود؛ بین خطاها backoff نمایی است.
"""
from __future__ import annotations

import datetime
import http.client
import ipaddress
import json
import logging
import socket
import urllib.parse

from django.utils import timezone

from . import caps, crypto, entitlements, metering, notify, pagekit, platform, tables, workspace

log = logging.getLogger(__name__)
MAX_BYTES, TIMEOUT = 2 * 1024 * 1024, 10
MAX_ROWS = 5000
MAX_FAILS, MAX_BACKOFF_MIN, MAX_RUNS_PER_TICK = 5, 360, 20
RUN_NOW_GAP = datetime.timedelta(minutes=5)
UA = "geopaygah-sources/1"


class SourceError(Exception):
    """خطای قابل‌نمایش (پیام ثابت فارسی؛ بدون متن پاسخ بیرونی)."""


# ---------------------------------------------------------------------- میزبان مجاز
def host_allowed(host: str) -> bool:
    from .models import SourceHost

    return SourceHost.objects.filter(host=(host or "").lower()).exists()


def add_host(host: str, note: str = "", user=None):
    from .models import SourceHost

    host = (host or "").strip().lower()
    if not pagekit.valid_host(host):
        raise ValueError("نام دامنه‌ی معتبر بدهید (نشانی IP و wildcard پذیرفته نیست).")
    return SourceHost.objects.get_or_create(host=host, defaults={"note": note[:200], "added_by": user})[0]


# ---------------------------------------------------------------------- واکشی امن
def _public_ip(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise SourceError("نام میزبان پیدا نشد.") from None
    ips = []
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        if not addr.is_global or addr.is_multicast:
            raise SourceError("نشانی میزبان عمومی نیست؛ مسدود شد.")
        ips.append(str(addr))
    if not ips:
        raise SourceError("نام میزبان پیدا نشد.")
    return ips[0]


class _Pinned(http.client.HTTPSConnection):
    """اتصال TLS به IP ازپیش‌بررسی‌شده، با SNI و راستی‌آزمایی گواهی برای نام میزبان."""

    def __init__(self, host: str, ip: str):
        super().__init__(host, 443, timeout=TIMEOUT)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _fetch(host: str, target: str, headers: dict) -> bytes:
    """GET و بدنه‌ی خام (≤۲ مگابایت). جداشده تا آزمون mock کند. هر خطا = SourceError با پیام ثابت."""
    ip = _public_ip(host)
    conn = _Pinned(host, ip)
    try:
        conn.request("GET", target, headers={"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity", **headers})
        resp = conn.getresponse()
        if resp.status != 200:
            raise SourceError(f"سرویس بیرونی کد {resp.status} داد.")
        data = resp.read(MAX_BYTES + 1)
    except SourceError:
        raise
    except (OSError, http.client.HTTPException):
        raise SourceError("اتصال به سرویس بیرونی برقرار نشد.") from None
    finally:
        conn.close()
    if len(data) > MAX_BYTES:
        raise SourceError("پاسخ سرویس بیرونی بیش از حد بزرگ است.")
    return data


# ---------------------------------------------------------------------- درخواست و استخراج
def _fill(template: str, values: dict) -> str:
    return pagekit.PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]), template)


def build_request(spec, state, now) -> tuple[str, dict]:
    """(مسیر+query، هدرها). ورودی‌ها دوباره با قواعد خودشان سنجیده می‌شوند."""
    vals = _inputs(spec, state.inputs)
    today = timezone.localtime(now).date()
    since = (state.cursor[:10] if state.cursor and len(state.cursor) >= 10 else (today - datetime.timedelta(days=spec.since_days)).isoformat())
    vals.update(since=since, today=today.isoformat())
    q = {k: _fill(v, vals) for k, v in spec.query}
    headers = {}
    if spec.secret_header or spec.secret_param:
        key = crypto.decrypt(state.secret_enc) if state.secret_enc else ""
        if not key:
            raise SourceError("کلید API وارد نشده است.")
        if spec.secret_header:
            headers[spec.secret_header] = key
        else:
            q[spec.secret_param] = key
    return spec.path + "?" + urllib.parse.urlencode(q), headers


def _inputs(spec, raw: dict) -> dict:
    out = {}
    for i in spec.inputs:
        v = str((raw or {}).get(i.name, i.default) or "").strip()
        f = pagekit.Field(i.name, "number" if i.kind == "number" else i.kind, i.label, i.required, (), i.max, i.min)
        try:
            val = pagekit.convert_field(f, v)
        except ValueError as exc:
            raise SourceError(str(exc)) from None
        out[i.name] = "" if val is None else val
    return out


def _walk(data, path: str):
    for part in [p for p in path.split(".") if p]:
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


def extract(spec, data) -> list[dict]:
    """پاسخ JSON ← فهرست {ستون: مقدار خام}؛ SourceError اگر ساختار نمی‌خواند."""
    root = _walk(data, spec.rows_path) if spec.rows_path else data
    paths = dict(spec.paths)
    if spec.layout == "columns":
        if not isinstance(root, dict):
            raise SourceError("ساختار پاسخ با تعریف منبع نمی‌خواند.")
        cols = {n: _walk(root, p) for n, p in paths.items()}
        if not all(isinstance(c, list) for c in cols.values()):
            raise SourceError("ساختار پاسخ با تعریف منبع نمی‌خواند.")
        n = min(len(c) for c in cols.values())
        return [{k: c[i] for k, c in cols.items()} for i in range(min(n, MAX_ROWS))]
    if not isinstance(root, list):
        raise SourceError("ساختار پاسخ با تعریف منبع نمی‌خواند.")
    return [{n: _walk(r, p) for n, p in paths.items()} for r in root[:MAX_ROWS] if isinstance(r, dict)]


def convert(spec, raw_rows: list[dict], cursor: str) -> tuple[list[dict], int, str]:
    """(ردیف‌های معتبر و تازه، شمار نامعتبر، cursor تازه). ردیف نامعتبر رد می‌شود (داده‌ی بیرونی تحمل‌پذیر)."""
    good, bad, newest = [], 0, cursor
    for r in raw_rows:
        try:
            row = {f.name: pagekit.convert_field(f, pagekit._norm_raw(r.get(f.name))) for f in spec.fields}
        except ValueError:
            bad += 1
            continue
        if spec.cursor:
            c = str(r.get(spec.cursor) or "")
            if not c or (cursor and c <= cursor):
                continue
            newest = max(newest, c)
        good.append(row)
    return good, bad, newest[:64]


# ---------------------------------------------------------------------- اجرا
def _state(ws_pk, plugin, page, key):
    from .models import SourceState

    return SourceState.objects.get_or_create(plugin_id=plugin, page=page, key=key, workspace_id=ws_pk)[0]


def configure(ws, plugin: str, page, spec, post: dict, *, enable: bool):
    """ذخیره‌ی ورودی‌ها و کلید API (خالی = بدون تغییر)؛ ValueError با پیام فارسی."""
    st = _state(ws.pk, plugin, page.key, spec.key)
    raw = {i.name: str(post.get(f"i_{i.name}", "")).strip() for i in spec.inputs}
    try:
        _inputs(spec, raw)
    except SourceError as exc:
        raise ValueError(str(exc)) from None
    st.inputs = raw
    key = str(post.get("secret", "")).strip()
    if key:
        st.secret_enc = crypto.encrypt(key[:300])
    if enable and (spec.secret_header or spec.secret_param) and not st.secret_enc:
        raise ValueError("برای فعال‌سازی کلید API را وارد کنید.")
    st.enabled = bool(enable)
    st.fails, st.last_error = 0, ""
    st.next_run = timezone.now() if enable else None
    st.save()
    return st


def disable(ws, plugin, page_key, key) -> None:
    from .models import SourceState

    SourceState.objects.filter(plugin_id=plugin, page=page_key, key=key, workspace_id=ws.pk).update(enabled=False, next_run=None)


def _fail(st, spec, ws, now, msg: str) -> str:
    st.fails += 1
    st.last_error = msg[:200]
    delay = min(spec.every_minutes * 2 ** (st.fails - 1), MAX_BACKOFF_MIN)
    st.next_run = now + datetime.timedelta(minutes=delay)
    if st.fails >= MAX_FAILS:
        st.enabled, st.next_run = False, None
        owner = getattr(ws, "owner", None)
        if owner is not None:
            notify.deliver(owner, f"منبع «{spec.title}» خاموش شد",
                           f"{st.fails} بار پیاپی دریافت داده ناموفق بود ({msg[:80]}). پس از رفع مشکل دوباره فعالش کنید.",
                           key=f"source-off:{st.plugin_id}:{st.page}:{st.key}:{ws.pk}")
    st.save()
    return st.last_error


def run_one(st, page, spec, ws, now=None) -> str:
    """یک واکشی. برمی‌گرداند خالی (موفق) یا پیام خطا. هرگز استثنا نمی‌دهد."""
    now = now or timezone.now()
    st.last_run = now
    try:
        if not platform.sources_enabled():
            raise SourceError("واکشی منابع بیرونی از طرف مدیر خاموش است.")
        if not host_allowed(spec.host):
            raise SourceError("میزبان این منبع هنوز توسط مدیر تأیید نشده است.")
        within, _used, cap = metering.check(st.plugin_id, "source_fetches", ws=ws)
        if not within:
            raise SourceError(f"سقف ماهانه‌ی واکشی ({cap}) پر شده است.")
        target, headers = build_request(spec, st, now)
        raw = _fetch(spec.host, target, headers)
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError("پاسخ سرویس بیرونی JSON معتبر نیست.") from None
        rows, bad, newest = convert(spec, extract(spec, data), st.cursor)
        if bad and not rows:
            raise SourceError("هیچ ردیف معتبری در پاسخ نبود؛ نوع یا مسیر فیلدها را بررسی کنید.")
        if page.tables:
            tables.ensure(ws, st.plugin_id, page.tables)
        if rows:
            pagekit.insert_rows(ws, spec, rows)
        metering.record(st.plugin_id, "source_fetches", ws=ws)
        metering.record(st.plugin_id, "source_rows", len(rows), ws=ws)
    except (SourceError, pagekit.SpecError, tables.TableError) as exc:
        return _fail(st, spec, ws, now, str(exc))
    except Exception as exc:  # noqa: BLE001 - خطای پایگاه داده مشتری، سهمیه… (جزئیات فقط در لاگ)
        log.warning("source %s/%s/%s ws=%s failed: %s", st.plugin_id, st.page, st.key, ws.pk, type(exc).__name__)
        return _fail(st, spec, ws, now, "نوشتن در پایگاه داده انجام نشد (سهمیه یا ساختار جدول).")
    st.cursor, st.last_ok, st.last_rows, st.fails = newest, now, len(rows), 0
    st.last_error = f"{bad} ردیف نامعتبر نادیده گرفته شد." if bad else ""
    st.next_run = now + datetime.timedelta(minutes=spec.every_minutes)
    st.save()
    return ""


def run_now(ws, plugin, page, spec, user=None) -> str:
    st = _state(ws.pk, plugin, page.key, spec.key)
    if st.last_run and timezone.now() - st.last_run < RUN_NOW_GAP:
        return "دریافت دستی را هر ۵ دقیقه یک‌بار می‌توانید بزنید."
    if not entitlements.allowed(plugin, user=user, ws=ws) or not caps.allowed("sources", user=user, ws=ws):
        return "دسترسی به پلاگین ندارید."
    return run_one(st, page, spec, ws)


def tick(now=None) -> dict:
    from .models import SourceState

    now = now or timezone.now()
    if not platform.sources_enabled():
        return {"ran": 0, "off": True}
    ran = ok = 0
    for st in SourceState.objects.filter(enabled=True, next_run__lte=now).order_by("next_run")[:MAX_RUNS_PER_TICK]:
        page = pagekit.get(st.plugin_id, st.page)
        spec = pagekit.get_source(page, st.key) if page else None
        ws = workspace.peek(st.workspace_id)
        if spec is None or ws is None or not getattr(ws, "is_live", False) or not entitlements.is_enabled(st.plugin_id):
            st.next_run = now + datetime.timedelta(hours=6)  # پلاگین/پایگاه فعلاً در دسترس نیست
            st.save(update_fields=["next_run"])
            continue
        owner = getattr(ws, "owner", None)
        if not entitlements.allowed(st.plugin_id, user=owner, ws=ws) or not caps.allowed("sources", user=owner, ws=ws):
            st.next_run = now + datetime.timedelta(hours=6)
            st.save(update_fields=["next_run"])
            continue
        ran += 1
        ok += not run_one(st, page, spec, ws, now)
    return {"ran": ran, "ok": ok}
