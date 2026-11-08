"""آمار هر ناحیه و سری زمانی: سهمیه با دلیل، سفارش و بازگشت اعتبار، پاسخ دروازه، نوشتن جدول، اجرای محلی روی رستر موجود
با محافظ فشار، رابط‌ها؛ و اجرای واقعی روی PostGIS (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import json
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

import numpy as np
import psycopg
import rasterio
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer, Member, Plan, UserDatabase
from databases.provisioner import Provisioner
from enterprise.models import Raster
from jobs import services as jobs
from jobs.models import Job
from satellite import client, router, services, zonal_service
from satellite.models import SatAnalysis
from satgate import protocol

PG_HOST = os.environ.get("TEST_PG_HOST", "")
SECRET = "s3cret"
GW = override_settings(SATGATE_URL="https://gw.test", SATGATE_SECRET=SECRET)
POLY_N = {"type": "Polygon", "coordinates": [[[51.305, 35.720], [51.335, 35.720], [51.335, 35.728], [51.305, 35.728], [51.305, 35.720]]]}
POLY_S = {"type": "Polygon", "coordinates": [[[51.305, 35.702], [51.335, 35.702], [51.335, 35.710], [51.305, 35.710], [51.305, 35.702]]]}
FEATS = [{"id": "A", "geometry": POLY_N}, {"id": "B", "geometry": POLY_S}]
BBOX = [51.305, 35.702, 51.335, 35.728]
LAYER = dict(layer="parcels", id_column="id", index="ndvi", source="satellite", mission="sentinel2",
             start="2026-08-01", end="2026-11-01", max_cloud=40, mask=True, name="ndvi_parcels")


def make_allbands(path: Path, nir=4000, red=2000) -> Path:
    """رستر «همه‌ی باندها» ساختگی (بازتاب ×۱۰۰۰۰ و توضیح باند = نام منطقی) روی UTM 39N."""
    w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.28, 35.68, 51.36, 35.75)
    names = ["red", "green", "blue", "nir", "swir16", "swir22"]
    vals = {"red": red, "green": 1500, "blue": 1000, "nir": nir, "swir16": 2500, "swir22": 1800}
    width, height = int((e - w) / 30), int((n - s) / 30)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=6, dtype="uint16", crs="EPSG:32639",
                       transform=from_origin(w, n, 30, 30), nodata=0) as d:
        for i, nm in enumerate(names, 1):
            d.write(np.full((height, width), vals[nm], dtype="uint16"), i)
            d.set_band_description(i, nm)
    return path


@GW
class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(RASTER_ROOT=str(self.tmp / "rasters"))
        o.enable()
        self.addCleanup(o.disable)
        self.server = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        self.server.set_admin_password("secret")
        self.server.save()
        self.user = User.objects.create_user("09120000091")
        self.free = Plan.objects.get(slug="free")
        self.db = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.free, label="an", db_name="gp_an",
                                              role_name="gp_an_user", status=UserDatabase.Status.ACTIVE)
        # خواندن لایه و بررسی نام جدول به PostGIS نیاز دارد؛ در آزمون‌های واحد جایگزین می‌شود
        for target, rv in (("satellite.zonal_service.read_features", (FEATS, BBOX, 12.3)), ("satellite.zonal_service._exists", False)):
            m = mock.patch(target, return_value=rv)
            m.start()
            self.addCleanup(m.stop)

    def an(self, **kw) -> SatAnalysis:
        vals = dict(database=self.db, user=self.user, name="ndvi_parcels", layer="parcels", id_column="id", features=2,
                    area_km2=12.3, charged=True, start="2026-08-01", end="2026-11-01")
        vals.update(kw)
        return SatAnalysis.objects.create(**vals)


class QuoteTests(_Base):
    def test_ok_for_satellite(self):
        q = zonal_service.quote(self.db, LAYER)
        self.assertTrue(q["ok"])
        self.assertEqual((q["features"], q["name"], q["credits"]["left"]), (2, "ndvi_parcels", 6))

    def test_default_name_and_bad_name_and_existing_table(self):
        self.assertEqual(zonal_service.default_name("ndwi", "public.My Parcels-1"), "ndwi_my_parcels_1")
        self.assertEqual(zonal_service.quote(self.db, {**LAYER, "name": ""})["name"], "ndvi_parcels")
        bad = zonal_service.quote(self.db, {**LAYER, "name": "1bad name"})
        self.assertEqual(bad["blockers"][0]["code"], "name")
        with mock.patch("satellite.zonal_service._exists", return_value=True):
            ex = zonal_service.quote(self.db, LAYER)
        self.assertEqual(ex["blockers"][0]["code"], "exists")
        self.assertIn("ndvi_parcels", ex["blockers"][0]["message"])

    def test_credits_blocker_explains_and_refund_does_not_count(self):
        for _ in range(6):
            self.an()
        q = zonal_service.quote(self.db, LAYER)
        b = next(b for b in q["blockers"] if b["code"] == "credits")
        self.assertIn("تمام شده", b["message"])
        self.assertIn("raster", b["fix"])
        SatAnalysis.objects.update(charged=False)
        self.assertEqual(zonal_service.credits(self.db)["used"], 0)

    def test_area_blocker_uses_plan_cap(self):
        with mock.patch("satellite.zonal_service.read_features", return_value=(FEATS, BBOX, 450.0)):
            q = zonal_service.quote(self.db, LAYER)
        b = next(b for b in q["blockers"] if b["code"] == "area")
        self.assertIn("۱۰۰", b["message"])
        self.assertIn("۴۵۰", b["message"])

    def test_no_service_plan_and_bad_params(self):
        self.free.sat_analysis_credits = 0
        self.free.save()
        self.assertEqual(zonal_service.quote(self.db, LAYER)["blockers"][0]["code"], "no_service")
        for bad in ({"index": "nope"}, {"source": "x"}, {"mission": "nope"}, {"layer": ""}, {"start": "x"},
                    {"start": "2020-01-01"}):
            with self.assertRaises(services.SatError, msg=str(bad)):
                zonal_service.quote(self.db, {**LAYER, **bad})

    def test_raster_source_gated_by_server_load(self):
        r = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY, width=100, height=100, bands=6)
        data = {**LAYER, "source": "raster", "raster_id": r.pk}
        with mock.patch("satellite.router.load_ratio", return_value=0.2):
            self.assertTrue(zonal_service.quote(self.db, data)["ok"])
        with mock.patch("satellite.router.load_ratio", return_value=0.95):
            q = zonal_service.quote(self.db, data)
        self.assertEqual(q["blockers"][0]["code"], "busy")
        self.assertIn("مشغول", q["blockers"][0]["message"])
        with self.assertRaises(services.SatError):
            zonal_service.quote(self.db, {**data, "raster_id": 999})


class OrderTests(_Base):
    @mock.patch("satellite.client.call", return_value={"status": "queued"})
    def test_order_sends_features_and_charges(self, call):
        an = zonal_service.order(self.db, self.user, LAYER)
        self.assertEqual((an.status, an.charged, an.features), (SatAnalysis.Status.PROCESSING, True, 2))
        method, path, body = call.call_args.args
        self.assertEqual((method, path), ("POST", "/v1/analyze"))
        self.assertEqual((body["id"], body["index"], body["mission"], body["mask"]), (an.token, "ndvi", "sentinel2", True))
        self.assertEqual([f["id"] for f in body["features"]], ["A", "B"])
        self.assertEqual((body["start"], body["max_km2"]), ("2026-08-01", 100))
        self.assertEqual(zonal_service.credits(self.db)["used"], 1)

    @mock.patch("satellite.client.call", side_effect=client.GatewayError("دروازه‌ی ماهواره موقتاً در دسترس نیست."))
    def test_gateway_down_refunds(self, _):
        with self.assertRaises(services.SatError) as cm:
            zonal_service.order(self.db, self.user, LAYER)
        self.assertEqual(cm.exception.code, "gateway")
        an = SatAnalysis.objects.get()
        self.assertEqual((an.status, an.charged), (SatAnalysis.Status.FAILED, False))
        self.assertEqual(zonal_service.credits(self.db)["used"], 0)

    @mock.patch("satellite.client.call", return_value={})
    def test_at_most_two_at_a_time_and_blocked_orders_do_not_charge(self, _):
        zonal_service.order(self.db, self.user, {**LAYER, "name": "a_one"})
        zonal_service.order(self.db, self.user, {**LAYER, "name": "a_two"})
        with self.assertRaises(services.SatError) as cm:
            zonal_service.order(self.db, self.user, {**LAYER, "name": "a_three"})
        self.assertEqual(cm.exception.code, "busy")
        self.assertEqual(SatAnalysis.objects.count(), 2)

    def test_local_order_queues_job_without_credit_or_gateway(self):
        r = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY, width=100, height=100, bands=6)
        with mock.patch("satellite.router.load_ratio", return_value=0.1), mock.patch("satellite.client.call") as call:
            an = zonal_service.order(self.db, self.user, {**LAYER, "source": "raster", "raster_id": r.pk})
        call.assert_not_called()
        self.assertFalse(an.charged)
        job = Job.objects.get(kind=Job.Kind.SAT_ANALYSIS)
        self.assertEqual(job.params, {"analysis": an.pk, "local": True})
        self.assertEqual(zonal_service.credits(self.db)["used"], 0)


class GatewayReplyTests(_Base):
    def signed(self, payload):
        body = json.dumps(payload).encode()
        h = protocol.sign(SECRET, "POST", "/hooks/satellite/", body)
        return self.client.post("/hooks/satellite/", body, content_type="application/json", HTTP_X_SAT_TIME=h[protocol.H_TIME],
                                HTTP_X_SAT_SIG=h[protocol.H_SIG], HTTP_X_SAT_KID=h[protocol.H_KID])

    def test_hook_ready_queues_ingest_once_and_failed_refunds(self):
        an = self.an()
        p = {"id": an.token, "status": "ready", "size": 900, "sha256": "x", "used": 5, "of": 6, "rows": 10}
        self.assertEqual(self.signed(p).status_code, 204)
        self.assertEqual(self.signed(p).status_code, 204)
        an.refresh_from_db()
        self.assertEqual((an.status, an.remote["used"]), (SatAnalysis.Status.DOWNLOADING, 5))
        self.assertEqual(Job.objects.filter(kind=Job.Kind.SAT_ANALYSIS).count(), 1)
        bad = self.an(name="other")
        self.signed({"id": bad.token, "status": "failed", "message": "تصویری با این شرایط در بازه پیدا نشد."})
        bad.refresh_from_db()
        self.assertEqual((bad.status, bad.charged), (SatAnalysis.Status.FAILED, False))
        self.assertIn("پیدا نشد", bad.message)

    def test_unknown_token_is_404(self):
        self.assertEqual(self.signed({"id": "0" * 32, "status": "ready"}).status_code, 404)

    @mock.patch("satellite.client.call")
    def test_poll_picks_up_missed_hook_and_times_out_old(self, call):
        an = self.an()
        SatAnalysis.objects.filter(pk=an.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        call.return_value = {"id": an.token, "status": "ready", "size": 10, "sha256": "", "used": 3, "of": 3, "rows": 6}
        services.poll()
        an.refresh_from_db()
        self.assertEqual(an.status, SatAnalysis.Status.DOWNLOADING)
        old = self.an(name="old_one")
        t = timezone.now() - timedelta(minutes=90)
        SatAnalysis.objects.filter(pk=old.pk).update(created_at=t, updated_at=t)
        services.poll()
        old.refresh_from_db()
        self.assertEqual((old.status, old.charged), (SatAnalysis.Status.FAILED, False))

    @mock.patch("satellite.zonal_service.write_table")
    @mock.patch("satellite.client.call")
    def test_ingest_writes_table_and_forgets_remote_job(self, call, write):
        an = self.an(status=SatAnalysis.Status.DOWNLOADING)
        rows = [{"feature": "A", "date": "2026-10-01", "scene": "S2A_x", "mean": .4, "count": 10, "valid": 9, "valid_pct": 90.0},
                {"feature": "B", "date": "2026-10-01", "scene": "S2A_x", "mean": .5, "count": 10, "valid": 10, "valid_pct": 100.0}]
        call.side_effect = [{"rows": rows, "scenes": [{"id": "S2A_x", "date": "2026-10-01", "cloud": 3.0}], "skipped": []}, {}]
        job = Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, params={"analysis": an.pk})
        msg = zonal_service.ingest(job)
        an.refresh_from_db()
        self.assertEqual((an.status, an.rows, an.scenes[0]["date"]), (SatAnalysis.Status.READY, 2, "2026-10-01"))
        self.assertIn("2", msg.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        write.assert_called_once()
        self.assertEqual(call.call_args_list[1].args[:2], ("DELETE", f"/v1/jobs/{an.token}"))

    @mock.patch("satellite.zonal_service.write_table", side_effect=services.SatError("نوشتن جدول نتیجه در پایگاه داده ممکن نشد.", "write"))
    @mock.patch("satellite.client.call", return_value={"rows": [], "scenes": []})
    def test_write_failure_refunds_and_worker_reports(self, *_):
        an = self.an(status=SatAnalysis.Status.DOWNLOADING)
        job = Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, status=Job.Status.RUNNING, params={"analysis": an.pk})
        jobs.run(job)
        an.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual((an.status, an.charged, job.status), (SatAnalysis.Status.FAILED, False, Job.Status.FAILED))
        self.assertIn("نوشتن جدول", job.message)


class LocalRasterTests(_Base):
    """اجرای محلی: رستر «همه‌ی باندها» یا تک‌باند؛ سبک و با سقف پیکسل."""

    def raster(self, **kw):
        r = Raster.objects.create(database=self.db, title="تصویر", status=Raster.Status.READY, bands=6, dtype="UInt16",
                                  meta={"datetime": "2026-10-20T07:00:00Z"}, **kw)
        make_allbands(r.path)
        return r

    def run_local(self, an):
        job = Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, params={"analysis": an.pk, "local": True})
        with mock.patch("satellite.zonal_service.write_table") as w, mock.patch("satellite.router.lower_priority"), \
                mock.patch("satellite.router.load_ratio", return_value=0.1):
            msg = zonal_service.ingest(job)
        return msg, w

    def test_ndvi_from_allbands_raster(self):
        an = self.an(source="raster", raster=self.raster(), charged=False, status=SatAnalysis.Status.DOWNLOADING)
        msg, w = self.run_local(an)
        rows = w.call_args.args[1]
        by = {r["feature"]: r for r in rows}
        # بازتاب: NIR .4 و قرمز .2 ← (.4-.2)/.6
        self.assertAlmostEqual(by["A"]["mean"], 1 / 3, places=3)
        self.assertEqual((by["A"]["date"], by["A"]["valid_pct"]), ("2026-10-20", 100.0))
        self.assertGreater(by["A"]["count"], 100)
        an.refresh_from_db()
        self.assertEqual((an.status, an.rows), (SatAnalysis.Status.READY, 2))
        self.assertIn("raster:", an.scenes[0]["id"])

    def test_other_index_and_single_band_raster(self):
        an = self.an(source="raster", raster=self.raster(), index="ndmi", charged=False)
        _, w = self.run_local(an)
        self.assertAlmostEqual(w.call_args.args[1][0]["mean"], (.4 - .25) / (.4 + .25), places=3)
        one = Raster.objects.create(database=self.db, title="ndvi", status=Raster.Status.READY, bands=1, dtype="Float32",
                                    meta={"product": "ndvi"})
        w_, s_, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.28, 35.68, 51.36, 35.75)
        one.path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(one.path, "w", driver="GTiff", width=int((e - w_) / 30), height=int((n - s_) / 30), count=1,
                           dtype="float32", crs="EPSG:32639", transform=from_origin(w_, n, 30, 30)) as d:
            d.write(np.full((int((n - s_) / 30), int((e - w_) / 30)), 0.77, dtype="float32"), 1)
        an2 = self.an(source="raster", raster=one, name="single", charged=False)
        _, w2 = self.run_local(an2)
        self.assertAlmostEqual(w2.call_args.args[1][0]["mean"], 0.77, places=3)

    def test_clear_errors_for_wrong_raster(self):
        # رستر سه‌باندی رنگی (بدون NIR) نمی‌تواند شاخص بدهد
        rgb = Raster.objects.create(database=self.db, title="rgb", status=Raster.Status.READY, bands=3, dtype="Byte")
        w_, s_, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.28, 35.68, 51.36, 35.75)
        rgb.path.parent.mkdir(parents=True, exist_ok=True)
        h, wd = int((n - s_) / 30), int((e - w_) / 30)
        with rasterio.open(rgb.path, "w", driver="GTiff", width=wd, height=h, count=3, dtype="uint8", crs="EPSG:32639",
                           transform=from_origin(w_, n, 30, 30)) as d:
            for i in (1, 2, 3):
                d.write(np.full((h, wd), 100, dtype="uint8"), i)
        an = self.an(source="raster", raster=rgb, charged=False, status=SatAnalysis.Status.DOWNLOADING)
        job = Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, status=Job.Status.RUNNING,
                                 params={"analysis": an.pk, "local": True})
        with mock.patch("satellite.router.lower_priority"), mock.patch("satellite.router.load_ratio", return_value=0.1):
            jobs.run(job)
        an.refresh_from_db()
        self.assertEqual(an.status, SatAnalysis.Status.FAILED)
        self.assertIn("باندهای لازم", an.message)

    def test_pixel_cap_and_outside_raster(self):
        an = self.an(source="raster", raster=self.raster(), charged=False)
        with override_settings(SAT_LOCAL_MAX_PIXELS=500), self.assertRaises(services.SatError) as cm:
            self.run_local(an)
        self.assertEqual(cm.exception.code, "big")
        far = [{"id": "Z", "geometry": {"type": "Polygon", "coordinates": [[[55, 30], [55.01, 30], [55.01, 30.01], [55, 30.01], [55, 30]]]}}]
        with mock.patch("satellite.zonal_service.read_features", return_value=(far, [55, 30, 55.01, 30.01], 1.0)), \
                self.assertRaises(services.SatError) as cm:
            self.run_local(an)
        self.assertEqual(cm.exception.code, "outside")

    def test_waits_for_load_then_runs_niced(self):
        an = self.an(source="raster", raster=self.raster(), charged=False)
        job = Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, params={"analysis": an.pk, "local": True})
        loads = iter([0.95, 0.9, 0.2])
        with mock.patch("satellite.zonal_service.write_table"), mock.patch("satellite.router.lower_priority") as nice, \
                mock.patch("satellite.router.load_ratio", side_effect=lambda: next(loads)), \
                mock.patch("satellite.zonal_service.time.sleep") as sl:
            zonal_service.ingest(job)
        nice.assert_called_once()
        self.assertEqual(sl.call_count, 2)                    # دو بار صبر کرد تا بار پایین آمد


class RouterTests(_Base):
    def test_local_ok_rules(self):
        with mock.patch("satellite.router.load_ratio", return_value=0.3):
            self.assertTrue(router.local_ok()[0])
        with mock.patch("satellite.router.load_ratio", return_value=0.9):
            ok, why = router.local_ok()
        self.assertFalse(ok)
        self.assertIn("مشغول", why)
        for _ in range(2):
            Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, status=Job.Status.QUEUED,
                               params={"analysis": 1, "local": True})
        Job.objects.create(kind=Job.Kind.SAT_ANALYSIS, database=self.db, status=Job.Status.QUEUED, params={"analysis": 2})
        with mock.patch("satellite.router.load_ratio", return_value=0.1):
            ok, why = router.local_ok()
        self.assertEqual((router.local_queue(), ok), (2, False))        # فقط کارهای محلی شمرده می‌شوند
        self.assertIn("در صف", why)
        st = router.status()
        self.assertEqual((st["queued"], st["max_jobs"]), (2, 2))


class ViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def url(self, name, *a):
        return reverse(f"satellite:{name}", args=[self.db.pk, *a])

    def post(self, name, data):
        return self.client.post(self.url(name), json.dumps(data), content_type="application/json")

    def test_page_has_analysis_tab_dialog_and_chart_script(self):
        self.an(status=SatAnalysis.Status.READY, rows=4)
        html = self.client.get(self.url("index")).content.decode()
        for needle in ('id="p-analysis"', 'id="an-dlg"', 'id="an-chart"', "data-an-chart", "satellite-analysis.js",
                       "echarts.min.js", "نمودار روند", "تحلیل تازه"):
            self.assertIn(needle, html)
        self.assertIn("/satellite/analysis/layers/", html)

    def test_layers_endpoint_lists_polygons_rasters_indices(self):
        Raster.objects.create(database=self.db, title="تصویر من", status=Raster.Status.READY, bands=6, dtype="UInt16")
        layers = [{"name": "parcels", "rows": 12, "srid": 4326, "columns": ["id"], "id_default": "id"}]
        with mock.patch("satellite.zonal_service.polygon_layers", return_value=layers):
            j = self.client.get(self.url("an_layers")).json()
        self.assertEqual(j["layers"][0]["name"], "parcels")
        self.assertEqual({i["key"] for i in j["indices"]}, {"ndvi", "ndwi", "ndmi", "nbr", "ndbi"})
        self.assertEqual(j["rasters"][0]["title"], "تصویر من")
        self.assertEqual(j["credits"]["cap"], 6)

    def test_quote_and_order_endpoints(self):
        j = self.post("an_quote", LAYER).json()
        self.assertTrue(j["quote"]["ok"])
        bad = self.post("an_quote", {**LAYER, "index": "nope"})
        self.assertEqual(bad.status_code, 400)
        with mock.patch("satellite.client.call", return_value={}):
            ok = self.post("an_order", LAYER).json()
        self.assertTrue(ok["ok"])
        for i in range(6):
            self.an(name=f"x{i}", status=SatAnalysis.Status.READY)
        blocked = self.post("an_order", {**LAYER, "name": "another"})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("credits", blocked.json()["code"])
        self.assertTrue(blocked.json()["quote"]["blockers"])

    def test_viewer_can_see_but_not_order_or_delete_and_stranger_404(self):
        an = self.an(status=SatAnalysis.Status.READY)
        other = User.objects.create_user("09120000092")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url("an_cards")).status_code, 404)
        Member.objects.create(database=self.db, user=other, role=Member.Role.VIEWER)
        self.assertEqual(self.client.get(self.url("an_cards")).status_code, 200)
        self.assertEqual(self.post("an_order", LAYER).status_code, 404)
        self.client.post(self.url("an_delete", an.pk))
        self.assertTrue(SatAnalysis.objects.filter(pk=an.pk).exists())

    def test_cards_fragment_and_delete(self):
        an = self.an(status=SatAnalysis.Status.READY, rows=8, scenes=[{"date": "2026-10-01"}])
        r = self.client.get(self.url("an_cards"))
        self.assertEqual(r["X-Sat-Active"], "0")
        self.assertContains(r, "ndvi_parcels")
        self.assertContains(r, "نمودار روند")
        self.assertContains(r, "ndvi_parcels_latest")                     # نمای آخرین مقدار
        SatAnalysis.objects.update(status=SatAnalysis.Status.PROCESSING)
        self.assertEqual(self.client.get(self.url("an_cards"))["X-Sat-Active"], "1")
        self.client.post(self.url("an_delete", an.pk))                     # در حال محاسبه حذف نمی‌شود
        self.assertTrue(SatAnalysis.objects.filter(pk=an.pk).exists())
        SatAnalysis.objects.update(status=SatAnalysis.Status.FAILED)
        self.client.post(self.url("an_delete", an.pk))
        self.assertFalse(SatAnalysis.objects.filter(pk=an.pk).exists())

    def test_series_endpoint_uses_users_table(self):
        an = self.an(status=SatAnalysis.Status.READY)
        fake = {"dates": ["2026-10-01"], "mean": [.4], "min": [.3], "max": [.5], "valid": [90.0], "features": ["A", "B"],
                "feature": None, "title": "شاخص گیاهی NDVI"}
        with mock.patch("satellite.zonal_service.series", return_value=fake) as s:
            j = self.client.get(self.url("an_series", an.pk) + "?feature=A").json()
        self.assertTrue(j["ok"])
        self.assertEqual(s.call_args.args[1], "A")
        with mock.patch("satellite.zonal_service.series", side_effect=RuntimeError("no table")):
            r = self.client.get(self.url("an_series", an.pk))
        self.assertEqual(r.status_code, 404)
        pending = self.an(name="p", status=SatAnalysis.Status.PROCESSING)
        self.assertEqual(self.client.get(self.url("an_series", pending.pk)).status_code, 404)


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class PostgisTests(TestCase):
    """خواندن چندضلعی‌ها، نوشتن جدول نتیجه و نمای آخرین مقدار و سری زمانی روی PostGIS واقعی."""

    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000293")
        label = f"sz_{uuid.uuid4().hex[:8]}"
        self.db = db_services.create_database(self.user, label, "Sat-Pass-12", ["postgis"])
        self.addCleanup(self._drop)
        with psycopg.connect(host=server.host, port=server.port, user=self.db.role_name, password="Sat-Pass-12",
                             dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE parcels(pid text PRIMARY KEY, name text, geom geometry(Polygon, 4326))")
            c.execute("INSERT INTO parcels VALUES ('A', 'شمالی', ST_MakeEnvelope(51.305, 35.720, 51.335, 35.728, 4326)), "
                      "('B', 'جنوبی', ST_MakeEnvelope(51.305, 35.702, 51.335, 35.710, 4326))")
            c.execute("CREATE TABLE pts(pid text PRIMARY KEY, geom geometry(Point, 4326))")
            c.execute("INSERT INTO pts VALUES ('P', ST_SetSRID(ST_MakePoint(51.3, 35.7), 4326))")
            c.execute("CREATE TABLE utm(pid int PRIMARY KEY, geom geometry(Polygon, 32639))")
            c.execute("INSERT INTO utm VALUES (1, ST_Transform(ST_MakeEnvelope(51.305, 35.720, 51.335, 35.728, 4326), 32639))")

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def test_layers_features_table_view_and_series(self):
        layers = {x["name"]: x for x in zonal_service.polygon_layers(self.db)}
        self.assertIn("parcels", layers)
        self.assertNotIn("pts", layers)                                       # نقطه چندضلعی نیست
        self.assertEqual(layers["parcels"]["id_default"], "pid")
        feats, bbox, km2 = zonal_service.read_features(self.db, "parcels", "pid")
        self.assertEqual({f["id"] for f in feats}, {"A", "B"})
        self.assertAlmostEqual(bbox[0], 51.305, places=3)
        self.assertGreater(km2, 5)
        utm, _, _ = zonal_service.read_features(self.db, "utm", "pid")        # مختصات UTM به WGS84 تبدیل می‌شود
        self.assertAlmostEqual(utm[0]["geometry"]["coordinates"][0][0][0], 51.305, places=3)
        with self.assertRaises(services.SatError):
            zonal_service.read_features(self.db, "pts", "pid")
        with self.assertRaises(services.SatError):
            zonal_service.read_features(self.db, "parcels", "geom")
        self.assertFalse(zonal_service._exists(self.db, "ndvi_parcels"))
        an = SatAnalysis.objects.create(database=self.db, user=self.user, name="ndvi_parcels", layer="parcels", id_column="pid",
                                        index="ndvi", features=2)
        rows = [{"feature": "A", "date": "2026-09-01", "scene": "S2A_1", "mean": .3, "median": .3, "min": .1, "max": .5, "std": .1,
                 "valid_pct": 80.0, "count": 100, "valid": 80},
                {"feature": "A", "date": "2026-10-01", "scene": "S2A_2", "mean": .5, "median": .5, "min": .2, "max": .7, "std": .1,
                 "valid_pct": 100.0, "count": 100, "valid": 100},
                {"feature": "B", "date": "2026-10-01", "scene": "S2A_2", "mean": .1, "valid_pct": 0.0, "count": 100, "valid": 0}]
        zonal_service.write_table(an, rows)
        self.assertTrue(zonal_service._exists(self.db, "ndvi_parcels"))
        self.assertTrue(zonal_service._exists(self.db, "ndvi_parcels_latest"))
        with self.assertRaises(services.SatError):
            zonal_service.write_table(an, rows)                              # نام تکراری
        with psycopg.connect(host=self.db.server.host, port=self.db.server.port, user=self.db.role_name, password="Sat-Pass-12",
                             dbname=self.db.db_name) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM ndvi_parcels").fetchone()[0], 3)
            latest = {r[0]: r[1] for r in c.execute("SELECT pid, sat_ndvi FROM ndvi_parcels_latest")}
            self.assertEqual(latest, {"A": 0.5, "B": 0.1})                    # آخرین مقدار هر قطعه، هندسه‌ی لایه همراه
            self.assertEqual(c.execute("SELECT count(*) FROM ndvi_parcels_latest WHERE geom IS NOT NULL").fetchone()[0], 2)
        s = zonal_service.series(an, "A")
        self.assertEqual(s["dates"], ["2026-09-01", "2026-10-01"])
        self.assertAlmostEqual(s["mean"][1], 0.3, places=3)                  # میانگین A=.5 و B=.1 در ۱۰/۰۱
        self.assertEqual(s["feature"]["mean"], [.3, .5])
        self.assertEqual(s["features"], ["A", "B"])
