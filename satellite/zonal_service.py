"""آمار هر ناحیه و سری زمانی: خواندن چندضلعی‌ها از پایگاه کاربر، ارسال به دروازه (یا اجرای محلی روی رستر موجود)،
و نوشتن جدول نتیجه در پایگاه داده‌ی خود کاربر. چیز سنگینی روی سرور ایران اجرا نمی‌شود."""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta

import psycopg
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from psycopg import sql

from databases.models import UserDatabase
from databases.provisioner import Provisioner
from enterprise.models import Raster
from jobs.models import Job
from kernel import tenantdb
from kernel.tenantdb import TenantError
from satgate import spec
from satgate import zonal as zl

from . import client, router
from .models import SatAnalysis
from .services import SatError, fa, fmt_size  # noqa: F401

PERIOD = timedelta(days=30)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
SCHEMA = "public"
MAX_ACTIVE = 2
DEFAULT_SCENES = 12
MAX_RESULT_BYTES = 8 * 1024 * 1024


# ---------------------------------------------------------------------- سهمیه
def credits(db: UserDatabase) -> dict:
    cap = db.plan.sat_analysis_credits if db.plan_id else 0
    since = timezone.now() - PERIOD
    qs = SatAnalysis.objects.filter(database=db, charged=True, created_at__gte=since).order_by("created_at")
    used = qs.count()
    first = qs.first()
    return {"cap": cap, "used": used, "left": max(cap - used, 0),
            "resets_at": (first.created_at + PERIOD) if first and used >= cap else None}


# ---------------------------------------------------------------------- لایه‌ها و ستون‌ها
def polygon_layers(db: UserDatabase) -> list[dict]:
    """جدول‌های چندضلعی با ستون‌هایشان برای انتخاب لایه و ستون شناسه."""
    ex = tenantdb.catalog(db)
    out = []
    for t in ex.tables():
        if t.geo_kind != "polygon" or t.kind not in ("r", "p", "v", "m"):
            continue
        cols = ex.columns(t)
        ids = [c["name"] for c in cols if not c["spatial"] and c["base"] in ("int2", "int4", "int8", "text", "varchar", "uuid", "bpchar")]
        pk = next((c["name"] for c in cols if c["pk"]), None)
        out.append({"name": t.qualified if t.schema != SCHEMA else t.name, "rows": t.rows_estimate, "srid": t.srid,
                    "columns": ids, "id_default": pk or (ids[0] if ids else "")})
    return out


def _split(layer: str) -> tuple[str, str]:
    schema, _, name = layer.rpartition(".")
    return schema or SCHEMA, name


def read_features(db: UserDatabase, layer: str, id_col: str) -> tuple[list[dict], list[float], float]:
    """چندضلعی‌ها به GeoJSON (WGS84، ساده‌شده)؛ خروجی: (عارضه‌ها، محدوده، مساحت محدوده به کیلومتر مربع)."""
    ex = tenantdb.catalog(db)
    try:
        t = ex.find(*_split(layer))
        cols = {c["name"]: c for c in ex.columns(t)}
        if not t.geometry or t.geo_kind != "polygon":
            raise SatError("این لایه چندضلعی نیست؛ آمار هر ناحیه فقط روی چندضلعی ممکن است.", "layer")
        if id_col not in cols or cols[id_col]["spatial"]:
            raise SatError("ستون شناسه نامعتبر است.", "id")
        g = t.geometry[0]
        gcol = sql.Identifier(g["column"])
        geom = sql.SQL("{}::geometry").format(gcol)
        if (g.get("srid") or 0) not in (0, 4326):
            geom = sql.SQL("ST_Transform({}, 4326)").format(geom)
        elif not g.get("srid"):
            raise SatError("سیستم مختصات این لایه مشخص نیست.", "srid")
        with ex.connect() as conn:
            conn.execute("SET statement_timeout = 30000")
            rows = conn.execute(sql.SQL(
                "SELECT {i}::text, ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_CollectionExtract(ST_MakeValid({g}), 3), 0.00004), 6) "
                "FROM {s}.{t} WHERE {raw} IS NOT NULL AND NOT ST_IsEmpty({raw}::geometry) LIMIT {n}").format(
                    i=sql.Identifier(id_col), g=geom, s=sql.Identifier(t.schema), t=sql.Identifier(t.name), raw=gcol,
                    n=sql.Literal(zl.MAX_FEATURES + 1))).fetchall()
    except (TenantError, psycopg.Error) as exc:
        raise SatError("لایه خوانده نشد؛ نام لایه و ستون شناسه را بررسی کنید.", "layer") from exc
    feats = []
    for fid, gj in rows:
        if not gj:
            continue
        geo = json.loads(gj)
        if geo.get("type") in ("Polygon", "MultiPolygon") and geo.get("coordinates"):
            feats.append({"id": fid, "geometry": geo})
    if not feats:
        raise SatError("این لایه عارضه‌ی چندضلعی معتبر ندارد.", "layer")
    if len(feats) > zl.MAX_FEATURES:
        raise SatError(f"حداکثر {fa(zl.MAX_FEATURES)} عارضه در هر تحلیل ممکن است؛ لایه را با فیلتر کوچک‌تر کنید.", "features")
    if len({f["id"] for f in feats}) != len(feats):
        raise SatError("ستون شناسه یکتا نیست؛ ستونی را انتخاب کنید که برای هر عارضه فرق دارد.", "id")
    bbox = zl.bbox_of(feats)
    return feats, bbox, spec.area_km2(bbox)


