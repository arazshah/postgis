"""بسته‌ی پلاگین: قالب، امضا و خط لوله‌ی بررسی تا فعال‌سازی (docs/plugins/packages.md).

بسته یک zip کوچک است: `plugin.toml`، `pages/*.toml`، `README.md` (اختیاری) و `SIGNATURE`. تنها محتوای **اعلانی** (صفحه‌ی کیت صفحه) پذیرفته
می‌شود؛ هیچ کد پایتونی اجرا نمی‌شود. بسته بدون امضای معتبر ناشرِ مجاز (کلید عمومی در تنظیم استقرار، نه در پایگاه داده) حتی وارد
بررسی نمی‌شود. چکیده‌ی امضاشده همه‌ی فایل‌ها (مسیر و محتوا) را پوشش می‌دهد.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import re
import tomllib
import zipfile
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import alerts, handlers, pagekit
from .plugins import API_VERSION, ID_RE, registry

log = logging.getLogger(__name__)

MAX_TOTAL, MAX_FILE, MAX_FILES = 2 * 1024 * 1024, 200 * 1024, 60
NAME_RE = re.compile(r"^(plugin\.toml|SIGNATURE|README\.md|pages/[a-z][a-z0-9_]{1,30}\.toml|code/[a-z][a-z0-9_]{1,30}\.py|tests/[a-z][a-z0-9_]{1,30}\.toml)$")
VERSION_RE = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
SIG_NAME, MANIFEST_NAME = "SIGNATURE", "plugin.toml"
KINDS = ("custom", "feature")


class PackageError(Exception):
    """بسته نامعتبر است؛ پیام فارسی برای گزارش بررسی."""


# ---------------------------------------------------------------------- کلیدها و امضا
def parse_keys(raw: str) -> dict[str, Ed25519PublicKey]:
    keys = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, b64 = part.partition("=")
        try:
            keys[name.strip()] = Ed25519PublicKey.from_public_bytes(base64.b64decode(b64.strip(), validate=True))
        except Exception as exc:  # noqa: BLE001
            raise PackageError(f"کلید ناشر «{name}» در تنظیم استقرار نامعتبر است.") from exc
    return keys


def publisher_keys() -> dict[str, Ed25519PublicKey]:
    """کلیدهای ناشر: متغیر استقرار + کلیدهای فعال ثبت‌شده در پنل (هر دو؛ نام تکراری با کلید پنل بازنویسی نمی‌شود)."""
    from . import platform

    keys = parse_keys(getattr(settings, "PLUGIN_PUBLISHER_KEYS", ""))
    for name, k in parse_keys(platform.db_publisher_keys()).items():
        keys.setdefault(name, k)
    return keys


def digest(files: dict[str, bytes]) -> bytes:
    """چکیده‌ی قانونی همه‌ی فایل‌ها به‌جز SIGNATURE (مسیر و محتوا، مرتب)؛ همین چکیده امضا می‌شود."""
    lines = [f"{path}\0{hashlib.sha256(data).hexdigest()}" for path, data in sorted(files.items()) if path != SIG_NAME]
    return hashlib.sha256("\n".join(lines).encode()).digest()


def sign(files: dict[str, bytes], private_key: Ed25519PrivateKey, publisher: str) -> bytes:
    sig = private_key.sign(digest(files))
    return json.dumps({"publisher": publisher, "alg": "ed25519", "sig": base64.b64encode(sig).decode()}).encode()


PANEL = "panel"  # ناشر «ویزارد پنل» (docs/adr/0008): مهر HMAC با کلید مشتق‌شده از SECRET_KEY همین سرور، نه کلید ناشر بیرونی


def _seal_key() -> bytes:
    return hashlib.sha256(b"geopaygah-panel-seal|" + settings.SECRET_KEY.encode()).digest()


def seal(files: dict[str, bytes]) -> bytes:
    """SIGNATURE پلاگین ساخته‌ی ویزارد: HMAC روی همان چکیده‌ی قانونی. فقط سرور با SECRET_KEY می‌تواند بسازد (بسته‌ی بیرونی نمی‌تواند جعلش کند)؛
    با تعویض SECRET_KEY مهر نسخه‌های ویزارد نامعتبر می‌شود و باید دوباره منتشر شوند."""
    mac = hmac.new(_seal_key(), digest(files), hashlib.sha256).digest()
    return json.dumps({"publisher": PANEL, "alg": "hmac-sha256", "sig": base64.b64encode(mac).decode()}).encode()


def verify(files: dict[str, bytes], keys: dict[str, Ed25519PublicKey]) -> str:
    """نام ناشر را برمی‌گرداند یا PackageError."""
    if SIG_NAME not in files:
        raise PackageError("بسته امضا ندارد.")
    try:
        sig = json.loads(files[SIG_NAME])
        publisher, raw = sig["publisher"], base64.b64decode(sig["sig"], validate=True)
        alg = sig.get("alg")
        assert alg in ("ed25519", "hmac-sha256")
    except Exception as exc:  # noqa: BLE001
        raise PackageError("فایل SIGNATURE نامعتبر است.") from exc
    if alg == "hmac-sha256":
        if publisher != PANEL:
            raise PackageError("مهر HMAC فقط برای ناشر «panel» (ویزارد این سرور) معتبر است.")
        if not hmac.compare_digest(raw, hmac.new(_seal_key(), digest(files), hashlib.sha256).digest()):
            raise PackageError("مهر ویزارد با محتوای بسته نمی‌خواند (بسته تغییر کرده یا از سرور دیگری است).")
        return PANEL
    if publisher == PANEL:
        raise PackageError("ناشر «panel» فقط با مهر ویزارد معتبر است.")
    key = keys.get(publisher)
    if key is None:
        raise PackageError(f"ناشر «{publisher}» مجاز نیست (کلیدش در تنظیم استقرار نیست).")
    try:
        key.verify(raw, digest(files))
    except InvalidSignature as exc:
        raise PackageError("امضا با محتوای بسته نمی‌خواند (بسته پس از امضا تغییر کرده است).") from exc
    return publisher


# ---------------------------------------------------------------------- خواندن امن zip
def read_archive(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_TOTAL:
        raise PackageError("حجم بسته بیش از ۲ مگابایت است.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackageError("فایل zip معتبر نیست.") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise PackageError("بسته خالی است.")
    if len(infos) > MAX_FILES:
        raise PackageError(f"تعداد فایل‌ها بیش از {MAX_FILES} است.")
    files, total = {}, 0
    for i in infos:
        name = i.filename
        if not NAME_RE.fullmatch(name) or name != name.strip():
            raise PackageError(f"فایل «{name}» در بسته مجاز نیست.")
        if (i.external_attr >> 28) == 0xA:  # پیوند نمادین
            raise PackageError(f"پیوند نمادین «{name}» مجاز نیست.")
        if i.file_size > MAX_FILE:
            raise PackageError(f"فایل «{name}» بیش از ۲۰۰ کیلوبایت است.")
        if name in files:
            raise PackageError(f"فایل «{name}» دوبار آمده است.")
        with zf.open(i) as fh:
            chunk = fh.read(MAX_FILE + 1)  # حجم واقعی خوانده‌شده، نه ادعای هدر (بمب فشرده)
        if len(chunk) > MAX_FILE:
            raise PackageError(f"فایل «{name}» بیش از ۲۰۰ کیلوبایت است.")
        total += len(chunk)
        if total > MAX_TOTAL:
            raise PackageError("حجم باز‌شده‌ی بسته بیش از ۲ مگابایت است.")
        files[name] = chunk
    return files


def pack(files: dict[str, bytes]) -> bytes:
    """zip قطعی (ترتیب و زمان ثابت) برای ساخت بسته."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, files[name])
    return buf.getvalue()


