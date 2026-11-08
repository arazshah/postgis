"""تصویر ماهواره‌ای: سهمیه و شفافیت دلیل محدودیت، سفارش و بازگشت اعتبار، هوک امضاشده، ورود به رستر و دانلود COG."""
import json
import shutil
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases.models import DatabaseServer, Member, Plan, UserDatabase
from enterprise import services as ent
from enterprise.models import Raster
from enterprise.tests.test_enterprise import HAS_GDAL, HAS_RIO, make_tif
from jobs import services as jobs
from jobs.models import Job
from satellite import client, probe, services
from satellite.models import SatRequest
from satgate import protocol

BBOX = [51.30, 35.70, 51.34, 35.73]
SECRET = "s3cret"
GW = override_settings(SATGATE_URL="https://gw.test", SATGATE_SECRET=SECRET)


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
        self.user = User.objects.create_user("09120000081")
        self.free = Plan.objects.get(slug="free")
        self.db = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.free, label="sat",
                                              db_name="gp_sat", role_name="gp_sat_user", status=UserDatabase.Status.ACTIVE)

    def plan(self, **kw) -> Plan:
        vals = dict(name="بالاتر", slug=f"p-{uuid.uuid4().hex[:6]}", is_free=False, price_toman=500000, raster_mb=2048,
                    sat_credits=100, sat_max_km2=1000)
        vals.update(kw)
        return Plan.objects.create(**vals)

    def req(self, **kw) -> SatRequest:
        vals = dict(database=self.db, user=self.user, product="ndvi", scene_id="S2A_X_1", bbox=BBOX, area_km2=10,
                    est_bytes=3_000_000, scene_date="2026-06-01T07:00:00Z")
        vals.update(kw)
        return SatRequest.objects.create(**vals)


class PlanDefaultsTests(_Base):
    def test_free_plan_has_satellite_quota(self):
        self.assertGreater(self.free.raster_mb, 0)   # مهاجرت: همه‌ی پلن‌ها فضای رستر دارند
        self.assertEqual((self.free.sat_credits, self.free.sat_max_km2), (10, 100))


class QuoteTests(_Base):
    def test_ok_small_area(self):
        q = services.quote(self.db, BBOX, "true_color")
        self.assertTrue(q["ok"])
        self.assertEqual(q["blockers"], [])
        self.assertGreater(q["est_bytes"], 100_000)
        self.assertEqual(q["status"]["credits"]["left"], 10)

    def test_area_blocker_explains_numbers_and_offers_upgrade(self):
        self.plan(sat_max_km2=2000)
        q = services.quote(self.db, [51.0, 35.5, 51.4, 35.9], "true_color")
        b = q["blockers"][0]
        self.assertEqual(b["code"], "area")
        self.assertIn("۱۰۰", b["message"])
        self.assertIn("upgrade", b["fix"])
        self.assertEqual(q["upgrade"]["sat_max_km2"], 2000)
        self.assertEqual(q["current"]["sat_max_km2"], 100)
        self.assertFalse(q["ok"])

    def test_space_blocker_says_how_much_is_left(self):
        self.free.raster_mb = 1
        self.free.save()
        q = services.quote(self.db, BBOX, "allbands")
        b = next(b for b in q["blockers"] if b["code"] == "space")
        self.assertIn("فضای رستر", b["message"])
        self.assertIn("free", b["fix"])
        self.assertIn("product", b["fix"])

    def test_credits_blocker_and_reset_time(self):
        for _ in range(10):
            self.req()
        q = services.quote(self.db, BBOX, "true_color")
        b = next(b for b in q["blockers"] if b["code"] == "credits")
        self.assertIn("تمام شده", b["message"])
        self.assertIn("روز دیگر", b["message"])
        self.assertEqual(q["status"]["credits"]["left"], 0)

    def test_old_requests_do_not_count_and_refunds_do_not_count(self):
        old = self.req()
        SatRequest.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=31))
        self.req(charged=False)
        self.assertEqual(services.credits(self.db)["used"], 0)

    def test_no_service_plan(self):
        self.free.sat_credits = 0
        self.free.save()
        q = services.quote(self.db, BBOX, "ndvi")
        self.assertEqual(q["blockers"][0]["code"], "no_service")

    def test_bad_input(self):
        for bad in ([1, 2], None, [10, 10, 5, 5]):
            with self.assertRaises(services.SatError):
                services.quote(self.db, bad, "ndvi")
        with self.assertRaises(services.SatError):
            services.quote(self.db, BBOX, "nope")

    def test_inactive_database_blocks(self):
        UserDatabase.objects.filter(pk=self.db.pk).update(status=UserDatabase.Status.EXPIRED)
        self.db.refresh_from_db()
        self.assertEqual(services.quote(self.db, BBOX, "ndvi")["blockers"][0]["code"], "inactive")