def _exists(db: UserDatabase, name: str) -> bool:
    ex = tenantdb.catalog(db)
    with ex.connect() as conn:
        return bool(conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.{name}",)).fetchone()[0])


def default_name(index: str, layer: str) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", _split(layer)[1].lower()).strip("_") or "layer"
    base = re.sub(r"_+", "_", base)
    return f"{index}_{base}"[:36]


def _params(data: dict) -> dict:
    index = str(data.get("index") or "ndvi")
    if index not in spec.INDICES:
        raise SatError("شاخص را نمی‌شناسیم.", "index")
    source = data.get("source") or "satellite"
    if source not in ("satellite", "raster"):
        raise SatError("منبع نامعتبر است.", "source")
    mission = str(data.get("mission") or "sentinel2")
    if source == "satellite" and mission not in spec.MISSIONS:
        raise SatError("ماهواره‌ی انتخاب‌شده را نمی‌شناسیم.", "mission")
    name = str(data.get("name") or "").strip().lower()
    out = {"layer": str(data.get("layer") or "").strip(), "id_column": str(data.get("id_column") or "").strip(),
           "index": index, "source": source, "mission": mission, "name": name,
           "mask": bool(data.get("mask", True)), "raster_id": data.get("raster_id")}
    if not out["layer"] or not out["id_column"]:
        raise SatError("لایه و ستون شناسه را انتخاب کنید.", "layer")
    if source == "satellite":
        try:
            start, end = date.fromisoformat(str(data.get("start"))[:10]), date.fromisoformat(str(data.get("end"))[:10])
            out["max_cloud"] = min(max(float(data.get("max_cloud", 40)), 0), 100)
        except (TypeError, ValueError) as exc:
            raise SatError("بازه‌ی تاریخ نامعتبر است.", "dates") from exc
        end = min(end, timezone.localdate())
        if start > end or (end - start).days > 400:
            raise SatError("بازه‌ی تاریخ باید بین یک روز تا ۴۰۰ روز باشد.", "dates")
        out["start"], out["end"] = start, end
    return out


def quote(db: UserDatabase, data: dict) -> dict:
    """بررسی همه‌ی محدودیت‌ها با دلیل و راه‌حل؛ همان قالب quote تصویر."""
    p = _params(data)
    feats, bbox, km2 = read_features(db, p["layer"], p["id_column"])
    p["name"] = p["name"] or default_name(p["index"], p["layer"])
    blockers = []
    if db.status != UserDatabase.Status.ACTIVE:
        blockers.append({"code": "inactive", "message": "پایگاه داده فعال نیست.", "fix": []})
    if not NAME_RE.match(p["name"]):
        blockers.append({"code": "name", "message": "نام جدول نتیجه باید با حرف انگلیسی کوچک شروع شود و فقط حرف، عدد و _ داشته باشد "
                                                    "(۳ تا ۳۹ نویسه).", "fix": ["rename"]})
    elif _exists(db, p["name"]) or _exists(db, p["name"] + "_latest"):
        blockers.append({"code": "exists", "message": f"جدولی به نام {p['name']} از قبل هست؛ نام دیگری بدهید.", "fix": ["rename"]})
    cr = credits(db)
    out = {"features": len(feats), "area_km2": round(km2, 2), "name": p["name"], "credits": cr, "source": p["source"]}
    if p["source"] == "satellite":
        cap_km2 = db.plan.sat_max_km2 if db.plan_id else 0
        if not cr["cap"]:
            blockers.append({"code": "no_service", "message": "تحلیل ماهواره‌ای در پلن فعلی شما فعال نیست.", "fix": ["upgrade"]})
        elif cr["left"] <= 0:
            when = cr["resets_at"]
            blockers.append({"code": "credits", "fix": ["wait", "upgrade", "raster"],
                             "message": f"اعتبار تحلیل این ماه ({fa(cr['cap'])} بار) تمام شده است."
                                        + (f" از {fa((when - timezone.now()).days + 1)} روز دیگر آزاد می‌شود." if when else "")})
        if km2 > cap_km2 > 0:
            blockers.append({"code": "area", "fix": ["filter", "upgrade"], "shrink_km2": cap_km2,
                             "message": f"محدوده‌ی همه‌ی عارضه‌ها {fa(round(km2))} کیلومتر مربع است و سقف پلن شما {fa(cap_km2)} کیلومتر مربع."})
        out["plan_max_km2"] = cap_km2
    else:
        r = _raster_for(db, p["raster_id"])
        ok, why = router.local_ok()
        if not ok:
            blockers.append({"code": "busy", "message": why, "fix": ["wait"]})
        elif r.width * r.height * max(r.bands, 1) > settings.SAT_LOCAL_MAX_PIXELS * 25:
            blockers.append({"code": "big", "message": "این رستر برای محاسبه روی سرور بزرگ است؛ از تصویر ماهواره‌ای (دروازه) استفاده کنید.",
                             "fix": ["satellite"]})
    out["blockers"], out["ok"] = blockers, not blockers
    return out


def _raster_for(db: UserDatabase, rid) -> Raster:
    r = Raster.objects.filter(pk=rid or 0, database=db, status=Raster.Status.READY).first()
    if r is None:
        raise SatError("رستر انتخاب‌شده پیدا نشد یا آماده نیست.", "raster")
    return r


# ---------------------------------------------------------------------- سفارش
def order(db: UserDatabase, user, data: dict) -> SatAnalysis:
    p = _params(data)
    q = quote(db, data)
    if not q["ok"]:
        b = q["blockers"][0]
        raise SatError(b["message"], b["code"], q)
    feats, bbox, km2 = read_features(db, p["layer"], p["id_column"])
    with transaction.atomic():
        UserDatabase.objects.select_for_update().filter(pk=db.pk).first()
        if p["source"] == "satellite" and credits(db)["left"] <= 0:
            raise SatError("اعتبار تحلیل این ماه تمام شده است.", "credits", q)
        if SatAnalysis.objects.filter(database=db, status__in=[SatAnalysis.Status.PROCESSING,
                                                               SatAnalysis.Status.DOWNLOADING]).count() >= MAX_ACTIVE:
            raise SatError(f"حداکثر {fa(MAX_ACTIVE)} تحلیل هم‌زمان ممکن است؛ تا تمام شدن قبلی‌ها صبر کنید.", "busy", q)
        an = SatAnalysis.objects.create(
            database=db, user=user, name=q["name"], layer=p["layer"], id_column=p["id_column"], source=p["source"],
            mission=p["mission"], index=p["index"], mask=p["mask"], features=len(feats), area_km2=round(km2, 2),
            start=p.get("start"), end=p.get("end"), max_cloud=p.get("max_cloud", 40), charged=p["source"] == "satellite",
            raster=_raster_for(db, p["raster_id"]) if p["source"] == "raster" else None)
        if p["source"] == "raster":
            an.status = SatAnalysis.Status.DOWNLOADING     # محلی: همان لحظه برای worker صف می‌شود
            an.save(update_fields=["status"])
            Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=db, user=user, trigger=Job.Trigger.MANUAL,
                               status=Job.Status.QUEUED, params={"analysis": an.pk, "local": True})
            return an
    try:
        client.call("POST", "/v1/analyze", {
            "id": an.token, "features": feats, "index": p["index"], "mission": p["mission"], "start": p["start"].isoformat(),
            "end": p["end"].isoformat(), "max_cloud": p["max_cloud"], "max_scenes": DEFAULT_SCENES, "mask": p["mask"],
            "max_km2": db.plan.sat_max_km2}, timeout=90)
    except client.GatewayError as exc:
        _fail(an, str(exc))
        raise SatError(str(exc), "gateway") from exc
    return an


