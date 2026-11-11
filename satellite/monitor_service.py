"""پایش خودکار: هر چند روز یک‌بار تصویرهای تازه‌ی بازه را برای قطعه‌های یک لایه روی دروازه می‌سنجد، نتیجه را به جدول
خود کاربر اضافه می‌کند و اگر شاخص یک قطعه نسبت به تصویر قبلی محسوس افت کرد اعلان هشدار می‌فرستد.
هیچ محاسبه‌ای روی سرور ایران نیست؛ اینجا فقط صف‌کردن، یک پرس‌وجوی کوچک روی جدول نتیجه و اعلان است."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from psycopg import sql

from databases.models import UserDatabase
from kernel import tenantdb
from notifications.models import Notification
from satgate import spec

from . import client, zonal_service
from .models import SatAnalysis, SatMonitor
from .services import SatError, fa

MAX_STARTS_PER_TICK = 3                   # فشار هم‌زمان روی دروازه را محدود نگه می‌دارد
FIRST_LOOKBACK_DAYS = 60                  # اولین اجرا: دست‌کم دو تصویر برای مقایسه
ALERT_FEATURES_SHOWN = 6


# ---------------------------------------------------------------------- سهمیه و ساخت
def limits(db: UserDatabase) -> dict:
    cap = db.plan.sat_monitors if db.plan_id else 0
    return {"cap": cap, "used": SatMonitor.objects.filter(database=db).count()}


def _params(data: dict) -> dict:
    index = str(data.get("index") or "ndvi")
    mission = str(data.get("mission") or "sentinel2")
    if index not in spec.INDICES:
        raise SatError("شاخص نامعتبر است.", "bad")
    if mission not in spec.MISSIONS:
        raise SatError("ماهواره‌ی نامعتبر است.", "bad")
    try:
        every = int(data.get("every_days") or 7)
        drop = int(data.get("drop_pct") or 20)
        cloud = float(data.get("max_cloud") or 40)
    except (TypeError, ValueError) as exc:
        raise SatError("مقدارها نامعتبر است.", "bad") from exc
    if every not in (7, 14, 30):
        raise SatError("بازه‌ی بررسی باید ۷، ۱۴ یا ۳۰ روز باشد.", "bad")
    if not 5 <= drop <= 90:
        raise SatError("درصد افت باید بین ۵ تا ۹۰ باشد.", "bad")
    layer, col = str(data.get("layer") or "").strip(), str(data.get("id_column") or "").strip()
    if not layer or not col:
        raise SatError("لایه و ستون شناسه را انتخاب کنید.", "bad")
    return {"index": index, "mission": mission, "every_days": every, "drop_pct": drop, "max_cloud": max(5.0, min(cloud, 90.0)),
            "layer": layer, "id_column": col, "name": str(data.get("name") or "").strip()[:80]}


def create(db: UserDatabase, user, data: dict) -> SatMonitor:
    p = _params(data)
    lim = limits(db)
    if lim["cap"] <= 0:
        raise SatError("پلن شما پایش خودکار ندارد.", "no_service")
    if lim["used"] >= lim["cap"]:
        raise SatError(f"سقف پایش پلن شما ({fa(lim['cap'])}) پر است؛ یکی را حذف کنید یا پلن را ارتقا دهید.", "limit")
    feats, _, km2 = zonal_service.read_features(db, p["layer"], p["id_column"])
    if km2 > db.plan.sat_max_km2:
        raise SatError(f"مساحت لایه ({fa(round(km2))} کیلومتر مربع) از سقف پلن ({fa(db.plan.sat_max_km2)}) بیشتر است.", "area")
    table = zonal_service.default_name(p["index"], p["layer"])
    table = ("mon_" + table)[:39]
    if not zonal_service.NAME_RE.match(table):
        raise SatError("نام جدول نتیجه از روی نام لایه ساخته نشد؛ لایه را تغییر نام دهید.", "name")
    if zonal_service._exists(db, table) or SatMonitor.objects.filter(database=db, table_name=table).exists():
        raise SatError(f"جدولی به نام {table} از قبل هست؛ برای همین لایه و شاخص پایش دیگری ساخته شده یا جدول را حذف کنید.", "exists")
    name = p["name"] or f"پایش {spec.INDICES[p['index']][2]} · {p['layer']}"
    return SatMonitor.objects.create(
        database=db, user=user, name=name, layer=p["layer"], id_column=p["id_column"], table_name=table, mission=p["mission"],
        index=p["index"], max_cloud=p["max_cloud"], every_days=p["every_days"], drop_pct=p["drop_pct"],
        last_message=f"{fa(len(feats))} قطعه؛ اولین بررسی به‌زودی انجام می‌شود.")


# ---------------------------------------------------------------------- زمان‌بندی
def due(m: SatMonitor, now: datetime) -> bool:
    if not m.enabled or not m.database.is_live or not (m.database.plan_id and m.database.plan.sat_monitors):
        return False
    if m.runs.filter(status__in=[SatAnalysis.Status.PROCESSING, SatAnalysis.Status.DOWNLOADING]).exists():
        return False
    return m.last_run_at is None or now - m.last_run_at >= timedelta(days=m.every_days)


def start_run(m: SatMonitor, now: datetime | None = None) -> SatAnalysis | None:
    """یک دور پایش را روی دروازه می‌فرستد. اعتبار تحلیل مصرف نمی‌کند (سقف با «تعداد پایش» و بازه‌ی اجراست)."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    start = (m.last_scene_date + timedelta(days=1)) if m.last_scene_date else today - timedelta(days=FIRST_LOOKBACK_DAYS)
    start = min(start, today)
    m.last_run_at = now
    try:
        feats, _, km2 = zonal_service.read_features(m.database, m.layer, m.id_column)
    except Exception as exc:  # noqa: BLE001 لایه حذف شده یا ستون عوض شده
        m.last_message = (str(exc) or "لایه خوانده نشد.")[:300]
        m.save(update_fields=["last_run_at", "last_message"])
        return None
    an = SatAnalysis.objects.create(
        database=m.database, user=m.user, name=m.table_name, layer=m.layer, id_column=m.id_column, mission=m.mission, index=m.index,
        mask=True, features=len(feats), area_km2=round(km2, 2), start=start, end=today, max_cloud=m.max_cloud, charged=False, monitor=m)
    try:
        client.call("POST", "/v1/analyze", {
            "id": an.token, "features": feats, "index": m.index, "mission": m.mission, "start": start.isoformat(),
            "end": today.isoformat(), "max_cloud": m.max_cloud, "max_scenes": zonal_service.DEFAULT_SCENES, "mask": True,
            "max_km2": m.database.plan.sat_max_km2}, timeout=90)
        m.last_message = "در حال بررسی تصویرهای تازه…"
    except client.GatewayError as exc:
        zonal_service._fail(an, str(exc), refund=False)
        m.last_message = f"دروازه در دسترس نبود؛ بار بعد دوباره تلاش می‌شود. ({exc})"[:300]
        m.last_run_at = now - timedelta(days=m.every_days) + timedelta(hours=6)     # شش ساعت دیگر
    m.save(update_fields=["last_run_at", "last_message"])
    return an