class OrderTests(_Base):
    def order(self, **kw):
        data = {"bbox": BBOX, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A", "scene_date": "2026-06-01T07:00:00Z", "cloud": 3.2}
        data.update(kw)
        return services.order(self.db, self.user, data)

    @mock.patch("satellite.client.call", return_value={"status": "queued"})
    def test_order_charges_and_sends_signed_job(self, call):
        r = self.order()
        self.assertEqual(r.status, SatRequest.Status.PROCESSING)
        self.assertTrue(r.charged)
        self.assertEqual(services.credits(self.db)["used"], 1)
        method, path, body = call.call_args.args
        self.assertEqual((method, path), ("POST", "/v1/jobs"))
        self.assertEqual((body["id"], body["product"], body["max_km2"]), (r.token, "ndvi", 100))

    @mock.patch("satellite.client.call", side_effect=client.GatewayError("دروازه‌ی ماهواره موقتاً در دسترس نیست."))
    def test_gateway_down_refunds_immediately(self, _):
        with self.assertRaises(services.SatError) as cm:
            self.order()
        self.assertEqual(cm.exception.code, "gateway")
        r = SatRequest.objects.get()
        self.assertEqual(r.status, SatRequest.Status.FAILED)
        self.assertFalse(r.charged)
        self.assertEqual(services.credits(self.db)["used"], 0)

    @mock.patch("satellite.client.call", return_value={})
    def test_scene_required_except_dem(self, _):
        with self.assertRaises(services.SatError) as cm:
            self.order(scene="")
        self.assertEqual(cm.exception.code, "scene")
        self.assertEqual(self.order(scene="", product="dem").scene_id, "cop-dem-glo-30")

    @mock.patch("satellite.client.call", return_value={})
    def test_limits_enforced_server_side(self, _):
        with self.assertRaises(services.SatError) as cm:
            self.order(bbox=[51.0, 35.5, 51.4, 35.9])
        self.assertEqual(cm.exception.code, "area")
        self.assertFalse(SatRequest.objects.exists())

    @mock.patch("satellite.client.call", return_value={})
    def test_only_two_at_a_time(self, _):
        self.order()
        self.order()
        with self.assertRaises(services.SatError) as cm:
            self.order()
        self.assertEqual(cm.exception.code, "busy")

    def test_not_configured(self):
        with override_settings(SATGATE_URL=""), self.assertRaises(services.SatError) as cm:
            self.order()
        self.assertEqual(cm.exception.code, "off")


class HookAndPollTests(_Base):
    def signed(self, payload, secret=SECRET, path="/hooks/satellite/"):
        body = json.dumps(payload).encode()
        h = protocol.sign(secret, "POST", path, body)
        return self.client.post(path, body, content_type="application/json", HTTP_X_SAT_TIME=h[protocol.H_TIME],
                                HTTP_X_SAT_SIG=h[protocol.H_SIG])

    def test_rejects_unsigned_and_wrong_key(self):
        r = self.req()
        self.assertEqual(self.client.post("/hooks/satellite/", "{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.signed({"id": r.token, "status": "ready"}, secret="x").status_code, 401)
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.PROCESSING)

    def test_ready_queues_ingest_job_once(self):
        r = self.req()
        p = {"id": r.token, "status": "ready", "size": 1234, "sha256": "ab"}
        self.assertEqual(self.signed(p).status_code, 204)
        self.assertEqual(self.signed(p).status_code, 204)   # پیام تکراری
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.DOWNLOADING)
        self.assertEqual(Job.objects.filter(kind=Job.Kind.SATELLITE).count(), 1)
        self.assertEqual(Job.objects.get().params, {"request": r.pk})

    def test_failed_refunds_with_reason(self):
        r = self.req()
        self.signed({"id": r.token, "status": "failed", "message": "باند لازم در این تصویر نیست: nir"})
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.FAILED)
        self.assertFalse(r.charged)
        self.assertIn("باند", r.message)

    def test_hook_rejection_explains_reason(self):
        r = self.req()
        old = protocol.sign(SECRET, "POST", "/hooks/satellite/", b"{}", ts=timezone.now().timestamp() - 900)
        resp = self.client.post("/hooks/satellite/", "{}", content_type="application/json", HTTP_X_SAT_TIME=old[protocol.H_TIME],
                                HTTP_X_SAT_SIG=old[protocol.H_SIG], HTTP_X_SAT_KID=old[protocol.H_KID])
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["reason"], "skew")
        bad = protocol.sign("other", "POST", "/hooks/satellite/", b"{}")
        resp = self.client.post("/hooks/satellite/", "{}", content_type="application/json", HTTP_X_SAT_TIME=bad[protocol.H_TIME],
                                HTTP_X_SAT_SIG=bad[protocol.H_SIG], HTTP_X_SAT_KID=bad[protocol.H_KID])
        self.assertEqual(resp.json()["reason"], "key")
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.PROCESSING)

    def test_unknown_token_is_404(self):
        self.assertEqual(self.signed({"id": "0" * 32, "status": "ready"}).status_code, 404)

    @mock.patch("satellite.client.call", return_value={"id": "x", "status": "ready", "size": 10, "sha256": ""})
    def test_poll_picks_up_missed_hook(self, call):
        r = self.req()
        SatRequest.objects.filter(pk=r.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        call.return_value = {"id": r.token, "status": "ready", "size": 10, "sha256": ""}
        self.assertEqual(services.poll(), 1)
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.DOWNLOADING)

    @mock.patch("satellite.client.call", return_value={})
    def test_poll_times_out_old_requests(self, call):
        r = self.req()
        old = timezone.now() - timedelta(minutes=90)
        SatRequest.objects.filter(pk=r.pk).update(created_at=old, updated_at=old)
        services.poll()
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.FAILED)
        self.assertFalse(r.charged)

    @mock.patch("satellite.client.call", side_effect=client.GatewayError("کار پیدا نشد.", 404))
    def test_poll_lost_job_fails_and_refunds(self, _):
        r = self.req()
        SatRequest.objects.filter(pk=r.pk).update(updated_at=timezone.now() - timedelta(minutes=2))
        services.poll()
        r.refresh_from_db()
        self.assertEqual((r.status, r.charged), (SatRequest.Status.FAILED, False))

    def test_poll_noop_when_off(self):
        self.req()
        with override_settings(SATGATE_URL=""):
            self.assertEqual(services.poll(), 0)


