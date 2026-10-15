"""پلن سازمانی: GeoServer اختصاصی (با GeoServer و Coolify ساختگی)، رستر، بکاپ چندساعته و کپی پایگاه داده."""
import json
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

import psycopg
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer, Plan, UserDatabase
from databases.provisioner import Provisioner
from enterprise import geoserver, services
from enterprise.models import GeoServerInstance, Raster
from jobs import services as jobs
from jobs.models import Job

PG_HOST = os.environ.get("TEST_PG_HOST", "")
HAS_GDAL = bool(shutil.which("gdal_translate"))
try:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    HAS_RIO = True
except ImportError:  # pragma: no cover
    HAS_RIO = False


def enterprise_plan() -> Plan:
    return Plan.objects.create(name="سازمانی تست", slug=f"ent-{uuid.uuid4().hex[:6]}", is_free=False, quota_mb=2048,
                               dedicated_geoserver=True, raster_mb=500, clone_enabled=True, snapshot_hours=6)


def make_tif(path: Path, bands: int = 1) -> Path:
    """GeoTIFF کوچک در تهران (EPSG:4326)، شیب ارتفاعی ساده."""
    data = np.arange(64 * 64, dtype="float32").reshape(64, 64)
    with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=bands, dtype="float32" if bands == 1
                       else "uint8", crs="EPSG:4326", transform=from_origin(51.30, 35.75, 0.002, 0.002)) as dst:
        for b in range(1, bands + 1):
            dst.write(data if bands == 1 else (data % 256).astype("uint8"), b)
    return path


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(RASTER_ROOT=str(self.tmp / "rasters"), BACKUP_ROOT=str(self.tmp / "bk"))
        o.enable()
        self.addCleanup(o.disable)
        self.server = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        self.server.set_admin_password("secret")
        self.server.save()
        self.user = User.objects.create_user("09120000071")
        self.ent = enterprise_plan()
        self.free = Plan.objects.get(slug="free")
        self.db = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.ent, label="org",
                                              db_name="gp_org", role_name="gp_org_user",
                                              status=UserDatabase.Status.ACTIVE)


class PlanAndPageTests(_Base):
    def test_enterprise_plan_has_features(self):
        self.assertTrue(self.ent.dedicated_geoserver and self.ent.clone_enabled)
        self.assertGreater(self.ent.raster_mb, 0)
        self.assertGreater(self.ent.snapshot_hours, 0)
        self.assertFalse(self.free.dedicated_geoserver or self.free.raster_mb or self.free.snapshot_hours)

    def test_page_owner_only_and_free_plan_message(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("enterprise:page", args=[self.db.pk]))
        self.assertContains(r, "GeoServer اختصاصی")
        self.assertNotContains(r, "مشاهده پلن‌ها")
        self.db.plan = self.free
        self.db.save()
        r = self.client.get(reverse("enterprise:page", args=[self.db.pk]))
        self.assertContains(r, "مشاهده پلن‌ها")
        self.client.force_login(User.objects.create_user("09120000072"))
        self.assertEqual(self.client.get(reverse("enterprise:page", args=[self.db.pk])).status_code, 404)

    def test_geoserver_request_rules(self):
        self.db.plan = self.free
        self.db.save()
        with self.assertRaisesMessage(services.EnterpriseError, "پلن سازمانی"):
            services.request_geoserver(self.db, self.user)
        self.db.plan = self.ent
        self.db.save()
        services.request_geoserver(self.db, self.user)
        self.assertEqual(Job.objects.filter(kind="geoserver").count(), 1)
        with self.assertRaisesMessage(services.EnterpriseError, "قبلاً"):
            services.request_geoserver(self.db, self.user)

    def test_snapshots_scheduled_for_enterprise_only(self):
        other = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.free, label="f",
                                            db_name="gp_f", role_name="gp_f_user", status="active")
        self.assertEqual(services.schedule_snapshots(), 1)
        job = Job.objects.get(kind="backup")
        self.assertEqual((job.database, job.trigger, job.params), (self.db, "system", {"snapshot": True}))
        self.assertFalse(Job.objects.filter(database=other).exists())
        # تا پایان بازه دوباره نه، حتی اگر کار در صف تمام شده باشد
        Job.objects.update(status="done")
        self.assertEqual(services.schedule_snapshots(), 0)
        later = timezone.now() + timedelta(hours=self.ent.snapshot_hours)
        Job.objects.update(created_at=timezone.now() - timedelta(hours=self.ent.snapshot_hours))
        self.assertEqual(services.schedule_snapshots(later), 1)

    def test_snapshot_backup_short_retention(self):
        job = Job.objects.create(kind="backup", trigger="system", database=self.db, params={"snapshot": True},
                                 status="running")
        with mock.patch("jobs.services.dump_database", return_value=1234):
            jobs.run(job)
        self.assertEqual(job.status, "done", job.message)
        hours = (job.expires_at - timezone.now()).total_seconds() / 3600
        self.assertAlmostEqual(hours, 48, delta=0.1)