def _fail(an: SatAnalysis, message: str, refund: bool = True) -> None:
    an.status, an.message, an.finished_at = SatAnalysis.Status.FAILED, message[:500], timezone.now()
    if refund:
        an.charged = False
    an.save(update_fields=["status", "message", "finished_at", "charged", "updated_at"])
    if an.monitor_id:
        from . import monitor_service
        monitor_service.run_failed(an)


# ---------------------------------------------------------------------- پاسخ دروازه
def on_remote(payload: dict) -> bool | None:
    """پاسخ دروازه برای تحلیل؛ None اگر این شناسه تحلیل نیست."""
    with transaction.atomic():
        an = SatAnalysis.objects.select_for_update().filter(token=str(payload.get("id", ""))).first()
        if an is None:
            return None
        if an.status != SatAnalysis.Status.PROCESSING:
            return True
        if payload.get("status") == "ready":
            an.status = SatAnalysis.Status.DOWNLOADING
            an.remote = {"size": int(payload.get("size") or 0), "sha256": str(payload.get("sha256") or ""),
                         "used": payload.get("used"), "of": payload.get("of"), "rows": payload.get("rows")}
            an.save(update_fields=["status", "remote", "updated_at"])
            Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=an.database, user=an.user, trigger=Job.Trigger.SYSTEM,
                               status=Job.Status.QUEUED, params={"analysis": an.pk})
        elif payload.get("status") == "failed":
            _fail(an, str(payload.get("message") or "محاسبه روی دروازه ناموفق بود."))
    return True