class IngestTests(_Base):
    def fake_download(self, token, dest, size, sha, max_bytes):
        make_tif(Path(dest)) if HAS_RIO else Path(dest).write_bytes(b"II*\x00")

    def ready_req(self, **kw):
        r = self.req(status=SatRequest.Status.DOWNLOADING, remote={"size": 5000, "sha256": ""}, **kw)
        return r, Job.objects.create(kind=Job.Kind.SATELLITE, database=self.db, user=self.user, params={"request": r.pk})

    def test_not_enough_space_fails_and_refunds(self):
        self.free.raster_mb = 1
        self.free.save()
        r, job = self.ready_req()
        SatRequest.objects.filter(pk=r.pk).update(remote={"size": 5 * 1048576, "sha256": ""})
        with mock.patch("satellite.client.call"), self.assertRaises(ent.EnterpriseError):
            services.ingest(job)
        r.refresh_from_db()
        self.assertEqual((r.status, r.charged), (SatRequest.Status.FAILED, False))
        self.assertIn("فضای رستر", r.message)
        self.assertFalse(Raster.objects.exists())

    def test_download_failure_cleans_up(self):
        r, job = self.ready_req()
        with mock.patch("satellite.client.download", side_effect=client.GatewayError("فایل دریافتی کامل نبود.")), \
                mock.patch("satellite.client.call"), self.assertRaises(client.GatewayError):
            services.ingest(job)
        r.refresh_from_db()
        self.assertEqual((r.status, r.charged), (SatRequest.Status.FAILED, False))
        self.assertFalse(Raster.objects.exists())

    def test_ingest_builds_raster_with_defaults(self):
        r, job = self.ready_req()

        def fake_process(j):
            rr = Raster.objects.get(pk=j.params["raster"])
            rr.status, rr.bands, rr.dtype, rr.size_bytes = Raster.Status.READY, 1, "Float32", 4321
            rr.save()
        with mock.patch("satellite.client.download", side_effect=self.fake_download), mock.patch("satellite.client.call") as call, \
                mock.patch("enterprise.services.process_raster", side_effect=fake_process):
            msg = services.ingest(job)
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.READY)
        self.assertEqual(r.raster.colormap, "rdylgn")
        self.assertEqual(r.raster.stats, [[-0.1, 0.9]])
        self.assertIn("Copernicus", r.raster.meta["attribution"])
        self.assertIn("آماده شد", msg)
        self.assertEqual(call.call_args.args[:2], ("DELETE", f"/v1/jobs/{r.token}"))   # دروازه فایل را پاک می‌کند

    @unittest.skipUnless(HAS_GDAL and HAS_RIO, "GDAL/rasterio نیست")
    def test_ingest_end_to_end_with_gdal(self):
        r, job = self.ready_req()
        with mock.patch("satellite.client.download", side_effect=self.fake_download), mock.patch("satellite.client.call"):
            services.ingest(job)
        r.refresh_from_db()
        self.assertEqual(r.status, SatRequest.Status.READY)
        self.assertEqual(r.raster.status, Raster.Status.READY)
        self.assertTrue(r.raster.path.exists())

    def test_delete_request_frees_space(self):
        r = self.req(status=SatRequest.Status.READY)
        rr = Raster.objects.create(database=self.db, title="t", size_bytes=1000, status=Raster.Status.READY)
        rr.path.parent.mkdir(parents=True, exist_ok=True)
        rr.path.write_bytes(b"x")
        r.raster = rr
        r.save()
        services.delete_request(r)
        self.assertFalse(Raster.objects.exists())
        self.assertFalse(SatRequest.objects.exists())
        self.assertFalse(rr.path.exists())

    def test_worker_dispatch_marks_job_failed_with_reason(self):
        r, job = self.ready_req()
        job.status = Job.Status.RUNNING
        job.save()
        with mock.patch("satellite.client.download", side_effect=client.GatewayError("قطع شد.")), mock.patch("satellite.client.call"):
            jobs.run(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertIn("قطع شد", job.message)


class ViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def url(self, name, *a):
        return reverse(f"satellite:{name}", args=[self.db.pk, *a])

    def post(self, name, data):
        return self.client.post(self.url(name), json.dumps(data), content_type="application/json")

    def test_page_shows_quota_and_nav_item(self):
        self.req(status=SatRequest.Status.FAILED, message="باند لازم نیست", charged=False)
        r = self.client.get(self.url("index"))
        self.assertContains(r, "تصویر ماهواره‌ای")
        self.assertContains(r, "۰ از ۱۰")                     # اعتبار (ناموفق حساب نشد)
        self.assertContains(r, "باند لازم نیست")
        self.assertContains(r, "اعتبار شما برگردانده شد")
        self.assertContains(r, 'id="sat-dlg"')
        self.assertContains(r, 'href="' + self.url("index") + '"')   # ریل کناری
        self.assertNotContains(r, "به‌زودی فعال می‌شود")

    def test_page_when_gateway_not_set_up(self):
        with override_settings(SATGATE_URL=""):
            r = self.client.get(self.url("index"))
        self.assertContains(r, "به‌زودی فعال می‌شود")
        self.assertNotContains(r, 'id="sat-dlg"')

    def test_stranger_gets_404_and_viewer_cannot_order(self):
        other = User.objects.create_user("09120000082")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url("index")).status_code, 404)
        Member.objects.create(database=self.db, user=other, role=Member.Role.VIEWER)
        self.assertEqual(self.client.get(self.url("index")).status_code, 200)
        self.assertEqual(self.post("order", {"bbox": BBOX, "product": "ndvi", "scene": "S2A_X_1"}).status_code, 404)
        self.assertNotContains(self.client.get(self.url("index")), 'id="sat-dlg"')

    def test_quote_endpoint_returns_blockers(self):
        j = self.post("quote", {"bbox": [51.0, 35.5, 51.4, 35.9], "product": "true_color"}).json()
        self.assertTrue(j["ok"])
        self.assertFalse(j["quote"]["ok"])
        self.assertEqual(j["quote"]["blockers"][0]["code"], "area")
        bad = self.post("quote", {"bbox": [1], "product": "ndvi"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("محدوده", bad.json()["error"])

    @mock.patch("satellite.client.call", return_value={"scenes": [{"id": "S2A_X_1", "cloud": 3, "coverage": 100}]})
    def test_search_validates_dates_and_proxies(self, call):
        today = timezone.localdate()
        ok = self.post("search", {"bbox": BBOX, "start": str(today - timedelta(days=30)), "end": str(today), "max_cloud": 20})
        self.assertEqual(ok.json()["scenes"][0]["id"], "S2A_X_1")
        self.assertEqual(call.call_args.args[2]["max_cloud"], 20.0)
        for bad in ({"start": "x", "end": "y"}, {"start": str(today), "end": str(today - timedelta(days=1))},
                    {"start": "2020-01-01", "end": str(today)}):
            r = self.post("search", {"bbox": BBOX, **bad})
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.post("search", {"bbox": [1], "start": str(today), "end": str(today)}).status_code, 400)

    @mock.patch("satellite.client.call", side_effect=client.GatewayError("دروازه‌ی ماهواره موقتاً در دسترس نیست."))
    def test_search_gateway_down_is_clear_503(self, _):
        today = str(timezone.localdate())
        r = self.post("search", {"bbox": BBOX, "start": today, "end": today})
        self.assertEqual(r.status_code, 503)
        self.assertIn("در دسترس نیست", r.json()["error"])

    @mock.patch("satellite.client.call", return_value={})
    def test_order_endpoint_and_blocked_order_returns_quote(self, _):
        ok = self.post("order", {"bbox": BBOX, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A"})
        self.assertTrue(ok.json()["ok"])
        big = self.post("order", {"bbox": [51.0, 35.5, 51.4, 35.9], "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A"})
        self.assertEqual(big.status_code, 409)
        self.assertEqual(big.json()["code"], "area")
        self.assertEqual(big.json()["quote"]["blockers"][0]["code"], "area")

    def test_cards_fragment_flags_active(self):
        self.req()
        r = self.client.get(self.url("cards"))
        self.assertEqual(r["X-Sat-Active"], "1")
        self.assertContains(r, "در حال برش")
        SatRequest.objects.update(status=SatRequest.Status.FAILED)
        self.assertEqual(self.client.get(self.url("cards"))["X-Sat-Active"], "0")

    def test_delete_blocked_while_active(self):
        r = self.req()
        self.client.post(self.url("delete", r.pk))
        self.assertTrue(SatRequest.objects.filter(pk=r.pk).exists())
        SatRequest.objects.filter(pk=r.pk).update(status=SatRequest.Status.FAILED)
        self.client.post(self.url("delete", r.pk))
        self.assertFalse(SatRequest.objects.filter(pk=r.pk).exists())

    @mock.patch("satellite.client.thumb", return_value=b"\xff\xd8jpeg")
    def test_thumb_proxied_and_validated(self, th):
        u = self.url("thumb", "sentinel-2-l2a", "S2A_X_1")
        self.assertEqual(self.client.get(u).content, b"\xff\xd8jpeg")
        self.client.get(u)
        self.assertEqual(th.call_count, 1)   # کش
        self.assertEqual(self.client.get(self.url("thumb", "other", "S2A_X_1")).status_code, 404)

    def test_card_shows_satellite_and_info_menu(self):
        r = self.req(status=SatRequest.Status.READY, scene_id="S2B_38SMG_20261024_0_L2A", cloud=3.2)
        rr = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY, bounds=BBOX, size_bytes=2048,
                                   bands=1, dtype="Float32", crs="EPSG:32639", width=300, height=200,
                                   meta={"attribution": "Contains modified Copernicus Sentinel data (ESA)"})
        r.raster = rr
        r.save()
        self.assertEqual((r.satellite, r.agency), ("Sentinel-2B", "ESA / Copernicus"))
        info = r.info
        self.assertEqual((info["satellite"], info["bands"], info["crs"], info["width"]), ("Sentinel-2B", 1, "EPSG:32639", 300))
        self.assertIn("۱۴۰", info["date"])
        html = self.client.get(self.url("index")).content.decode()
        self.assertIn("Sentinel-2B", html)
        self.assertIn("data-sat-info", html)
        self.assertIn("ویژگی‌های تصویر", html)
        self.assertIn('id="sat-info"', html)

    def test_dem_card_names_copernicus(self):
        r = self.req(product="dem", scene_id="cop-dem-glo-30", scene_date="")
        self.assertEqual(r.satellite, "Copernicus DEM GLO-30")
        self.assertEqual(r.info["date"], "")

    def test_card_has_qgis_connect_and_download(self):
        r = self.req(status=SatRequest.Status.READY)
        rr = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY, bounds=BBOX, size_bytes=2048)
        r.raster = rr
        r.save()
        html = self.client.get(self.url("index")).content.decode()
        self.assertIn(f"/raster/{rr.slug}.tif", html)
        self.assertIn("data-sat-conn", html)
        self.assertIn("دانلود GeoTIFF", html)
        self.assertIn(f"/raster/{rr.slug}/", html)   # کاشی پیش‌نمایش


class RasterFileTests(_Base):
    def setUp(self):
        super().setUp()
        self.r = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY)
        self.r.path.parent.mkdir(parents=True, exist_ok=True)
        self.r.path.write_bytes(bytes(range(256)) * 4)   # ۱۰۲۴ بایت
        self.url = reverse("enterprise:raster_file", args=[self.r.slug])

    def test_private_needs_login_member_or_key(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_range_requests_for_qgis(self):
        self.client.force_login(self.user)
        full = self.client.get(self.url)
        self.assertEqual(full["Accept-Ranges"], "bytes")
        self.assertEqual(len(b"".join(full.streaming_content)), 1024)
        part = self.client.get(self.url, HTTP_RANGE="bytes=0-9")
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part["Content-Range"], "bytes 0-9/1024")
        self.assertEqual(b"".join(part.streaming_content), bytes(range(10)))
        tail = self.client.get(self.url, HTTP_RANGE="bytes=-4")
        self.assertEqual(b"".join(tail.streaming_content), bytes([252, 253, 254, 255]))
        self.assertEqual(self.client.get(self.url, HTTP_RANGE="bytes=5000-").status_code, 416)

    def test_public_and_download_header(self):
        Raster.objects.filter(pk=self.r.pk).update(is_public=True)
        r = self.client.get(self.url + "?download=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")


