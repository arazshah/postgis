"""منطق دریافت تصویر ماهواره‌ای: سهمیه، شفافیت دلیل محدودیت، سفارش، ورود به رستر و پیگیری."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from databases.models import Plan, UserDatabase
from enterprise import services as ent
from enterprise.models import Raster
from jobs.models import Job
from satgate import spec

from . import client
from .models import SatRequest

PERIOD = timedelta(days=30)
SEARCH_MAX_KM2 = 20_000
SEARCH_MAX_DAYS = 400
MAX_ACTIVE = 2          # هم‌زمان برای هر پایگاه داده
SCENE_RE = re.compile(r"^[A-Za-z0-9_\-]{5,100}$")
MB = 1024 * 1024
ATTRIBUTION = {
    "sentinel-2-l2a": "Contains modified Copernicus Sentinel data (ESA)",
    "landsat-c2-l2": "Landsat-8/9 Collection 2 Level-2 image courtesy of the U.S. Geological Survey",
    "cop-dem-glo-30": "Copernicus DEM GLO-30 © DLR e.V. / Airbus Defence and Space, provided under COPERNICUS by the EU and ESA",
}


class SatError(Exception):
    def __init__(self, message: str, code: str = "error", extra: dict | None = None):
        super().__init__(message)
        self.code, self.extra = code, extra or {}


def fa(n) -> str:
    return str(f"{n:,}" if isinstance(n, int) else n).translate(str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫"))


def fmt_size(num: float) -> str:
    for unit, div in (("گیگابایت", 1024 ** 3), ("مگابایت", MB), ("کیلوبایت", 1024)):
        if num >= div:
            return f"{fa(round(num / div, 1))} {unit}"
    return f"{fa(int(num))} بایت"


# ---------------------------------------------------------------------- سهمیه
def credits(db: UserDatabase) -> dict:
    cap = db.plan.sat_credits if db.plan_id else 0
    since = timezone.now() - PERIOD
    qs = SatRequest.objects.filter(database=db, charged=True, created_at__gte=since).order_by("created_at")
    used = qs.count()
    first = qs.first()
    return {"cap": cap, "used": used, "left": max(cap - used, 0),
            "resets_at": (first.created_at + PERIOD) if first and used >= cap else None}


def space(db: UserDatabase) -> dict:
    cap = (db.plan.raster_mb if db.plan_id else 0) * MB
    used = ent.raster_used(db)
    return {"cap": cap, "used": used, "left": max(cap - used, 0)}


def status(db: UserDatabase) -> dict:
    return {"credits": credits(db), "space": space(db), "max_km2": db.plan.sat_max_km2 if db.plan_id else 0}


def plan_hint(db: UserDatabase, km2: float, est: int, need_credit: bool) -> dict | None:
    """ارزان‌ترین پلن عمومی که این درخواست در آن جا می‌شود؛ برای نمایش «چه چیزی با ارتقا عوض می‌شود»."""
    cr, sp = credits(db), space(db)
    for p in Plan.objects.filter(is_public=True).exclude(pk=db.plan_id).order_by("price_toman", "order"):
        if (p.sat_max_km2 >= km2 and p.raster_mb * MB - sp["used"] >= est and p.sat_credits > cr["used"]
                and p.sat_credits >= (1 if need_credit else 0)):
            return {"name": p.name, "price_toman": p.price_toman, "raster_mb": p.raster_mb, "sat_credits": p.sat_credits,
                    "sat_max_km2": p.sat_max_km2}
    return None


def _mission(product: str, mission) -> str:
    """ماهواره‌ی معتبر؛ DEM مستقل از ماهواره است."""
    if product == "dem":
        return spec.DEM_MISSION
    mission = str(mission or "sentinel2")
    if mission not in spec.MISSIONS:
        raise SatError("ماهواره‌ی انتخاب‌شده را نمی‌شناسیم.", "mission")
    return mission


def quote(db: UserDatabase, bbox, product: str, mission: str = "sentinel2") -> dict:
    """برآورد حجم و بررسی همه‌ی محدودیت‌ها؛ هر مانع دلیل فارسی و راه‌حل دارد (نه فقط دکمه‌ی غیرفعال)."""
    if not isinstance(product, str) or spec.get_product(spec.DEM_MISSION if product == "dem" else "sentinel2", product) is None:
        raise SatError("محصول انتخاب‌شده را نمی‌شناسیم.", "product")
    mission = _mission(product, mission)
    if not spec.valid_bbox(bbox):
        raise SatError("محدوده نامعتبر است؛ دوباره روی نقشه بکشید.", "bbox")
    bbox = [round(float(v), 5) for v in bbox]
    km2, est = spec.area_km2(bbox), spec.estimate_bytes(bbox, product, mission)
    st = status(db)
    cap_km2, blockers = st["max_km2"], []
    if db.status != UserDatabase.Status.ACTIVE:
        blockers.append({"code": "inactive", "message": "پایگاه داده فعال نیست؛ اول آن را فعال یا تمدید کنید.", "fix": []})
    if not st["credits"]["cap"] or not st["space"]["cap"]:
        blockers.append({"code": "no_service", "message": "این سرویس در پلن فعلی شما فعال نیست.", "fix": ["upgrade"]})
    else:
        if km2 > cap_km2:
            blockers.append({"code": "area", "fix": ["shrink", "upgrade"], "shrink_km2": cap_km2,
                             "message": f"مساحت محدوده {fa(round(km2))} کیلومتر مربع است و سقف پلن شما {fa(cap_km2)} کیلومتر مربع."})
        if est > st["space"]["left"]:
            blockers.append({"code": "space", "fix": ["shrink", "product", "free", "upgrade"],
                             "message": f"این تصویر حدود {fmt_size(est)} می‌شود و فقط {fmt_size(st['space']['left'])} از "
                                        f"{fmt_size(st['space']['cap'])} فضای رستر شما خالی است."})
        if st["credits"]["left"] <= 0:
            when = st["credits"]["resets_at"]
            blockers.append({"code": "credits", "fix": ["wait", "upgrade"],
                             "message": f"اعتبار دریافت تصویر این ماه ({fa(st['credits']['cap'])} بار) تمام شده است."
                                        + (f" اعتبار از {fa((when - timezone.now()).days + 1)} روز دیگر آزاد می‌شود." if when else "")})
    out = {"bbox": bbox, "area_km2": round(km2, 1), "est_bytes": est, "est_text": fmt_size(est), "status": st,
           "blockers": blockers, "ok": not blockers}
    if any(b["fix"] and "upgrade" in b["fix"] for b in blockers):
        out["upgrade"] = plan_hint(db, km2, est, st["credits"]["left"] <= 0)
        out["current"] = {"name": db.plan.name, "raster_mb": db.plan.raster_mb, "sat_credits": db.plan.sat_credits,
                          "sat_max_km2": db.plan.sat_max_km2}
    return out


# ---------------------------------------------------------------------- جست‌وجو
def search(db: UserDatabase, user, data: dict) -> list[dict]:
    if not client.configured():
        raise SatError("سرویس تصویر ماهواره‌ای هنوز راه‌اندازی نشده است.", "off")
    bbox = data.get("bbox")
    if not spec.valid_bbox(bbox) or spec.area_km2(bbox) > SEARCH_MAX_KM2:
        raise SatError("محدوده نامعتبر یا بیش از اندازه بزرگ است.", "bbox")
    try:
        start = date.fromisoformat(str(data.get("start", ""))[:10])
        end = date.fromisoformat(str(data.get("end", ""))[:10])
    except ValueError as exc:
        raise SatError("بازه‌ی تاریخ نامعتبر است.", "dates") from exc
    today = timezone.localdate()
    end = min(end, today)
    if start > end or (end - start).days > SEARCH_MAX_DAYS:
        raise SatError(f"بازه‌ی تاریخ باید بین یک روز تا {fa(SEARCH_MAX_DAYS)} روز باشد.", "dates")
    try:
        cloud = min(max(float(data.get("max_cloud", 30)), 0), 100)
    except (TypeError, ValueError) as exc:
        raise SatError("درصد ابر نامعتبر است.", "cloud") from exc
    mission = _mission("imagery", data.get("mission"))
    key = f"satsearch:{user.pk}"
    n = cache.get(key, 0)
    if n >= 40:
        raise SatError("جست‌وجوهای پشت‌سرهم زیاد بود؛ چند دقیقه صبر کنید.", "rate")
    cache.set(key, n + 1, 600)
    try:
        res = client.call("POST", "/v1/search", {"bbox": bbox, "start": start.isoformat(), "end": end.isoformat(),
                                                 "max_cloud": cloud, "limit": 24, "mission": mission})
    except client.GatewayError as exc:
        raise SatError(str(exc), "gateway") from exc
    return res.get("scenes", [])


# ---------------------------------------------------------------------- سفارش
COMPOSITE_MAX_SCENES = 6


def _composite(data: dict, p) -> dict | None:
    """پارامترهای ترکیب بی‌ابر (بازه، ابر مجاز، تعداد تصویر) یا None برای تصویر تکی."""
    c = data.get("composite")
    if not c:
        return None
    if not p.needs_scene:
        raise SatError("ترکیب بی‌ابر برای ارتفاع (DEM) معنی ندارد.", "composite")
    try:
        start, end = date.fromisoformat(str(c.get("start"))[:10]), date.fromisoformat(str(c.get("end"))[:10])
        cloud = min(max(float(c.get("max_cloud", 40)), 0), 100)
    except (TypeError, ValueError, AttributeError) as exc:
        raise SatError("بازه‌ی ترکیب نامعتبر است.", "dates") from exc
    end = min(end, timezone.localdate())
    if start > end or (end - start).days > SEARCH_MAX_DAYS:
        raise SatError(f"بازه‌ی ترکیب باید بین یک روز تا {fa(SEARCH_MAX_DAYS)} روز باشد.", "dates")
    return {"start": start.isoformat(), "end": end.isoformat(), "max_cloud": cloud, "max_scenes": COMPOSITE_MAX_SCENES}


def order(db: UserDatabase, user, data: dict) -> SatRequest:
    product = data.get("product")
    mission = _mission(product, data.get("mission"))
    q = quote(db, data.get("bbox"), product, mission)
    p = spec.get_product(mission, product)
    composite = _composite(data, p)
    mask = bool(data.get("mask")) and p.needs_scene
    scene = str(data.get("scene") or "").strip()
    if composite:
        mask = bool(data.get("mask", True))
        scene = ""
    elif p.needs_scene and not SCENE_RE.match(scene):
        raise SatError("اول یکی از تصویرها را انتخاب کنید یا «ترکیب بی‌ابر» را بزنید.", "scene")
    if not client.configured():
        raise SatError("سرویس تصویر ماهواره‌ای هنوز راه‌اندازی نشده است.", "off")
    with transaction.atomic():
        UserDatabase.objects.select_for_update().filter(pk=db.pk).first()  # جلوی مصرف هم‌زمان بیش از اعتبار
        q = quote(db, q["bbox"], product, mission)
        if not q["ok"]:
            b = q["blockers"][0]
            raise SatError(b["message"], b["code"], q)
        if SatRequest.objects.filter(database=db, status__in=[SatRequest.Status.PROCESSING,
                                                              SatRequest.Status.DOWNLOADING]).count() >= MAX_ACTIVE:
            raise SatError(f"حداکثر {fa(MAX_ACTIVE)} دریافت هم‌زمان ممکن است؛ تا تمام شدن قبلی‌ها صبر کنید.", "busy")
        req = SatRequest.objects.create(
            database=db, user=user, mission=mission, product=product, mask=mask, composite=composite,
            scene_id=("composite:" + mission) if composite else (scene if p.needs_scene else p.collection),
            scene_date=(composite["end"] if composite else str(data.get("scene_date") or "")[:25]), cloud=_num(data.get("cloud")), bbox=q["bbox"],
            area_km2=q["area_km2"], est_bytes=q["est_bytes"])
    try:
        client.call("POST", "/v1/jobs", {"id": req.token, "product": product, "mission": mission, "scene": scene, "bbox": q["bbox"],
                                         "mask": mask, "composite": composite,
                                         "max_km2": db.plan.sat_max_km2})
    except client.GatewayError as exc:
        _fail(req, str(exc))
        raise SatError(str(exc), "gateway") from exc
    return req


def _num(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def _fail(req: SatRequest, message: str, refund: bool = True) -> None:
    """ناموفق شدن: اعتبار برمی‌گردد و دلیل برای کاربر می‌ماند."""
    req.status, req.message = SatRequest.Status.FAILED, message[:500]
    req.finished_at = timezone.now()
    if refund:
        req.charged = False
    req.save(update_fields=["status", "message", "finished_at", "charged", "updated_at"])


# ---------------------------------------------------------------------- پاسخ دروازه (هوک یا پرس‌وجو)
def on_remote(payload: dict) -> bool:
    """وضعیت کار روی دروازه را اعمال می‌کند؛ تکراری بودن پیام بی‌ضرر است."""
    with transaction.atomic():
        req = SatRequest.objects.select_for_update().filter(token=str(payload.get("id", ""))).first()
        if req is None:
            return False
        if req.status != SatRequest.Status.PROCESSING:
            return True
        if payload.get("status") == "ready":
            req.status = SatRequest.Status.DOWNLOADING
            req.remote = {"size": int(payload.get("size") or 0), "sha256": str(payload.get("sha256") or ""),
                          "used": payload.get("used"), "of": payload.get("of")}
            req.save(update_fields=["status", "remote", "updated_at"])
            Job.objects.create(kind=Job.Kind.SATELLITE, database=req.database, user=req.user, trigger=Job.Trigger.SYSTEM,
                               status=Job.Status.QUEUED, params={"request": req.pk})
        elif payload.get("status") == "failed":
            _fail(req, str(payload.get("message") or "پردازش روی دروازه ناموفق بود."))
    return True


def poll(now: datetime | None = None) -> int:
    """اگر هوک نرسید، وضعیت کارهای باز را از دروازه می‌پرسد؛ کار بسیار کهنه ناموفق می‌شود."""
    if not client.configured():
        return 0
    now = now or timezone.now()
    n = 0
    for req in SatRequest.objects.filter(status=SatRequest.Status.PROCESSING, updated_at__lt=now - timedelta(seconds=45)):
        n += 1
        if now - req.created_at > timedelta(minutes=settings.SATGATE_JOB_TIMEOUT_MIN):
            _fail(req, "پردازش بیش از حد طول کشید و لغو شد؛ اعتبار شما برگردانده شد.")
            _forget(req)
            continue
        try:
            on_remote(client.call("GET", f"/v1/jobs/{req.token}"))
        except client.GatewayError as exc:
            if exc.status == 404:
                _fail(req, "کار روی دروازه پیدا نشد؛ دوباره درخواست بدهید. اعتبار شما برگردانده شد.")
            else:
                SatRequest.objects.filter(pk=req.pk).update(updated_at=now)  # بار بعد دوباره می‌پرسیم
    stale = SatRequest.objects.filter(status=SatRequest.Status.DOWNLOADING, updated_at__lt=now - timedelta(hours=3))
    for req in stale:
        _fail(req, "دریافت فایل کامل نشد؛ دوباره درخواست بدهید. اعتبار شما برگردانده شد.")
    return n + stale.count()


def _forget(req: SatRequest) -> None:
    try:
        client.call("DELETE", f"/v1/jobs/{req.token}")
    except client.GatewayError:
        pass


# ---------------------------------------------------------------------- ورود به رستر (worker)
def ingest(job: Job) -> str:
    req = SatRequest.objects.select_related("database__plan").get(pk=job.params["request"])
    db, p = req.database, req.spec
    size = int(req.remote.get("size") or 0)
    sp = space(db)
    if size > sp["left"]:
        _fail(req, f"فضای رستر پلن برای این فایل ({fmt_size(size)}) کافی نیست؛ اعتبار شما برگردانده شد.")
        _forget(req)
        raise ent.EnterpriseError("فضای رستر کافی نیست.")
    raster = Raster.objects.create(
        database=db, title=req.title[:120], original_name=f"{req.product}.tif", created_by=req.user,
        meta={"source": {"sentinel-2-l2a": "sentinel-2", "landsat-c2-l2": "landsat"}.get(p.collection, "copernicus-dem"),
              "mission": req.mission, "product": req.product, "mask": req.mask, "composite": req.composite,
              "used": (req.remote or {}).get("used"),
              "scene": req.scene_id, "datetime": req.scene_date, "cloud": req.cloud, "bbox": req.bbox,
              "attribution": ATTRIBUTION[p.collection]})
    try:
        dest = ent.raster_upload_path(raster)
        dest.parent.mkdir(parents=True, exist_ok=True)
        client.download(req.token, dest, size, str(req.remote.get("sha256") or ""), settings.RASTER_MAX_MB * MB)
        ent.process_raster(SimpleNamespace(params={"raster": raster.pk}))
        raster.refresh_from_db()
        _apply_defaults(raster, p)
    except (client.GatewayError, ent.EnterpriseError) as exc:
        Raster.objects.filter(pk=raster.pk).delete()
        _fail(req, str(exc))
        raise
    except Exception:
        Raster.objects.filter(pk=raster.pk).delete()
        _fail(req, "آماده‌سازی تصویر ناموفق بود؛ اعتبار شما برگردانده شد.")
        raise
    req.raster, req.status, req.message, req.finished_at = raster, SatRequest.Status.READY, "", timezone.now()
    req.save(update_fields=["raster", "status", "message", "finished_at", "updated_at"])
    _forget(req)
    return f"تصویر «{req.title}» آماده شد ({fmt_size(raster.size_bytes)})."


def _apply_defaults(raster: Raster, p: spec.Product) -> None:
    raster.colormap, raster.rgb = p.colormap if p.colormap != "gray" else raster.colormap, p.rgb and raster.bands >= 3
    if p.key == "ndvi":
        raster.stats = [[-0.1, 0.9]]
    raster.save(update_fields=["colormap", "rgb", "stats"])


def delete_request(req: SatRequest) -> None:
    if req.raster_id:
        ent.delete_raster(req.raster)
    req.delete()


# ---------------------------------------------------------------------- ماهواره‌های در دسترس
def missions(force: bool = False) -> list[dict]:
    """فهرست ماهواره‌ها با وضعیت «در دسترس»؛ فقط آن‌هایی که دروازه واقعاً به‌شان می‌رسد فعال‌اند.
    Sentinel-2 همیشه پیش‌فرض است؛ دروازه‌ی قدیمی بدون /v1/missions فقط Sentinel-2 را می‌دهد."""
    key = "satmissions"
    live = None if force else cache.get(key)
    if live is None:
        try:
            live = client.call("GET", "/v1/missions" + ("?refresh=1" if force else ""), timeout=60).get("missions", {})
        except client.GatewayError as exc:
            live = {"_error": str(exc)} if exc.status != 404 else {}
        cache.set(key, live, 300)
    out = []
    for m in spec.MISSIONS.values():
        st = live.get(m.key)
        known = m.key == "sentinel2" and not isinstance(st, dict)
        ok = bool(st.get("ok")) if isinstance(st, dict) else known
        out.append({"key": m.key, "title": m.title, "agency": m.agency, "res": m.res_m, "revisit": m.revisit,
                    "since": m.since, "hint": m.hint, "available": ok,
                    "error": "" if ok else (st or {}).get("error", "") if isinstance(st, dict) else live.get("_error", "")})
    return out