def poll(now: datetime | None = None) -> int:
    now = now or timezone.now()
    n = 0
    for an in SatAnalysis.objects.filter(status=SatAnalysis.Status.PROCESSING, source=SatAnalysis.Source.SATELLITE,
                                         updated_at__lt=now - timedelta(seconds=45)):
        n += 1
        if now - an.created_at > timedelta(minutes=settings.SATGATE_JOB_TIMEOUT_MIN):
            _fail(an, "محاسبه بیش از حد طول کشید و لغو شد؛ اعتبار شما برگردانده شد.")
            continue
        try:
            on_remote(client.call("GET", f"/v1/jobs/{an.token}"))
        except client.GatewayError as exc:
            if exc.status == 404:
                _fail(an, "کار روی دروازه پیدا نشد؛ دوباره درخواست بدهید. اعتبار شما برگردانده شد.")
            else:
                SatAnalysis.objects.filter(pk=an.pk).update(updated_at=now)
    return n


# ---------------------------------------------------------------------- نوشتن جدول نتیجه
COLS = [("feature_id", "text NOT NULL"), ("scene_date", "date NOT NULL"), ("scene", "text NOT NULL"),
        ("mean", "double precision"), ("median", "double precision"), ("min", "double precision"),
        ("max", "double precision"), ("std", "double precision"), ("valid_pct", "real"), ("n_pixels", "integer"),
        ("n_valid", "integer")]