class TileStretchTests(_Base):
    def test_uint16_rgb_is_stretched(self):
        if not HAS_RIO:
            self.skipTest("rasterio نیست")
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        from enterprise import tiles
        rr = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY, bands=3, dtype="UInt16", rgb=True,
                                   bounds=BBOX)
        rr.path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(rr.path, "w", driver="GTiff", width=256, height=256, count=3, dtype="uint16", crs="EPSG:4326",
                           transform=from_origin(51.30, 35.75, 0.0002, 0.0002)) as d:
            for i in (1, 2, 3):
                d.write(np.full((256, 256), 1500, dtype="uint16"), i)
        png = tiles.render(rr, 13, 6577, 3220)
        self.assertTrue(png is None or png[:4] == b"\x89PNG")


class SiteSettingsTests(TestCase):
    """نشانی و کلید دروازه از تنظیمات سایت می‌آید (متغیر محیطی فقط جایگزین است)."""

    def form(self, **extra):
        from core.admin import SiteSettingsForm
        from core.models import SiteSettings
        from core.tests.test_footer_enamad import form_data

        conf = SiteSettings.get()
        return SiteSettingsForm(form_data(conf, **extra), instance=conf)

    def test_unset_means_off(self):
        self.assertFalse(client.configured())

    def test_save_encrypts_secret_and_config_prefers_site_settings(self):
        from core.models import SiteSettings
        f = self.form(satgate_url="https://sat.example.com/", satgate_secret=" abc def ")
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        conf = SiteSettings.get()
        self.assertEqual(conf.satgate_url, "https://sat.example.com")
        self.assertNotIn("abcdef", conf.satgate_secret_encrypted)
        self.assertTrue(conf.satgate_ready)
        with override_settings(SATGATE_URL="https://env.example", SATGATE_SECRET="env"):
            self.assertEqual(client.config(), ("https://sat.example.com", "abcdef"))
        self.assertTrue(client.configured())

    def test_env_is_fallback_and_blank_save_keeps_secret(self):
        from core.models import SiteSettings
        with override_settings(SATGATE_URL="https://env.example", SATGATE_SECRET="env"):
            self.assertEqual(client.config(), ("https://env.example", "env"))
        self.form(satgate_url="https://sat.example.com", satgate_secret="k1").save()
        f = self.form(satgate_url="https://sat.example.com")
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        self.assertEqual(SiteSettings.get().get_satgate_secret(), "k1")
        self.assertNotIn("k1", str(self.form()["satgate_secret"]))
        f = self.form(clear_satgate_secret="on")
        self.assertTrue(f.is_valid())
        f.save()
        self.assertFalse(SiteSettings.get().satgate_ready)

    def test_generate_secret_once(self):
        from core.models import SiteSettings
        f = self.form(satgate_url="https://sat.example.com", generate_satgate_secret="on")
        self.assertTrue(f.is_valid(), f.errors)
        obj = f.save()
        self.assertGreaterEqual(len(obj._new_satgate_secret), 48)
        self.assertEqual(SiteSettings.get().get_satgate_secret(), obj._new_satgate_secret)

    def test_url_validation(self):
        for bad in ("http://sat.example.com", "https://sat.example.com/path", "ftp://x", "sat.example.com", "https://a b"):
            self.assertFalse(self.form(satgate_url=bad).is_valid(), bad)
        self.assertTrue(self.form(satgate_url="http://127.0.0.1:8099").is_valid())
        self.assertTrue(self.form(satgate_url="https://sat.example.com:8443").is_valid())

    def test_hook_uses_site_settings_secret(self):
        from core.models import SiteSettings
        conf = SiteSettings.get()
        conf.set_satgate_secret("dbsecret")
        conf.satgate_url = "https://gw.test"
        conf.save()
        body = json.dumps({"id": "0" * 32, "status": "ready"}).encode()
        h = protocol.sign("dbsecret", "POST", "/hooks/satellite/", body)
        r = self.client.post("/hooks/satellite/", body, content_type="application/json", HTTP_X_SAT_TIME=h[protocol.H_TIME],
                             HTTP_X_SAT_SIG=h[protocol.H_SIG])
        self.assertEqual(r.status_code, 404)   # امضا درست بود (۴۰۱ نیست)؛ فقط شناسه ناموجود است