def run_due(now: datetime | None = None) -> int:
    now = now or timezone.now()
    n = 0
    for m in SatMonitor.objects.filter(enabled=True).select_related("database__plan", "database__server"):
        if n >= MAX_STARTS_PER_TICK:
            break
        if due(m, now) and start_run(m, now):
            n += 1
    return n


def run_failed(an: SatAnalysis) -> None:
    """دور پایش بدون نتیجه (مثلاً تصویر بی‌ابر نبود): بی‌سروصدا در وضعیت پایش ثبت می‌شود، نه اعلان."""
    if an.monitor_id:
        SatMonitor.objects.filter(pk=an.monitor_id).update(last_message=(an.message or "تصویر مناسبی پیدا نشد.")[:300])


# ---------------------------------------------------------------------- مقایسه و هشدار
def detect_drops(pairs: list[tuple], drop_pct: float) -> list[dict]:
    """pairs: (شناسه، میانگین تازه، میانگین قبلی). افت نسبی ≥ آستانه ← هشدار. مقدار قبلی ≤ ۰ نادیده می‌ماند (نسبت بی‌معنی است)."""
    out = []
    for fid, new, old in pairs:
        if new is None or old is None or old <= 0:
            continue
        pct = round((old - new) / old * 100, 6)
        if pct >= drop_pct:
            out.append({"id": fid, "new": round(new, 3), "old": round(old, 3), "drop": round(pct)})
    return sorted(out, key=lambda d: -d["drop"])


