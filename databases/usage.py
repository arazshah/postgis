"""داشبورد مصرف هر پایگاه داده: حجم جدول‌ها، اتصال‌ها، کوئری‌های در حال اجرا و کند، پیشنهاد نمایه."""
from __future__ import annotations

from datetime import timedelta

import psycopg
from django.utils import timezone

from .models import SizeSample, UserDatabase
from .provisioner import Provisioner, ProvisionError


def _roles(db: UserDatabase, conn) -> list[str]:
    return [db.role_name, *Provisioner.helper_roles(db.role_name), *Provisioner.extra_roles(conn, db.role_name)]


def collect(db: UserDatabase) -> dict:
    """همه آمار با کاربر مدیر خوانده می‌شود، اما فقط برای همین دیتابیس و نقش‌های همین کاربر."""
    p = Provisioner.for_server(db.server)
    out = {"tables": [], "suggestions": [], "connections": [], "running": [], "slow": None, "slow_note": ""}
    with p.connect() as conn:
        roles = _roles(db, conn)
        out["connections"] = [dict(zip(("user", "app", "state", "count"), r, strict=True)) for r in conn.execute("""
            SELECT usename, COALESCE(NULLIF(application_name, ''), '—'), COALESCE(state, '—'), count(*)
            FROM pg_stat_activity WHERE datname = %s AND usename = ANY(%s) AND pid <> pg_backend_pid()
            GROUP BY 1, 2, 3 ORDER BY 4 DESC""", (db.db_name, roles)).fetchall()]
        out["running"] = [dict(zip(("pid", "user", "app", "seconds", "query"), r, strict=True)) for r in conn.execute("""
            SELECT pid, usename, COALESCE(NULLIF(application_name, ''), '—'),
                   EXTRACT(EPOCH FROM now() - query_start)::int, left(query, 400)
            FROM pg_stat_activity
            WHERE datname = %s AND usename = ANY(%s) AND state = 'active' AND pid <> pg_backend_pid()
              AND application_name NOT LIKE 'geopaygah%%'
            ORDER BY query_start LIMIT 20""", (db.db_name, roles)).fetchall()]
    with p.connect(dbname=db.db_name) as conn:
        rows = conn.execute("""
            SELECT n.nspname, c.relname, pg_total_relation_size(c.oid), pg_relation_size(c.oid),
                   GREATEST(c.reltuples, 0)::bigint, COALESCE(s.seq_scan, 0), COALESCE(s.idx_scan, 0),
                   COALESCE(s.n_dead_tup, 0), COALESCE(s.n_live_tup, 0),
                   EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE c.relkind IN ('r', 'm', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg\\_%%' AND NOT (n.nspname = 'public' AND c.relname = 'spatial_ref_sys')
            ORDER BY 3 DESC LIMIT 25""").fetchall()
        for schema, name, total, heap, est, seq, idx, dead, live, has_pk in rows:
            t = {"schema": schema, "name": name, "total": total, "heap": heap, "index": max(0, total - heap),
                 "rows": max(est, live), "seq": seq, "idx": idx, "dead": dead}
            out["tables"].append(t)
            if t["rows"] >= 5000 and seq >= 50 and seq > 10 * max(idx, 1):
                out["suggestions"].append({"kind": "index", "table": f"{schema}.{name}", "text":
                    f"{seq:,} بار کل جدول خوانده شده و فقط {idx:,} بار از نمایه استفاده شده؛ برای ستون‌هایی که در "
                    "WHERE یا JOIN می‌آیند نمایه بسازید (هندسه: GIST)."})
            if live and dead > 10000 and dead > live * 0.2:
                out["suggestions"].append({"kind": "vacuum", "table": f"{schema}.{name}", "text":
                    f"{dead:,} سطر حذف‌شده هنوز فضا گرفته‌اند؛ «VACUUM (ANALYZE) {schema}.{name};» را اجرا کنید."})
            if not has_pk and t["rows"] > 0:
                out["suggestions"].append({"kind": "pk", "table": f"{schema}.{name}", "text":
                    "کلید اصلی ندارد؛ QGIS و انتشار لایه به کلید اصلی نیاز دارند (بخش «سلامت داده»)."})
        for schema, table, index, size in conn.execute("""
                SELECT s.schemaname, s.relname, s.indexrelname, pg_relation_size(s.indexrelid)
                FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
                WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
                  AND pg_relation_size(s.indexrelid) > 8 * 1024 * 1024
                ORDER BY 4 DESC LIMIT 5""").fetchall():
            out["suggestions"].append({"kind": "unused", "table": f"{schema}.{table}", "text":
                f"نمایه «{index}» ({size // 1048576} مگابایت) تا حالا استفاده نشده؛ اگر لازم نیست حذفش کنید."})
        out["slow"], out["slow_note"] = _slow(conn, db)
    return out


def _slow(conn, db) -> tuple[list | None, str]:
    """۱۰ کوئری پرهزینه از pg_stat_statements (اگر روی سرور فعال باشد)."""
    preload = conn.execute("SELECT current_setting('shared_preload_libraries')").fetchone()[0] or ""
    if "pg_stat_statements" not in preload:
        return None, "آمار کوئری‌های کند (pg_stat_statements) روی این سرور فعال نیست."
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        rows = conn.execute("""
            SELECT left(regexp_replace(query, '\\s+', ' ', 'g'), 300), calls, round(mean_exec_time::numeric, 1),
                   round(total_exec_time::numeric / 1000, 1), rows
            FROM pg_stat_statements s JOIN pg_roles r ON r.oid = s.userid
            WHERE s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND r.rolname NOT LIKE '%%\\_web' AND query NOT ILIKE '%%pg_stat%%'
            ORDER BY total_exec_time DESC LIMIT 10""").fetchall()
    except psycopg.Error:
        return None, "آمار کوئری‌ها در دسترس نیست."
    return [dict(zip(("query", "calls", "mean_ms", "total_s", "rows"), r, strict=True)) for r in rows], ""


def cancel(db: UserDatabase, pid: int) -> bool:
    """فقط کوئری نقش‌های همین پایگاه داده روی همین دیتابیس."""
    p = Provisioner.for_server(db.server)
    with p.connect() as conn:
        roles = _roles(db, conn)
        row = conn.execute("SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE pid = %s AND datname = %s "
                           "AND usename = ANY(%s)", (pid, db.db_name, roles)).fetchone()
    return bool(row and row[0])


def history(db: UserDatabase, days: int = 30) -> list[dict]:
    since = timezone.localdate() - timedelta(days=days - 1)
    return [{"day": s.day, "size": s.size_bytes}
            for s in SizeSample.objects.filter(database=db, day__gte=since).order_by("day")]


def requests(db: UserDatabase, days: int = 14) -> list[dict]:
    from publish.models import DailyUsage

    since = timezone.localdate() - timedelta(days=days - 1)
    got = dict(DailyUsage.objects.filter(database=db, day__gte=since).values_list("day", "requests"))
    return [{"day": since + timedelta(days=i), "n": got.get(since + timedelta(days=i), 0)} for i in range(days)]


def safe_collect(db: UserDatabase) -> tuple[dict | None, str]:
    try:
        return collect(db), ""
    except (ProvisionError, psycopg.Error) as exc:
        return None, f"خواندن آمار ممکن نشد: {exc}"