class AdminTestButtonTests(TestCase):
    def setUp(self):
        from core.models import SiteSettings
        SiteSettings.get()
        self.admin = User.objects.create_admin("boss", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)

    def test_settings_page_has_tab_and_button(self):
        r = self.client.get(reverse("admin:core_sitesettings_change", args=[1]))
        self.assertContains(r, "تصویر ماهواره‌ای")
        self.assertContains(r, reverse("admin:core_sitesettings_satgatetest"))
        self.assertContains(r, "تنظیم نشده")

    def test_button_not_configured(self):
        r = self.client.get(reverse("admin:core_sitesettings_satgatetest"), follow=True)
        self.assertContains(r, "هنوز در تنظیمات سایت وارد نشده")

    @mock.patch("satellite.probe.run", return_value=[(True, "دروازه در دسترس است."), (True, "کلید مشترک درست است.")])
    def test_button_success_shows_each_step(self, _):
        r = self.client.get(reverse("admin:core_sitesettings_satgatetest"), follow=True)
        self.assertContains(r, "دروازه در دسترس است.")
        self.assertContains(r, "همه‌ی مراحل موفق بود")

    @mock.patch("satellite.probe.run", return_value=[(True, "دروازه در دسترس است."), (False, "امضا پذیرفته نشد: x")])
    def test_button_failure_is_explained(self, _):
        r = self.client.get(reverse("admin:core_sitesettings_satgatetest"), follow=True)
        self.assertContains(r, "امضا پذیرفته نشد")
        self.assertNotContains(r, "همه‌ی مراحل موفق بود")

    def test_button_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("admin:core_sitesettings_satgatetest")).status_code, 302)