def write_table(an: SatAnalysis, rows: list[dict]) -> None:
    """جدول نتیجه (بلند: یک ردیف برای هر عارضه و تاریخ) و نمای «آخرین مقدار» با هندسه‌ی لایه در پایگاه داده‌ی کاربر."""
    db = an.database
    ex = tenantdb.catalog(db)
    tbl, view = sql.Identifier(SCHEMA, an.name), sql.Identifier(SCHEMA, an.name + "_latest")
    src_schema, src_name = _split(an.layer)
    try:
        with ex.connect(read_only=False, as_owner=True) as conn:
            conn.execute("SET statement_timeout = 120000")
            have = conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.{an.name}",)).fetchone()[0]
            if have and not an.monitor_id:
                raise SatError(f"جدولی به نام {an.name} از قبل هست.", "exists")
            if not have:
                conn.execute(sql.SQL("CREATE TABLE {} ({}, PRIMARY KEY (feature_id, scene_date, scene))").format(
                    tbl, sql.SQL(", ").join(sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(t)) for c, t in COLS)))
                conn.execute(sql.SQL("CREATE INDEX ON {} (scene_date)").format(tbl))
            with conn.cursor() as cur:
                cur.executemany(
                    sql.SQL("INSERT INTO {} VALUES ({}) ON CONFLICT DO NOTHING").format(
                        tbl, sql.SQL(", ").join([sql.Placeholder()] * len(COLS))),
                    [(r["feature"], r["date"], r["scene"], r.get("mean"), r.get("median"), r.get("min"), r.get("max"),
                      r.get("std"), r.get("valid_pct"), r.get("count"), r.get("valid")) for r in rows])
            if not conn.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.{an.name}_latest",)).fetchone()[0]:
                conn.execute(sql.SQL(
                    "CREATE VIEW {v} AS SELECT s.*, r.scene_date AS sat_date, r.mean AS sat_{idx}, r.valid_pct AS sat_valid_pct "
                    "FROM {src} s JOIN (SELECT DISTINCT ON (feature_id) feature_id, scene_date, mean, valid_pct FROM {t} "
                    "WHERE mean IS NOT NULL ORDER BY feature_id, scene_date DESC) r ON r.feature_id = s.{i}::text").format(
                        v=view, idx=sql.SQL(an.index), src=sql.Identifier(src_schema, src_name), t=tbl,
                        i=sql.Identifier(an.id_column)))
                note = f"{an.index_title} برای {an.layer} (تحلیل ماهواره‌ای)"
                conn.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(tbl, sql.Literal(note)))
            conn.execute(sql.SQL("ANALYZE {}").format(tbl))
            conn.commit()
    except psycopg.Error as exc:
        raise SatError("نوشتن جدول نتیجه در پایگاه داده ممکن نشد؛ فضا یا دسترسی را بررسی کنید.", "write") from exc
    Provisioner.for_server(db.server).reassign_browser_objects(db.db_name, db.role_name)


def _finish(an: SatAnalysis, rows: list[dict], scenes: list[dict], skipped=()) -> str:
    write_table(an, rows)
    if an.monitor_id:
        from . import monitor_service
        monitor_service.after_run(an, rows)
    an.status, an.message, an.rows, an.finished_at = SatAnalysis.Status.READY, "", len(rows), timezone.now()
    an.scenes = [{"date": s["date"], "cloud": s.get("cloud"), "id": s.get("id", "")} for s in scenes]
    if skipped:
        an.message = f"{len(skipped)} تصویر قابل‌محاسبه نبود."
    an.save()
    return f"تحلیل {an.index_title} روی {an.features} عارضه تمام شد ({len(rows)} ردیف در جدول {an.name})."


# ---------------------------------------------------------------------- اجرا در worker
def ingest(job: Job) -> str:
    an = SatAnalysis.objects.select_related("database__plan", "raster").get(pk=job.params["analysis"])
    try:
        if an.source == SatAnalysis.Source.RASTER:
            return _run_local(an)
        data = client.call("GET", f"/v1/jobs/{an.token}/result", timeout=120)
        if len(json.dumps(data)) > MAX_RESULT_BYTES:
            raise SatError("نتیجه بیش از حد بزرگ است.", "big")
        msg = _finish(an, data.get("rows", []), data.get("scenes", []), data.get("skipped", []))
        try:
            client.call("DELETE", f"/v1/jobs/{an.token}")
        except client.GatewayError:
            pass
        return msg
    except (SatError, client.GatewayError) as exc:
        _fail(an, str(exc))
        raise