class FakeGeoServer:
    """REST ساختگی GeoServer و Coolify که درخواست‌ها را ثبت می‌کند."""

    def __init__(self):
        self.calls, self.ws, self.stores, self.fts = [], set(), set(), set()

    def __call__(self, method, url, *, body=None, headers=None, auth=None, timeout=30):
        self.calls.append((method, url, body))
        if "/api/v1/" in url:
            if url.endswith("/applications/dockerimage"):
                return 201, b'{"uuid": "app-1"}'
            return 200, b"{}"
        path = url.split("/rest", 1)[1]
        if path == "/about/version.json":
            return 200, json.dumps({"about": {"resource": [{"@name": "GeoServer", "Version": "2.26.1"}]}}).encode()
        if method == "GET" and path.startswith("/workspaces/") and path.endswith(".json") and path.count("/") == 2:
            return (200 if path.split("/")[2][:-5] in self.ws else 404), b"{}"
        if method == "POST" and path == "/workspaces":
            self.ws.add(body["workspace"]["name"])
            return 201, b""
        if "/datastores/postgis.json" in path:
            return (200 if "postgis" in self.stores else 404), b"{}"
        if path.endswith("/datastores") or path.endswith("/datastores/postgis"):
            self.stores.add("postgis")
            return 201, b""
        if "/featuretypes/" in path:
            return (200 if path.rsplit("/", 1)[1][:-5] in self.fts else 404), b"{}"
        if path.endswith("/featuretypes"):
            self.fts.add(body["featureType"]["name"])
            return 201, b""
        return 404, b""


class TableRef:
    def __init__(self, name, geometry=True, schema="public", kind="r"):
        self.name, self.geometry, self.schema, self.kind = name, geometry, schema, kind


@override_settings(COOLIFY_API_URL="https://coolify.example", COOLIFY_API_TOKEN="t", COOLIFY_PROJECT_UUID="p",
                   COOLIFY_SERVER_UUID="s", GEOSERVER_DOMAIN="postgis.ir")