def _pairs(m: SatMonitor, since: date | None) -> list[tuple]:
    """برای هر قطعه: میانگین تصویر تازه (فقط اگر بعد از آخرین تصویر پردازش‌شده‌ی قبلی باشد) و تصویر معتبر قبل از آن."""
    ex = tenantdb.catalog(m.database)
    tbl = sql.Identifier(zonal_service.SCHEMA, m.table_name)
    with ex.connect() as conn:
        conn.execute("SET statement_timeout = 20000")
        rows = conn.execute(sql.SQL(
            "WITH r AS (SELECT feature_id, scene_date, mean, row_number() OVER (PARTITION BY feature_id ORDER BY scene_date DESC) rn "
            "FROM {} WHERE mean IS NOT NULL AND valid_pct >= %s) "
            "SELECT a.feature_id, a.mean, b.mean FROM r a JOIN r b ON a.feature_id = b.feature_id AND a.rn = 1 AND b.rn = 2 "
            "WHERE %s::date IS NULL OR a.scene_date > %s::date").format(tbl), (m.min_valid_pct, since, since)).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def after_run(an: SatAnalysis, rows: list[dict]) -> None:
    """بعد از نوشتن ردیف‌های تازه در جدول: آخرین تاریخ را ثبت کن و در صورت افت، هشدار بده."""
    m = an.monitor
    if m is None:
        return
    newest = max((r["date"] for r in rows), default=None)
    since = m.last_scene_date
    try:
        drops = detect_drops(_pairs(m, since), m.drop_pct) if newest else []
    except Exception:  # noqa: BLE001 مقایسه نباید ثبت نتیجه را خراب کند
        drops = []
    m.last_scene_date = date.fromisoformat(newest) if newest else m.last_scene_date
    m.last_message = (f"{fa(len(drops))} قطعه افت کرد." if drops else "تصویر تازه بررسی شد؛ افت محسوسی نبود.") if newest else \
        "تصویر تازه‌ی مناسبی پیدا نشد."
    fields = ["last_scene_date", "last_message"]
    if drops:
        shown = "، ".join(f"{d['id']} ({fa(d['drop'])}٪)" for d in drops[:ALERT_FEATURES_SHOWN])
        more = f" و {fa(len(drops) - ALERT_FEATURES_SHOWN)} قطعه‌ی دیگر" if len(drops) > ALERT_FEATURES_SHOWN else ""
        if m.user_id:
            Notification.objects.create(
                user_id=m.user_id, level=Notification.Level.WARNING, database=m.database,
                title=f"افت {spec.INDICES[m.index][2]} در «{m.name}»",
                body=f"نسبت به تصویر قبلی، میانگین این قطعه‌ها دست‌کم {fa(m.drop_pct)}٪ کم شده: {shown}{more}.",
                url=reverse("databases:explore_table", args=[m.database_id, zonal_service.SCHEMA, m.table_name]), action="مشاهده جدول")
        m.last_alert_at = timezone.now()
        fields.append("last_alert_at")
    m.save(update_fields=fields)


def summary(db: UserDatabase) -> list[dict]:
    return list(SatMonitor.objects.filter(database=db).annotate(n=Count("runs")).values("pk", "name", "n"))
