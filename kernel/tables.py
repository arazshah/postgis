"""ساخت خودکار جدول پلاگین در پایگاه مشتری (docs/adr/0008، مرحله‌ی ۲).

صفحه‌ی پلاگین جدول‌هایش را با `[[tables]]` اعلام می‌کند؛ هسته هنگام **نخستین استفاده** در پایگاه همان مشتری (باز کردن صفحه،
ثبت فرم، دریافت داده) آن را می‌سازد. اصل‌ها:
- **فقط افزایشی:** `CREATE TABLE IF NOT EXISTS` و `ADD COLUMN IF NOT EXISTS` (ستون تازه همیشه nullable). هرگز حذف، تغییر نوع یا بازنویسی.
- **نام با پیشوند `<id پلاگین>_`**، فقط در `public`؛ جدولِ هم‌نامِ ازپیش‌موجودِ غیرِ ساخته‌ی همین پلاگین = خطا، نه دست‌زدن.
- نوع ستون فقط از فهرست سفید؛ نام‌ها با `Identifier` و هیچ متنی از پلاگین وارد SQL نمی‌شود. اتصال با نقش مالک (`tenantdb`).
- تکرارپذیر و بی‌خطر در رقابت: ساخت `IF NOT EXISTS` است و ردپا `get_or_create`.
خوانندگان مرورگر (`pg_read_all_data`) بدون GRANT جدول تازه را می‌خوانند.
"""
from __future__ import annotations

import hashlib
import json
import logging

from django.db import IntegrityError, transaction
from psycopg import sql

from . import tenantdb
from .pagekit import GEOM_KINDS as GEOM_TYPES
from .pagekit import ColumnSpec, TableSpec

log = logging.getLogger(__name__)
TYPES = {"text": "text", "integer": "integer", "bigint": "bigint", "double": "double precision", "boolean": "boolean",
         "date": "date", "timestamptz": "timestamptz", "jsonb": "jsonb", "point": "geometry(Point, 4326)",
         "line": "geometry(LineString, 4326)", "polygon": "geometry(Polygon, 4326)", "multipolygon": "geometry(MultiPolygon, 4326)"}


class TableError(Exception):
    """پیام فارسی کوتاه برای کاربر/مدیر."""


def spec_hash(t: TableSpec) -> str:
    raw = json.dumps([t.name, [(c.name, c.type, c.required, c.auto_now) for c in t.columns], t.indexes], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _column(c: ColumnSpec, *, create: bool) -> sql.Composable:
    parts = [sql.Identifier(c.name), sql.SQL(TYPES[c.type])]
    if create and c.required:
        parts.append(sql.SQL("NOT NULL"))
    if c.auto_now:
        parts.append(sql.SQL("DEFAULT now()"))
    return sql.SQL(" ").join(parts)


def create_statement(t: TableSpec) -> sql.Composable:
    cols = [sql.SQL("id bigserial PRIMARY KEY")] + [_column(c, create=True) for c in t.columns]
    return sql.SQL("CREATE TABLE IF NOT EXISTS {rel} ({cols})").format(
        rel=sql.Identifier("public", t.name), cols=sql.SQL(", ").join(cols))


def index_statements(t: TableSpec) -> list[sql.Composable]:
    out = []
    for i, cols in enumerate(t.indexes, 1):
        name = f"{t.name[:50]}_ix{i}"
        out.append(sql.SQL("CREATE INDEX IF NOT EXISTS {n} ON {rel} ({cols})").format(
            n=sql.Identifier(name), rel=sql.Identifier("public", t.name), cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols)))
    if any(c.type in GEOM_TYPES for c in t.columns):
        for c in t.columns:
            if c.type in GEOM_TYPES:
                out.append(sql.SQL("CREATE INDEX IF NOT EXISTS {n} ON {rel} USING gist ({c})").format(
                    n=sql.Identifier(f"{t.name[:48]}_{c.name[:10]}_gx"), rel=sql.Identifier("public", t.name), c=sql.Identifier(c.name)))
    return out


def owners(ws, schema: str, name: str) -> list[str]:
    """شناسه‌ی پلاگین‌هایی که این جدول را برای این پایگاه ساخته‌اند (برای هشدار پیش از حذف)."""
    if schema != "public":
        return []
    from .models import PluginTable

    return sorted(PluginTable.objects.filter(workspace_id=ws.pk, table=name).values_list("plugin_id", flat=True))