def _run_local(an: SatAnalysis) -> str:
    """آمار روی رستری که از قبل روی همین سرور هست: سبک، با اولویت کم و سقف پیکسل."""
    router.lower_priority()
    for _ in range(24):          # اگر سرور شلوغ است تا ۲ دقیقه صبر می‌کنیم؛ بعد با اولویت کم ادامه می‌دهیم
        if router.load_ratio() < settings.SAT_LOCAL_MAX_LOAD:
            break
        time.sleep(5)
    feats, bbox, _ = read_features(an.database, an.layer, an.id_column)
    rows, day = _local_rows(an, feats, bbox)
    return _finish(an, rows, [{"date": day, "id": f"raster:{an.raster_id}"}])


def _local_rows(an: SatAnalysis, feats: list[dict], bbox: list[float]) -> tuple[list[dict], str]:
    import numpy as np
    import rasterio
    from rasterio.errors import WindowError
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    r = an.raster
    with rasterio.open(r.path) as ds:
        x0, y0, x1, y1 = transform_bounds("EPSG:4326", ds.crs, *bbox)
        win = from_bounds(x0, y0, x1, y1, transform=ds.transform).round_offsets().round_lengths()
        try:
            win = win.intersection(Window(0, 0, ds.width, ds.height))
        except WindowError:
            win = Window(0, 0, 0, 0)
        if win.width < 1 or win.height < 1:
            raise SatError("عارضه‌ها بیرون از محدوده‌ی این رستر هستند.", "outside")
        if win.width * win.height * ds.count > settings.SAT_LOCAL_MAX_PIXELS:
            raise SatError("محدوده برای محاسبه روی سرور بزرگ است؛ از تصویر ماهواره‌ای (دروازه) استفاده کنید.", "big")
        data = ds.read(window=win, masked=True).astype("float32").filled(np.nan)
        wt, crs, desc = ds.window_transform(win), ds.crs, list(ds.descriptions)
    need = zl.index_bands(an.index)
    if all(b in desc for b in need):                                  # رستر «همه‌ی باندها»: بازتاب ×۱۰۰۰۰
        refl = {b: data[desc.index(b)] / 10000.0 for b in need}
        values = zl.index_array(refl, an.index)
    elif data.shape[0] == 1:                                          # تک‌باند (مثلاً NDVI یا DEM): خود مقدار
        values = data[0]
    else:
        raise SatError("این رستر باندهای لازم برای این شاخص را ندارد؛ رستر «همه‌ی باندها» یا تک‌باند (مثل NDVI) بدهید.", "bands")
    labels = zl.feature_labels(feats, values.shape, wt, crs)
    st = zl.zonal_stats(labels, values, len(feats))
    day = ((r.meta or {}).get("datetime") or r.created_at.isoformat())[:10]
    return zl.rows_for(day, f"raster:{r.slug}", feats, st), day


# ---------------------------------------------------------------------- خواندن نتیجه برای نمودار
def series(an: SatAnalysis, feature: str = "") -> dict:
    """سری زمانی از جدول نتیجه‌ی خود کاربر: میانگین همه‌ی عارضه‌ها (با کمینه و بیشینه) و در صورت انتخاب، یک عارضه."""
    ex = tenantdb.catalog(an.database)
    tbl = sql.Identifier(SCHEMA, an.name)
    with ex.connect() as conn:
        conn.execute("SET statement_timeout = 20000")
        allrows = conn.execute(sql.SQL(
            "SELECT scene_date, avg(mean), min(mean), max(mean), avg(valid_pct), count(*) FROM {} GROUP BY 1 ORDER BY 1").format(tbl)).fetchall()
        feats = [r[0] for r in conn.execute(sql.SQL("SELECT DISTINCT feature_id FROM {} ORDER BY 1 LIMIT 300").format(tbl))]
        one = conn.execute(sql.SQL("SELECT scene_date, mean, valid_pct FROM {} WHERE feature_id = %s ORDER BY 1").format(tbl),
                           (feature,)).fetchall() if feature else []
    f = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
    return {"dates": [r[0].isoformat() for r in allrows], "mean": [f(r[1]) for r in allrows], "min": [f(r[2]) for r in allrows],
            "max": [f(r[3]) for r in allrows], "valid": [f(r[4]) for r in allrows], "features": feats,
            "feature": {"id": feature, "dates": [r[0].isoformat() for r in one], "mean": [f(r[1]) for r in one],
                        "valid": [f(r[2]) for r in one]} if feature else None,
            "title": an.index_title}