# ---------------------------------------------------------------------- بررسی
@dataclass
class Step:
    stage: str
    ok: bool
    detail: str = ""


@dataclass
class Inspection:
    steps: list[Step] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    pages: list[pagekit.Page] = field(default_factory=list)
    code: dict[str, str] = field(default_factory=dict)  # سطح ۲: نام handler ← منبع پایتون
    alerts: list[tuple[str, int]] = field(default_factory=list)  # سطح ۲: (handler، هر چند دقیقه)
    tests: dict = field(default_factory=dict)  # سطح ۲: نام handler ← فهرست Case
    publisher: str = ""
    sha256: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def report(self) -> list[dict]:
        return [{"stage": s.stage, "ok": s.ok, "detail": s.detail} for s in self.steps]


def _semver(v: str) -> tuple[int, int, int]:
    m = VERSION_RE.fullmatch(v or "")
    if not m:
        raise PackageError(f"نسخه‌ی «{v}» باید به شکل ۱٫۲٫۳ (عددی) باشد.")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def _manifest(files: dict[str, bytes]) -> dict:
    if MANIFEST_NAME not in files:
        raise PackageError("plugin.toml در بسته نیست.")
    try:
        m = tomllib.loads(files[MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackageError(f"plugin.toml خوانده نشد: {exc}") from exc
    pid = str(m.get("id", ""))
    if not ID_RE.fullmatch(pid):
        raise PackageError(f"شناسه‌ی پلاگین «{pid}» نامعتبر است (حروف کوچک لاتین، رقم و _).")
    _semver(str(m.get("version", "")))
    if not str(m.get("name", "")).strip():
        raise PackageError("نام پلاگین لازم است.")
    if m.get("kind", "custom") not in KINDS:
        raise PackageError(f"نوع پلاگین باید یکی از {'، '.join(KINDS)} باشد (پلاگین سیستمی از راه بسته نمی‌آید).")
    if int(m.get("api", 1)) > API_VERSION:
        raise PackageError(f"بسته قرارداد نسخه‌ی {m.get('api')} می‌خواهد؛ هسته {API_VERSION} است.")
    if int(m.get("tier", 1)) not in (1, 2):
        raise PackageError("فقط سطح ۱ (اعلانی) و ۲ (کد ایزوله) از راه بسته پشتیبانی می‌شود؛ سطح ۳ هنوز نیست.")
    return m


def _check_collision(pid: str) -> None:
    p = registry.plugins.get(pid)
    if p is not None and pid not in _loaded:
        raise PackageError(f"شناسه‌ی «{pid}» با پلاگین داخلی سامانه برخورد دارد.")


def inspect(data: bytes, *, keys: dict | None = None, new_release: bool = True, run_tests: bool = False) -> Inspection:
    """همه‌ی مرحله‌های خودکار (دریافت، امضا، مانیفست، هویت، صفحه‌ها) را اجرا می‌کند؛ اولین شکست بقیه را متوقف می‌کند.
    new_release=False (بررسی دوباره‌ی نسخه‌ی ذخیره‌شده): شرط «نسخه‌ی بالاتر از موجودها» برداشته می‌شود."""
    ins = Inspection()

    def stage(name: str, fn):
        try:
            out = fn()
        except PackageError as exc:
            ins.steps.append(Step(name, False, str(exc)))
            return None
        ins.steps.append(Step(name, True))
        return out

    ins.sha256 = hashlib.sha256(data).hexdigest()
    files = stage("دریافت و بازکردن امن", lambda: read_archive(data))
    if files is None:
        return ins
    ins.files = files
    pub = stage("امضا و ناشر", lambda: verify(files, publisher_keys() if keys is None else keys))
    if pub is None:
        return ins
    ins.publisher = pub
    manifest = stage("مانیفست", lambda: _manifest(files))
    if manifest is None:
        return ins
    ins.manifest = manifest
    if stage("هویت و نسخه", lambda: _identity(manifest, check_version=new_release)) is None:
        return ins
    code = stage("کد سطح ۲", lambda: _code(manifest, files))
    if code is None:
        return ins
    ins.code = code
    if stage("هشدارهای دوره‌ای", lambda: _alerts(manifest, code)) is None:
        return ins
    ins.alerts = _alerts(manifest, code)
    tests = stage("آزمون‌های بسته (ساختار)", lambda: _tests(files, code))
    if tests is None:
        return ins
    ins.tests = tests
    pages = stage("مشخصات صفحه‌ها", lambda: _pages(manifest, files, set(code)))
    if pages is not None:
        ins.pages = pages
        writes = sorted({f"{pg.key}→{fm.table}" for pg in pages for fm in pg.forms} |
                        {f"{pg.key}→جدول تازه ({im.handler})" for pg in pages for im in pg.imports} |
                        {f"{pg.key}→{ig.table} (دریافت عمومی با توکن)" for pg in pages for ig in pg.ingests} |
                        {f"{pg.key}→ساخت جدول {t.name}" for pg in pages for t in pg.tables})
        # خبر برای بازبین: این بسته می‌تواند ردیف بنویسد (فقط INSERT در جدول‌های نام‌برده)؛ مانع نیست
        if run_tests and code:
            stage("آزمون‌های بسته (اجرا)", lambda: _run_tests(code, tests, pages))
        ins.steps.append(Step("دسترسی نوشتن", True, ("فقط INSERT در: " + "، ".join(writes)) if writes else "بدون نوشتن (فقط خواندنی)"))
    return ins


def _identity(manifest: dict, *, check_version: bool = True) -> bool:
    from .models import PluginRelease

    pid, ver = manifest["id"], _semver(str(manifest["version"]))
    _check_collision(pid)
    if check_version:
        for r in PluginRelease.objects.filter(plugin_id=pid).exclude(status=PluginRelease.Status.REJECTED):
            if _semver(r.version) >= ver:
                raise PackageError(f"نسخه‌ی {manifest['version']} باید از نسخه‌ی {r.version} (موجود) بالاتر باشد.")
    missing = [r for r in manifest.get("requires", []) if r not in registry.plugins]
    if missing:
        raise PackageError(f"پلاگین‌های مورد نیاز نصب نیستند: {'، '.join(missing)}")
    return True


def _code(manifest: dict, files: dict[str, bytes]) -> dict[str, str]:
    """کد سطح ۲: فقط با tier = 2، با فهرست handlers هم‌خوان، و بررسی ایستای AST."""
    from .runner import scan

    present = {n[5:-3]: n for n in files if n.startswith("code/")}
    declared = list((manifest.get("contributes") or {}).get("handlers", []))
    if int(manifest.get("tier", 1)) != 2:
        if present or declared:
            raise PackageError("کد پایتون و handlers فقط در بسته‌ی سطح ۲ (tier = 2) مجاز است.")
        return {}
    if sorted(declared) != sorted(present):
        raise PackageError("فهرست handlers مانیفست با فایل‌های code/ یکی نیست.")
    if not present:
        raise PackageError("بسته‌ی سطح ۲ دست‌کم یک handler لازم دارد.")
    out, problems = {}, []
    for name, path in sorted(present.items()):
        try:
            src = files[path].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PackageError(f"{path}: کد باید UTF-8 باشد.") from exc
        problems += scan.scan(src, path)
        if "def handle(" not in src:
            problems.append(f"{path}: تابع handle(ctx, params) تعریف نشده است.")
        out[name] = src
    if problems:
        raise PackageError("؛ ".join(problems[:8]) + (f" (و {len(problems) - 8} مورد دیگر)" if len(problems) > 8 else ""))
    return out


def _tests(files: dict[str, bytes], code: dict[str, str]) -> dict:
    """هر handler فایل tests/<handler>.toml با دست‌کم یک مورد می‌خواهد؛ فایل آزمون برای handlerِ ناموجود یا در سطح ۱ رد می‌شود."""
    from . import pkgtest

    present = {n[6:-5]: n for n in files if n.startswith("tests/")}
    if not code:
        if present:
            raise PackageError("فایل آزمون فقط در بسته‌ی سطح ۲ مجاز است.")
        return {}
    extra = sorted(set(present) - set(code))
    if extra:
        raise PackageError(f"آزمون برای handlerِ ناموجود: {'، '.join(extra)}")
    missing = sorted(set(code) - set(present))
    if missing:
        raise PackageError(f"آزمون لازم است (tests/<نام>.toml با دست‌کم یک مورد) برای: {'، '.join(missing)}")
    total, out = 0, {}
    for name in sorted(present):
        try:
            out[name] = pkgtest.parse(files[present[name]].decode("utf-8"), name)
        except (pkgtest.TestSpecError, UnicodeDecodeError) as exc:
            raise PackageError(str(exc)) from exc
        total += len(out[name])
    if total > pkgtest.MAX_CASES:
        raise PackageError(f"حداکثر {pkgtest.MAX_CASES} مورد آزمون در هر بسته.")
    return out


def _run_tests(code: dict[str, str], tests: dict, pages) -> bool:
    """موردهای آزمون را در runner اجرا می‌کند؛ اولین ناکامی‌ها در پیام می‌آید. روی استقرار بدون runner قابل اجرا نیست."""
    from . import pkgtest

    try:
        res = pkgtest.run_all(code, tests, pkgtest.roles_of(pages or []))
    except pkgtest.TestSpecError as exc:
        raise PackageError(f"آزمون‌ها اجرا نشد: {exc}") from exc
    bad = [r for r in res if not r["ok"]]
    if bad:
        raise PackageError(f"{len(bad)} از {len(res)} مورد ناموفق: " + "؛ ".join(f"{r['handler']}/{r['case']}: {r['message']}" for r in bad[:5]))
    return True


def _alerts(manifest: dict, code: dict[str, str]) -> list[tuple[str, int]]:
    """`[[contributes.alerts]]` handler + every_minutes (۵ تا ۱۴۴۰)؛ فقط سطح ۲ و فقط handlerهای بسته."""
    from . import alerts as alerts_mod

    raw = (manifest.get("contributes") or {}).get("alerts", [])
    if not raw:
        return []
    if not code:
        raise PackageError("هشدار دوره‌ای فقط در بسته‌ی سطح ۲ مجاز است.")
    if not isinstance(raw, list) or len(raw) > 5:
        raise PackageError("حداکثر ۵ هشدار دوره‌ای.")
    out, seen = [], set()
    for a in raw:
        h, every = (a.get("handler") if isinstance(a, dict) else None), (a.get("every_minutes") if isinstance(a, dict) else None)
        if h not in code:
            raise PackageError(f"هشدار: handler «{h}» در بسته نیست.")
        if not isinstance(every, int) or isinstance(every, bool) or not alerts_mod.MIN_EVERY <= every <= alerts_mod.MAX_EVERY:
            raise PackageError(f"هشدار «{h}»: every_minutes باید عدد صحیح بین {alerts_mod.MIN_EVERY} و {alerts_mod.MAX_EVERY} باشد.")
        if h in seen:
            raise PackageError(f"هشدار «{h}» تکراری است.")
        seen.add(h)
        out.append((h, every))
    return out


def _pages(manifest: dict, files: dict[str, bytes], known: set[str] | None = None) -> list[pagekit.Page]:
    declared = list((manifest.get("contributes") or {}).get("pages", []))
    present = sorted(n for n in files if n.startswith("pages/"))
    if sorted(declared) != present:
        raise PackageError("فهرست صفحه‌های مانیفست با فایل‌های pages/ یکی نیست.")
    out, keys = [], set()
    for name in present:
        try:
            spec = tomllib.loads(files[name].decode("utf-8"))
            page = pagekit.parse_page(manifest["id"], spec)
        except (UnicodeDecodeError, tomllib.TOMLDecodeError, pagekit.SpecError) as exc:
            raise PackageError(f"{name}: {exc}") from exc
        for b in page.blocks:
            if b.handler and b.handler not in (known or set()):
                raise PackageError(f"{name}: handler «{b.handler}» در بسته نیست.")
        for item in (*page.imports, *page.exports, *(i for i in page.ingests if i.handler)):
            if item.handler not in (known or set()):
                raise PackageError(f"{name}: handler «{item.handler}» در بسته نیست.")
        if page.key in keys:
            raise PackageError(f"{name}: کلید صفحه‌ی «{page.key}» تکراری است.")
        keys.add(page.key)
        out.append(page)
    if not out:
        raise PackageError("بسته دست‌کم یک صفحه لازم دارد (فعلاً تنها سهم پشتیبانی‌شده).")
    return out


# ---------------------------------------------------------------------- ذخیره و چرخه‌ی عمر
def submit(data: bytes, user) -> PluginRelease:  # noqa: F821
    """بسته را بررسی و (حتی اگر رد شود) با گزارشش ثبت می‌کند."""
    from .models import PluginRelease

    if len(data) > MAX_TOTAL:
        raise PackageError("حجم بسته بیش از ۲ مگابایت است.")
    ins = inspect(data, run_tests=True)
    existing = PluginRelease.objects.filter(sha256=ins.sha256).first()
    if existing:
        raise PackageError(f"همین بسته پیش‌تر بارگذاری شده است ({existing}).")
    m = ins.manifest
    return PluginRelease.objects.create(
        plugin_id=str(m.get("id", ""))[:41], version=str(m.get("version", ""))[:20], name=str(m.get("name", ""))[:120],
        kind=str(m.get("kind", "custom")), publisher=ins.publisher[:60], sha256=ins.sha256, blob=data, size=len(data),
        manifest=json.loads(json.dumps(m, default=str)),
        status=PluginRelease.Status.CHECKED if ins.ok else PluginRelease.Status.REJECTED,
        report=ins.report(), uploaded_by=user)


def second_approval_required() -> bool:
    """انتشار ویزارد تأیید مدیر دیگر بخواهد؟ تنظیم پنل «تأیید نفر دوم» (پیش‌فرض خاموش)."""
    from . import platform

    return platform.get("require_second_approval") == "1"


def can_approve(release, user) -> str:
    """دلیل ممنوع بودن تأیید برای این کاربر (خالی = مجاز)."""
    from .models import PluginRelease

    if release.status not in (PluginRelease.Status.CHECKED, PluginRelease.Status.RETIRED):
        return "فقط نسخه‌ی بررسی‌شده یا جایگزین‌شده فعال می‌شود."
    same = release.uploaded_by_id == getattr(user, "pk", None)
    if release.status == PluginRelease.Status.CHECKED and same and not getattr(settings, "PLUGIN_SELF_APPROVAL", False):
        if release.publisher == PANEL and not second_approval_required():
            return ""  # ساخته‌ی ویزارد و «تأیید نفر دوم» خاموش است (ADR-0008)
        return "بارگذارنده نمی‌تواند خودش تأیید کند (اصل دونفره)."
    return ""


@transaction.atomic
def activate(release, user, *, apply_access: bool = True) -> None:
    """نسخه را فعال می‌کند (قبلی جایگزین می‌شود)؛ پلاگین تازه با «محدود و بدون مجوز» ساخته می‌شود: تا مدیر مجوز ندهد کسی نمی‌بیندش."""
    from .models import PluginRelease, PluginState

    why = can_approve(release, user)
    if why:
        raise PackageError(why)
    ins = inspect(bytes(release.blob), new_release=False, run_tests=True)  # دوباره: کلید ناشر ممکن است حذف شده باشد
    if not ins.ok:
        raise PackageError("بررسی دوباره‌ی بسته موفق نبود: " + "؛ ".join(s.detail for s in ins.steps if not s.ok))
    PluginRelease.objects.filter(plugin_id=release.plugin_id, status=PluginRelease.Status.ACTIVE).update(
        status=PluginRelease.Status.RETIRED)
    release.status = PluginRelease.Status.ACTIVE
    release.approved_by = user
    release.activated_at = timezone.now()
    release.save()
    PluginState.objects.get_or_create(plugin_id=release.plugin_id, defaults={"access": PluginState.Access.RESTRICTED})
    if release.access and apply_access:  # انتشار از ویزارد با تأیید بعدی: دسترسی/مجوز/قیمتی که مدیر انتخاب کرده اعمال شود
        from . import market, publish

        try:
            publish.apply_access(release.plugin_id, release.access)
        except market.MarketError:
            log.exception("market listing failed for %s", release.plugin_id)  # فعال‌سازی را برنمی‌گردانیم


@transaction.atomic
def deactivate(release) -> None:
    from .models import PluginRelease

    if release.status == PluginRelease.Status.ACTIVE:
        release.status = PluginRelease.Status.RETIRED
        release.save(update_fields=["status"])


# ---------------------------------------------------------------------- بارگذاری در رجیستری
_loaded: dict[str, str] = {}  # شناسه‌ی پلاگین ← چکیده‌ی نسخه‌ی فعال بارگذاری‌شده (فقط پلاگین‌های بسته)


def sync() -> int:
    """رجیستری این پردازه را با نسخه‌های فعال هماهنگ می‌کند: افزودن، تعویض و حذف؛ تعداد تغییرها را برمی‌گرداند."""
    from .models import PluginRelease

    active = {r.plugin_id: r for r in PluginRelease.objects.filter(status=PluginRelease.Status.ACTIVE)}
    changed = 0
    for pid in [p for p in _loaded if p not in active or _loaded[p] != active[p].sha256]:
        registry.remove_plugin(pid)
        _loaded.pop(pid, None)
        changed += 1
    for pid, rel in active.items():
        if pid in _loaded:
            continue
        if pid in registry.plugins:  # برخورد با پلاگین داخلی: هرگز بازنویسی نمی‌شود
            registry.errors[pid] = "شناسه با پلاگین داخلی برخورد دارد؛ نسخه‌ی بسته بار نشد."
            continue
        try:
            ins = inspect(bytes(rel.blob), new_release=False)
            if not ins.ok:
                raise PackageError("؛ ".join(s.detail for s in ins.steps if not s.ok))
            m = ins.manifest
            registry.register(pid, m["name"], kind=m.get("kind", "custom"), version=m["version"],
                              requires=tuple(m.get("requires", ())), description=str(m.get("description", "")))
            for page in ins.pages:
                pagekit.register(pid, page)
            for hname, src in ins.code.items():
                handlers.register(pid, hname, src)
            for hname, every in ins.alerts:
                alerts.register(pid, hname, every)
            _loaded[pid] = rel.sha256
            changed += 1
        except Exception as exc:  # noqa: BLE001  بسته‌ی معیوب سایت را نمی‌خواباند
            log.exception("plugin package %s failed to load", pid)
            registry.remove_plugin(pid)
            registry.errors[pid] = f"بسته‌ی فعال بار نشد: {exc}"
    return changed