def probe(ws, tables) -> dict[str, set[str]] | None:
    """ستون‌های موجودِ هر جدول در `public` (جدولِ نبود = کلید ندارد). یک پرس‌وجوی سبک برای همه؛ خطا ⇒ None (بررسی رد می‌شود)."""
    names = [t.name for t in tables]
    try:
        with tenantdb.connect(ws) as conn:
            rows = conn.execute(
                "SELECT c.relname, a.attname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND c.relname = ANY(%s)", (names,)).fetchall()
    except Exception:  # noqa: BLE001  نبود اتصال را «جدول نیست» نگیریم؛ خود خواندن خطا را نشان می‌دهد
        return None
    out: dict[str, set[str]] = {}
    for rel, col in rows:
        out.setdefault(rel, set()).add(col)
    return out


def ensure(ws, plugin: str, tables, restored: list | None = None) -> int:
    """جدول‌های اعلام‌شده را در پایگاه `ws` تضمین می‌کند؛ تعداد جدول ساخته/به‌روز/ترمیم‌شده. TableError اگر ممکن نیست.

    ردپا (`PluginTable`) ثابت می‌کند جدول را همین پلاگین ساخته بود؛ پس اگر کاربر جدول (یا ستونی از آن) را حذف کرده باشد،
    همان ساختار اعلام‌شده دوباره (خالی) ساخته می‌شود. نام جدول‌های ترمیم‌شده به `restored` افزوده و در گزارش فضای کار ثبت می‌شود."""
    from .models import PluginTable

    recs = {r.table: r for r in PluginTable.objects.filter(plugin_id=plugin, workspace_id=ws.pk, table__in=[t.name for t in tables])}
    fresh = [t for t in tables if t.name in recs and recs[t.name].spec_hash == spec_hash(t)]
    have = probe(ws, fresh) if fresh else None
    done = 0
    for t in tables:
        h = spec_hash(t)
        rec = recs.get(t.name)
        healed = False
        if rec is not None and rec.spec_hash == h:
            if have is None or (t.name in have and {c.name for c in t.columns} <= have[t.name]):
                continue
            healed = True  # جدول یا ستونی حذف شده است
        try:
            cat = tenantdb.catalog(ws)
            existing = next((x for x in cat.tables() if x.schema == "public" and x.name == t.name), None)
            if existing is not None and rec is None:
                raise TableError(f"جدولی به نام «{t.name}» از قبل در این پایگاه داده هست و از این پلاگین نیست؛ آن را تغییر نام دهید.")
            if existing is not None and existing.kind not in ("r", "p"):
                raise TableError(f"«{t.name}» جدول عادی نیست.")
            have = {c["name"] for c in cat.columns(existing)} if existing is not None else set()
            with tenantdb.connect(ws, write=True, as_owner=True) as conn:
                conn.execute(sql.SQL("SET LOCAL statement_timeout = '30s'"))
                if existing is None:
                    conn.execute(create_statement(t))
                else:  # فقط افزودن ستون تازه (nullable)
                    for c in t.columns:
                        if c.name not in have:
                            conn.execute(sql.SQL("ALTER TABLE {rel} ADD COLUMN IF NOT EXISTS {col}").format(
                                rel=sql.Identifier("public", t.name), col=_column(c, create=False)))
                for stmt in index_statements(t):
                    conn.execute(stmt)
                conn.commit()
        except TableError:
            raise
        except tenantdb.TenantError as exc:
            raise TableError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001  سهمیه، دسترسی، قید…: پیام کوتاه، جزئیات در لاگ
            log.warning("plugin table %s.%s failed: %s", plugin, t.name, str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
            raise TableError(f"ساخت جدول «{t.name}» انجام نشد (سهمیه یا دسترسی پایگاه داده).") from exc
        try:
            with transaction.atomic():
                PluginTable.objects.update_or_create(plugin_id=plugin, table=t.name, workspace_id=ws.pk, defaults={"spec_hash": h})
        except IntegrityError:  # رقابت: همزمان ثبت شد
            PluginTable.objects.filter(plugin_id=plugin, table=t.name, workspace_id=ws.pk).update(spec_hash=h)
        done += 1
        if healed:
            log.warning("plugin table %s.%s was missing and restored (ws=%s)", plugin, t.name, ws.pk)
            if restored is not None:
                restored.append(t.name)
            try:
                from . import workspace

                workspace.log_event("plugin_table_restored", f"جدول «{t.name}» پلاگین «{plugin}» حذف شده بود و دوباره (خالی) ساخته شد.", database=ws)
            except Exception:  # noqa: BLE001  گزارش‌دهی نباید ترمیم را بشکند
                log.exception("restore event failed")
    return done
