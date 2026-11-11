"""موتور ابزارهای تحلیل: اعتبارسنجی، ساخت جدول نتیجه در پایگاه کاربر (با نقش خود او) و خط لوله‌ی مشترک خروجی.

خود ابزارها پلاگین‌اند (tools/sdk.py)؛ این ماژول هیچ ابزاری را به نام نمی‌شناسد.
"""
from __future__ import annotations

from psycopg import sql

from databases.explorer import Explorer, ExplorerError
from databases.gdal import TABLE_RE

from . import sdk
from .sdk import ToolError

TIMEOUT = "180s"
COMMON_PARAMS = ("output", "replace")


def tool_map() -> dict:
    return {t.key: t for t in sdk.all_tools()}


def public_params(key: str | None = None) -> tuple[str, ...]:
    """نام پارامترهایی که از فرم پذیرفته می‌شود: پارامترهای خود ابزار (یا همه‌ی ابزارها) + نام خروجی و جایگزینی."""
    tools = [sdk.get(key)] if key else sdk.all_tools()
    names = dict.fromkeys(p.name for t in tools if t for p in t.params)
    return (*names, *COMMON_PARAMS)


def __getattr__(name):  # سازگاری با مصرف‌کننده‌های قدیمی
    if name == "TOOLS":
        return sdk.all_tools()
    if name == "TOOL_MAP":
        return tool_map()
    if name == "PUBLIC_PARAMS":
        return public_params()
    raise AttributeError(name)


def _fix_geom_type(conn, target) -> None:
    """ستون geom حاصل از عبارت، نوع و SRID ندارد (geometry خالی) و QGIS و نقشه آن را بدون مختصات می‌بینند؛
    نوع را از خود داده (و Multi اگر تک و چندبخشی قاطی باشند) و SRID را 4326 می‌گذارد."""
    types = {r[0] for r in conn.execute(sql.SQL("SELECT DISTINCT GeometryType(geom) FROM {} WHERE geom IS NOT NULL")
                                        .format(target)).fetchall()}
    base = {t.removeprefix("MULTI") for t in types}
    if len(types) == 1:
        gtype, expr = types.pop(), "ST_SetSRID(geom, 4326)"
    elif len(base) == 1 and base.pop() in ("POINT", "LINESTRING", "POLYGON"):
        gtype, expr = "MULTI" + next(iter(types)).removeprefix("MULTI"), "ST_Multi(ST_SetSRID(geom, 4326))"
    else:
        gtype, expr = "GEOMETRY", "ST_SetSRID(geom, 4326)"
    conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN geom TYPE geometry({}, 4326) USING " + expr).format(
        target, sql.SQL(gtype)))


def _prepare(db, key: str, params: dict):
    """اعتبارسنجی پارامترها و ساخت SELECT نهایی؛ به پایگاه داده کاربر فقط کاتالوگ را می‌خواند."""
    tool = sdk.get(key)
    if tool is None:
        raise ToolError("ابزار ناشناخته است.")
    out = (params.get("output") or "").strip().lower()
    if not TABLE_RE.match(out):
        raise ToolError("نام جدول خروجی: حروف کوچک لاتین، رقم و _ (مثلاً metro_buffer_500).")
    ex = Explorer(db)
    tables = {f"{t.schema}.{t.name}": t for t in ex.tables()}
    if f"public.{out}" in tables and params.get("replace") != "on":
        raise ToolError(f"جدول {out} از قبل وجود دارد؛ نام دیگری بدهید یا «جایگزین شود» را بزنید.")
    ctx = sdk.Context(ex=ex, tables=tables, params=params)
    body = tool.build(ctx)
    if not isinstance(body, sql.Composable):
        raise ToolError("ابزار SQL امن برنگرداند.")  # محافظ در برابر رشته‌ی خام
    return ex, out, sql.Identifier("public", out), body, ctx.guards


def validate(db, key: str, params: dict) -> str:
    """همان بررسی‌های اجرا، بدون اجرا؛ نام جدول خروجی را برمی‌گرداند."""
    return _prepare(db, key, params)[1]


def summarize(db, key: str, params: dict) -> str:
    """توضیح کوتاه فارسی از ورودی‌ها برای ردیف تاریخچه."""
    tool = sdk.get(key)
    return tool.summary(params) if tool else ""


def run_job(job) -> dict:
    """اجرا در کارگر؛ پارامترها از ToolRun خوانده می‌شود."""
    run_ = job.tool_run
    return run(job.database, run_.tool, run_.params, job=job, run_row=run_)


def run(db, key: str, params: dict, job=None, run_row=None) -> dict:
    def step(pct: int, text: str):
        if job is not None:
            job.set_progress(pct, text)

    step(5, "بررسی ورودی‌ها")
    ex, out, target, body, guards = _prepare(db, key, params)
    tool = sdk.get(key)
    step(12, "ساخت جدول نتیجه (سنگین‌ترین مرحله)")
    from databases.provisioner import Provisioner

    try:
        with ex.connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
            conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(TIMEOUT)))
            for q, cap, msg in guards:
                if conn.execute(q).fetchone()[0] > cap:
                    raise ToolError(msg)
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(target))
            conn.execute(sql.SQL("CREATE TABLE {} AS {}").format(target, body))
            tool.after_create(conn, target)
            step(65, "تنظیم نوع هندسه و سیستم مختصات")
            _fix_geom_type(conn, target)
            step(78, "افزودن کلید اصلی")
            conn.execute(sql.SQL("ALTER TABLE {} ADD COLUMN gid serial PRIMARY KEY").format(target))
            step(86, "ساخت نمایه مکانی")
            conn.execute(sql.SQL("CREATE INDEX ON {} USING gist (geom)").format(target))
            step(94, "آماده‌سازی نهایی")
            conn.execute(sql.SQL("ANALYZE {}").format(target))
            n = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0]
            conn.commit()
    except ExplorerError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001  خطای PostgreSQL (مثلاً timeout)
        msg = str(exc).splitlines()[0]
        if "statement timeout" in msg:
            msg = "تحلیل بیش از ۳ دقیقه طول کشید؛ داده را کوچک‌تر کنید یا پارامتر را تغییر دهید."
        raise ToolError(f"تحلیل انجام نشد: {msg}") from exc
    Provisioner.for_server(db.server).reassign_browser_objects(db.db_name, db.role_name)
    if run_row is not None:
        run_row.rows = n
        run_row.save(update_fields=["rows"])
    return {"table": out, "rows": n}