class GeoServerProvisionTests(_Base):
    def _run(self, fake):
        inst = services.request_geoserver(self.db, self.user)
        job = Job.objects.get(kind="geoserver")
        tables = [TableRef("parcels"), TableRef("roads"), TableRef("lookup", geometry=False),
                  TableRef("x", schema="topology")]
        with mock.patch.object(geoserver, "_request", fake), \
                mock.patch("databases.explorer.Explorer.tables", return_value=tables), \
                mock.patch.object(services, "_geoserver_role", return_value=("gp_org_user_geoserver", "pw-ro")), \
                mock.patch.object(geoserver.time, "sleep"):
            jobs.run_inline(job)
        inst.refresh_from_db()
        return inst, job

    def test_coolify_create_and_bootstrap(self):
        fake = FakeGeoServer()
        inst, job = self._run(fake)
        self.assertEqual(job.status, "done", job.message)
        self.assertEqual(inst.status, "active")
        self.assertEqual(inst.url, f"https://gs-{inst.slug}.postgis.ir/geoserver")
        self.assertEqual(inst.coolify_uuid, "app-1")
        self.assertEqual(inst.version, "2.26.1")
        self.assertEqual(fake.ws, {"gp_org"})
        self.assertEqual(fake.fts, {"parcels", "roads"})
        create = next(c for c in fake.calls if c[1].endswith("/dockerimage"))
        self.assertEqual(create[2]["limits_memory"], "1536m")
        envs = {c[2]["key"]: c[2]["value"] for c in fake.calls if c[1].endswith("/envs")}
        self.assertEqual(envs["GEOSERVER_ADMIN_PASSWORD"], inst.get_password())
        store = next(c for c in fake.calls if c[1].endswith("/datastores") and c[0] == "POST")
        params = {e["@key"]: e["$"] for e in store[2]["dataStore"]["connectionParameters"]["entry"]}
        # کاربر فقط‌خواندنی جدا؛ نه نقش اصلی مشتری
        self.assertEqual((params["user"], params["passwd"], params["database"]), ("gp_org_user_geoserver", "pw-ro",
                                                                                  "gp_org"))
        # اجرای دوباره (پیکربندی از پنل مدیریت) چیزی را تکراری نمی‌سازد
        Job.objects.create(kind="geoserver", database=self.db, status="queued")
        n = len(fake.calls)
        with mock.patch.object(geoserver, "_request", fake), \
                mock.patch("databases.explorer.Explorer.tables", return_value=[TableRef("parcels")]), \
                mock.patch.object(services, "_geoserver_role", return_value=("r", "p")):
            jobs.run_inline(Job.objects.filter(kind="geoserver", status="queued").get())
        self.assertFalse(any(c[1].endswith("/dockerimage") for c in fake.calls[n:]))

    def test_page_shows_addresses_when_active(self):
        self._run(FakeGeoServer())
        self.client.force_login(self.user)
        r = self.client.get(reverse("enterprise:page", args=[self.db.pk]))
        self.assertContains(r, "/geoserver/gp_org/wms")

    @override_settings(COOLIFY_API_URL="")
    def test_manual_mode_notifies_admin(self):
        with mock.patch("core.alerts.notify_admins") as notify:
            services.request_geoserver(self.db, self.user)
            jobs.run_inline(Job.objects.get(kind="geoserver"))
        notify.assert_called_once()
        inst = GeoServerInstance.objects.get()
        self.assertEqual(inst.status, "requested")
        self.assertIn("دستی", inst.message)

    def test_geoserver_down_marks_failed(self):
        def down(*a, **kw):
            raise geoserver.GeoServerError("اتصال ممکن نشد")

        inst = services.request_geoserver(self.db, self.user)
        inst.url = "https://gs.example/geoserver"
        inst.set_password("x")
        inst.save()
        with mock.patch.object(geoserver, "_request", down), mock.patch.object(geoserver.time, "sleep"), \
                mock.patch.object(geoserver.time, "monotonic", side_effect=[0, 1, 10_000]):
            job = jobs.run_inline(Job.objects.get(kind="geoserver"))
        inst.refresh_from_db()
        self.assertEqual((job.status, inst.status), ("failed", "failed"))