class RejectMessageTests(TestCase):
    """پیام ۴۰۱ دروازه به فارسی و با راه‌حل مشخص."""

    def test_messages_per_reason(self):
        m = client.reject_message({"reason": "skew", "skew_s": 340})
        self.assertIn("۳۴۰", m)
        self.assertIn("جلوتر", m)
        self.assertIn("NTP", m)
        self.assertIn("عقب‌تر", client.reject_message({"reason": "skew", "skew_s": -500}))
        self.assertIn("یکی نیست", client.reject_message({"reason": "key"}))
        self.assertIn("پراکسی", client.reject_message({"reason": "signature"}))
        self.assertIn("SATGATE_SECRET", client.reject_message({"reason": "no_secret"}))
        self.assertIn("بررسی کنید", client.reject_message({}))

    @GW
    def test_http_401_from_gateway_is_translated(self):
        import io
        import urllib.error
        body = json.dumps({"reason": "skew", "skew_s": 300, "error": "x"}).encode()
        err = urllib.error.HTTPError("https://gw.test/v1/probe", 401, "Unauthorized", {}, io.BytesIO(body))
        with mock.patch("urllib.request.urlopen", side_effect=err), self.assertRaises(client.GatewayError) as cm:
            client.call("POST", "/v1/probe", {})
        self.assertIn("۳۰۰", str(cm.exception))
        self.assertEqual(cm.exception.status, 401)

    @GW
    def test_requests_carry_key_id(self):
        seen = {}

        def fake(req, timeout=0):
            seen.update(dict(req.header_items()))
            raise OSError("stop")
        with mock.patch("urllib.request.urlopen", side_effect=fake), self.assertRaises(client.GatewayError):
            client.call("POST", "/v1/probe", {})
        self.assertEqual(seen["X-sat-kid"], protocol.key_id(SECRET))


@GW
class ProbeTests(TestCase):
    def test_not_configured_message(self):
        with override_settings(SATGATE_URL="", SATGATE_SECRET=""):
            steps = probe.run()
        self.assertEqual(steps[0][0], False)
        self.assertIn("هنوز", steps[0][1])

    def test_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            steps = probe.run()
        self.assertEqual([ok for ok, _ in steps], [False])
        self.assertIn("به دروازه نرسیدیم", steps[0][1])

    def test_wrong_key_is_named(self):
        health = mock.MagicMock()
        health.__enter__.return_value.read.return_value = b'{"ok": true, "version": "1.0", "configured": true}'
        with mock.patch("urllib.request.urlopen", return_value=health), \
                mock.patch("satellite.client.call", side_effect=client.GatewayError("کلید ارتباط پنل با دروازه درست نیست", 401)):
            steps = probe.run()
        self.assertEqual([ok for ok, _ in steps], [True, False])
        self.assertIn("کلید", steps[1][1])

    def test_all_steps_pass(self):
        health = mock.MagicMock()
        health.__enter__.return_value.read.return_value = b'{"ok": true, "version": "1.0", "configured": true}'
        replies = [{"ok": True, "stac_ms": 120, "data_ms": 300},
                   {"missions": {"sentinel2": {"ok": True, "ms": 90}, "landsat": {"ok": True, "ms": 210}}},
                   {"scenes": [{"id": "S2A_X_1", "collection": "sentinel-2-l2a"}]}]
        with mock.patch("urllib.request.urlopen", return_value=health), mock.patch("satellite.client.call", side_effect=replies), \
                mock.patch("satellite.client.thumb", return_value=b"x" * 20000):
            steps = probe.run()
        self.assertTrue(all(ok for ok, _ in steps), steps)
        self.assertEqual(len(steps), 6)
        self.assertTrue(any("Landsat 8/9: در دسترس" in t for _, t in steps))