@unittest.skipUnless(HAS_GDAL and HAS_RIO, "gdal or rasterio missing")
class RasterTests(_Base):
    def _upload(self, path: Path, name="dem.tif"):
        self.client.force_login(self.user)
        return self.client.post(reverse("enterprise:page", args=[self.db.pk]), {
            "action": "raster_upload", "title": "ارتفاع", "file": SimpleUploadedFile(name, path.read_bytes())})

    def test_upload_process_and_tiles(self):
        self._upload(make_tif(self.tmp / "dem.tif"))
        r = Raster.objects.get()
        jobs.run_inline(Job.objects.get(kind="raster"))
        r.refresh_from_db()
        self.assertEqual(r.status, "ready", r.message)
        self.assertEqual((r.width, r.height, r.bands, r.crs), (64, 64, 1, "EPSG:4326"))
        self.assertAlmostEqual(r.bounds[0], 51.30, places=3)
        self.assertEqual(r.stats[0][0], 0)
        self.assertTrue(r.path.exists())
        self.assertFalse(services.raster_upload_path(r).exists())
        with rasterio.open(r.path) as src:  # COG واقعی با overview
            self.assertEqual(src.profile.get("compress", "").lower(), "deflate")
        # کاشی داخل محدوده: PNG؛ بیرون: 204
        z = 12
        x = int((51.36 + 180) / 360 * 2 ** z)
        import math
        lat = math.radians(35.72)
        y = int((1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * 2 ** z)
        resp = self.client.get(f"/raster/{r.slug}/{z}/{x}/{y}.png")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"\x89PNG"))
        self.assertEqual(self.client.get(f"/raster/{r.slug}/{z}/0/0.png").status_code, 204)
        self.assertEqual(self.client.get(f"/raster/{r.slug}.json").json()["bounds"], r.bounds)
        self.assertEqual(self.client.get(f"/r/{r.slug}/").status_code, 200)
        # خصوصی: بیرونی‌ها نمی‌بینند؛ عمومی: می‌بینند
        self.client.logout()
        self.assertEqual(self.client.get(f"/raster/{r.slug}/{z}/{x}/{y}.png").status_code, 404)
        r.is_public = True
        r.save()
        self.assertEqual(self.client.get(f"/raster/{r.slug}/{z}/{x}/{y}.png").status_code, 200)

    def test_rejects_non_tiff_and_free_plan(self):
        vrt = self.tmp / "evil.tif"
        vrt.write_text('<VRTDataset rasterXSize="1" rasterYSize="1"><VRTRasterBand dataType="Byte" band="1">'
                       '<SimpleSource><SourceFilename>/etc/passwd</SourceFilename></SimpleSource>'
                       '</VRTRasterBand></VRTDataset>')
        r = self._upload(vrt)
        self.assertFalse(Raster.objects.exists())
        self.assertContains(self.client.get(r.url), "GeoTIFF نیست")
        self.db.plan = self.free
        self.db.save()
        r = self._upload(make_tif(self.tmp / "a.tif"))
        self.assertFalse(Raster.objects.exists())

    def test_no_crs_fails_cleanly(self):
        p = self.tmp / "nocrs.tif"
        with rasterio.open(p, "w", driver="GTiff", width=8, height=8, count=1, dtype="uint8") as dst:
            dst.write(np.zeros((8, 8), dtype="uint8"), 1)
        self._upload(p)
        job = jobs.run_inline(Job.objects.get(kind="raster"))
        self.assertEqual(job.status, "failed")
        self.assertIn("مختصات", job.message)
        self.assertEqual(Raster.objects.get().status, "failed")

    def test_delete(self):
        self._upload(make_tif(self.tmp / "dem.tif"))
        jobs.run_inline(Job.objects.get(kind="raster"))
        r = Raster.objects.get()
        path = r.path
        self.client.post(reverse("enterprise:page", args=[self.db.pk]), {"action": "raster_delete", "raster": r.pk})
        self.assertFalse(Raster.objects.exists())
        self.assertFalse(path.exists())


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class CloneIntegrationTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        o = override_settings(BACKUP_ROOT=self.tmp.name)
        o.enable()
        self.addCleanup(o.disable)
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.server = server
        self.user = User.objects.create_user("09120000073")
        plan = enterprise_plan()
        self.db = db_services.create_database(self.user, f"cl_{uuid.uuid4().hex[:8]}", "Clone-Pass-123", ["postgis"],
                                              plan=plan)
        self.addCleanup(self._drop, self.db)
        with self._conn(self.db, "Clone-Pass-123") as c:
            c.execute("CREATE TABLE parcels(id serial PRIMARY KEY, geom geometry(Point, 4326))")
            c.execute("INSERT INTO parcels(geom) SELECT ST_MakePoint(51, 35)::geometry FROM generate_series(1, 7)")

    def _conn(self, db, pw):
        return psycopg.connect(host=self.server.host, port=self.server.port, user=db.role_name, password=pw,
                               dbname=db.db_name, autocommit=True)

    def _drop(self, db):
        db.refresh_from_db()
        if db.status != "deleted":
            db_services.delete_database(db)

    def test_clone_from_backup(self):
        with self.assertRaisesMessage(services.EnterpriseError, "بکاپ"):
            services.request_clone(self.db, self.user, None, "nope")
        backup = jobs.run_inline(jobs.request_backup(self.db, self.user))
        self.assertEqual(backup.status, "done", backup.message)
        self.client.force_login(self.user)
        label = f"cl_{uuid.uuid4().hex[:6]}_t"
        r = self.client.post(reverse("enterprise:page", args=[self.db.pk]),
                             {"action": "clone", "label": label, "backup": backup.pk})
        clone = UserDatabase.objects.get(label=label)
        self.addCleanup(self._drop, clone)
        self.assertRedirects(r, reverse("databases:detail", args=[clone.pk]), fetch_redirect_response=False)
        self.assertEqual(clone.expires_at, self.db.expires_at)
        job = jobs.run_inline(Job.objects.get(kind="clone"))
        self.assertEqual(job.status, "done", job.message)
        pw = self.client.session[f"gp_once_password_{clone.pk}"]
        with self._conn(clone, pw) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM parcels").fetchone()[0], 7)
            owner = c.execute("SELECT tableowner FROM pg_tables WHERE tablename='parcels'").fetchone()[0]
        self.assertEqual(owner, clone.role_name)
        # سقف کپی‌ها
        with mock.patch.object(services, "MAX_CLONES", 1), self.assertRaisesMessage(services.EnterpriseError,
                                                                                   "حداکثر 1"):
            services.request_clone(self.db, self.user, backup, "another_copy")
        # اصلی دست‌نخورده
        with self._conn(self.db, "Clone-Pass-123") as c:
            c.execute("DELETE FROM parcels")
        with self._conn(clone, pw) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM parcels").fetchone()[0], 7)