@GW
class MissionTests(_Base):
    """انتخاب ماهواره: فقط ماهواره‌ی در دسترس نشان داده می‌شود؛ Landsat محصول و سهمیه‌ی خودش را دارد."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.client.force_login(self.user)

    def url(self, name, *a):
        return reverse(f"satellite:{name}", args=[self.db.pk, *a])

    def test_missions_list_hides_unavailable_and_explains(self):
        live = {"missions": {"sentinel2": {"ok": True, "ms": 80}, "landsat": {"ok": False, "ms": 5, "error": "به کاتالوگ تصویر وصل نشدیم."}}}
        with mock.patch("satellite.client.call", return_value=live):
            j = self.client.get(self.url("missions")).json()
        by = {m["key"]: m for m in j["missions"]}
        self.assertTrue(by["sentinel2"]["available"])
        self.assertFalse(by["landsat"]["available"])
        self.assertIn("وصل نشدیم", by["landsat"]["error"])
        self.assertEqual(by["landsat"]["res"], 30)

    def test_landsat_available_when_gateway_says_so(self):
        live = {"missions": {"sentinel2": {"ok": True}, "landsat": {"ok": True, "ms": 300}}}
        with mock.patch("satellite.client.call", return_value=live):
            by = {m["key"]: m for m in self.client.get(self.url("missions")).json()["missions"]}
        self.assertTrue(by["landsat"]["available"])

    def test_old_gateway_without_missions_endpoint_offers_only_sentinel2(self):
        with mock.patch("satellite.client.call", side_effect=client.GatewayError("پیدا نشد", 404)):
            by = {m["key"]: m for m in self.client.get(self.url("missions")).json()["missions"]}
        self.assertTrue(by["sentinel2"]["available"])
        self.assertFalse(by["landsat"]["available"])

    def test_gateway_down_still_lists_sentinel2(self):
        with mock.patch("satellite.client.call", side_effect=client.GatewayError("در دسترس نیست")):
            by = {m["key"]: m for m in self.client.get(self.url("missions")).json()["missions"]}
        self.assertTrue(by["sentinel2"]["available"])
        self.assertIn("در دسترس نیست", by["landsat"]["error"])

    def test_page_config_has_products_per_mission(self):
        html = self.client.get(self.url("index")).content.decode()
        self.assertIn('"mission":"landsat"', html.replace(" ", ""))
        self.assertIn("data-missions", html)

    @mock.patch("satellite.client.call", return_value={})
    def test_order_landsat_sends_mission_and_stores_it(self, call):
        r = services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "mission": "landsat",
                                                "scene": "LC09_L2SP_164035_20261020_20261022_02_T1",
                                                "scene_date": "2026-10-20T07:10:00Z", "cloud": 4})
        self.assertEqual(r.mission, "landsat")
        self.assertEqual(call.call_args.args[2]["mission"], "landsat")
        self.assertEqual((r.satellite, r.agency), ("Landsat 9", "USGS / NASA"))
        self.assertEqual(r.spec.res_m, 30)

    @mock.patch("satellite.client.call", return_value={})
    def test_dem_ignores_mission_and_bad_mission_rejected(self, call):
        r = services.order(self.db, self.user, {"bbox": BBOX, "product": "dem", "mission": "landsat"})
        self.assertEqual(r.mission, "dem")
        with self.assertRaises(services.SatError) as cm:
            services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "mission": "nope", "scene": "S2A_X_1"})
        self.assertEqual(cm.exception.code, "mission")

    @mock.patch("satellite.client.call", return_value={})
    def test_composite_order_needs_no_scene_and_sends_period(self, call):
        today = timezone.localdate()
        r = services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "mask": True,
                                                "composite": {"start": str(today - timedelta(days=60)), "end": str(today), "max_cloud": 50}})
        self.assertEqual((r.mission, r.mask), ("sentinel2", True))
        self.assertEqual(r.composite["max_cloud"], 50.0)
        self.assertEqual(r.composite["max_scenes"], 6)
        body = call.call_args.args[2]
        self.assertEqual((body["scene"], body["mask"]), ("", True))
        self.assertEqual(body["composite"]["start"], str(today - timedelta(days=60)))
        self.assertEqual((r.satellite, r.agency), ("Sentinel-2", "ESA / Copernicus"))
        self.assertIn("ترکیب بی‌ابر", r.title)
        info = r.info
        self.assertEqual((info["composite"], info["mask"]), (True, True))
        self.assertIn("تا", info["period"])

    @mock.patch("satellite.client.call", return_value={})
    def test_composite_validation_and_dem(self, _):
        today = timezone.localdate()
        base = {"bbox": BBOX, "product": "ndvi"}
        for bad in ({"start": "x", "end": "y"}, {"start": str(today), "end": str(today - timedelta(days=3))},
                    {"start": "2020-01-01", "end": str(today)}):
            with self.assertRaises(services.SatError, msg=str(bad)):
                services.order(self.db, self.user, {**base, "composite": bad})
        with self.assertRaises(services.SatError) as cm:
            services.order(self.db, self.user, {"bbox": BBOX, "product": "dem",
                                                "composite": {"start": str(today - timedelta(days=9)), "end": str(today)}})
        self.assertEqual(cm.exception.code, "composite")
        with self.assertRaises(services.SatError) as cm:
            services.order(self.db, self.user, {**base})                       # نه تصویر، نه ترکیب
        self.assertEqual(cm.exception.code, "scene")

    @mock.patch("satellite.client.call", return_value={})
    def test_single_scene_mask_flag_is_kept_and_composite_is_masked_by_default(self, call):
        r = services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A",
                                                "scene_date": "2026-06-01T07:00:00Z", "mask": True})
        self.assertTrue(r.mask)
        SatRequest.objects.update(status=SatRequest.Status.READY)            # سقف دو دریافت هم‌زمان
        r2 = services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "scene": "S2A_39SUQ_20260602_0_L2A"})
        self.assertFalse(r2.mask)
        SatRequest.objects.update(status=SatRequest.Status.READY)
        today = timezone.localdate()
        r3 = services.order(self.db, self.user, {"bbox": BBOX, "product": "true_color",
                                                 "composite": {"start": str(today - timedelta(days=30)), "end": str(today)}})
        self.assertTrue(r3.mask)                                               # در ترکیب پیش‌فرض ماسک روشن است

    def test_hook_keeps_composite_usage_for_ingest(self):
        r = self.req(composite={"start": "2026-06-01", "end": "2026-06-30", "max_cloud": 40, "max_scenes": 6}, mask=True)
        services.on_remote({"id": r.token, "status": "ready", "size": 10, "sha256": "", "used": 4, "of": 5})
        r.refresh_from_db()
        self.assertEqual((r.remote["used"], r.remote["of"]), (4, 5))
        self.assertEqual(r.info["used"], 4)

    def test_landsat_estimate_is_smaller_than_sentinel2(self):
        big = [51.0, 35.5, 51.4, 35.9]
        a = services.quote(self.db, big, "true_color", "sentinel2")["est_bytes"]
        b = services.quote(self.db, big, "true_color", "landsat")["est_bytes"]
        self.assertLess(b, a / 5)

    @mock.patch("satellite.client.call", return_value={"scenes": []})
    def test_search_passes_mission(self, call):
        today = str(timezone.localdate())
        self.client.post(self.url("search"), json.dumps({"bbox": BBOX, "start": today, "end": today, "mission": "landsat"}),
                         content_type="application/json")
        self.assertEqual(call.call_args.args[2]["mission"], "landsat")
        bad = self.client.post(self.url("search"), json.dumps({"bbox": BBOX, "start": today, "end": today, "mission": "x"}),
                               content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_thumb_allows_landsat_collection(self):
        with mock.patch("satellite.client.thumb", return_value=b"jpg"):
            r = self.client.get(self.url("thumb", "landsat-c2-l2", "LC09_L2SP_164035_20261020_20261022_02_T1"))
        self.assertEqual(r.content, b"jpg")

    def test_thumb_url_template_takes_collection_per_scene(self):
        """پیش‌نمایش Landsat با مجموعه‌ی Sentinel-2 درخواست می‌شد؛ حالا قالب هر دو جای‌نگهدار را دارد."""
        html = self.client.get(self.url("index")).content.decode()
        self.assertIn("/satellite/thumb/COLL/ITEM.jpg", html)
        js = Path(__file__).resolve().parents[2].joinpath("static/js/satellite.js").read_text()
        self.assertIn('cfg.thumb.replace("COLL", encodeURIComponent(s.collection))', js)

    def test_toggle_public_and_key_link(self):
        req = self.req(status=SatRequest.Status.READY)
        rr = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY, bounds=BBOX, size_bytes=1)
        req.raster = rr
        req.save()
        html = self.client.get(self.url("index")).content.decode()
        self.assertIn("عمومی کردن", html)
        self.assertIn(f"/dashboard/{self.db.pk}/publish/#keys", html)     # ساخت کلید: نقشه و API
        self.assertIn("نقشه و API ← کلیدهای API", html)
        self.client.post(self.url("toggle_public", req.pk))
        rr.refresh_from_db()
        self.assertTrue(rr.is_public)
        self.assertIn("خصوصی کردن", self.client.get(self.url("index")).content.decode())
        self.client.post(self.url("toggle_public", req.pk))
        rr.refresh_from_db()
        self.assertFalse(rr.is_public)

    def test_viewer_cannot_toggle_public(self):
        req = self.req(status=SatRequest.Status.READY)
        req.raster = Raster.objects.create(database=self.db, title="t", status=Raster.Status.READY)
        req.save()
        other = User.objects.create_user("09120000083")
        Member.objects.create(database=self.db, user=other, role=Member.Role.VIEWER)
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url("toggle_public", req.pk)).status_code, 404)


class ProbeCommandTests(TestCase):
    def test_fails_when_not_configured(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with override_settings(SATGATE_URL="", SATGATE_SECRET=""), self.assertRaises(CommandError):
            call_command("sat_probe")
