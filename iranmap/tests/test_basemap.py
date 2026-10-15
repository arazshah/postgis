"""نقشه پایه ایران: خواندن PMTiles، دسترسی هم‌سایت/کلید API، سبک و glyph."""
import gzip
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

from accounts.models import User
from databases.models import DatabaseServer, Plan, UserDatabase
from iranmap import basemap, glyphs
from publish.models import ApiKey, DailyUsage

TILE = b"\x1a\x05fake!"  # محتوا برای خواندن مهم نیست


def write_pmtiles(path: Path, gz: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    tiles = {(0, 0, 0): TILE, (12, 2632, 1613): TILE + b"12", (14, 10530, 6455): TILE + b"14"}
    with open(path, "wb") as f:
        w = Writer(f)
        for (z, x, y), data in sorted(tiles.items(), key=lambda kv: zxy_to_tileid(*kv[0])):
            w.write_tile(zxy_to_tileid(z, x, y), gzip.compress(data) if gz else data)
        w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP if gz else Compression.NONE,
                    "min_zoom": 0, "max_zoom": 14, "min_lon_e7": 440000000, "min_lat_e7": 250000000,
                    "max_lon_e7": 634000000, "max_lat_e7": 398000000, "center_zoom": 5,
                    "center_lon_e7": 530000000, "center_lat_e7": 320000000}, {"name": "test"})


@override_settings(ALLOWED_HOSTS=["testserver"])
class BasemapTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(OSM_ROOT=str(self.tmp))
        o.enable()
        self.addCleanup(o.disable)
        basemap._cache["mtime"] = None
        self.same = {"HTTP_SEC_FETCH_SITE": "same-origin"}

    def test_missing_basemap(self):
        self.assertFalse(basemap.available())
        r = self.client.get("/basemap/0/0/0.mvt", **self.same)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.get("/basemap/style.json").status_code, 404)

    def test_tiles_same_site(self):
        write_pmtiles(basemap.path())
        r = self.client.get("/basemap/12/2632/1613.mvt", **self.same)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(r.content), TILE + b"12")
        self.assertIn("max-age", r["Cache-Control"])
        self.assertEqual(self.client.get("/basemap/5/1/1.mvt", **self.same).status_code, 204)  # کاشی خالی
        self.assertEqual(self.client.get("/basemap/3/99/0.mvt", **self.same).status_code, 400)
        # Referer همین سایت هم کافی است (مرورگرهای قدیمی بدون Sec-Fetch-Site)
        r = self.client.get("/basemap/0/0/0.mvt", HTTP_REFERER="http://testserver/m/abc/")
        self.assertEqual(r.status_code, 200)

    def test_uncompressed_tiles(self):
        write_pmtiles(basemap.path(), gz=False)
        r = self.client.get("/basemap/14/10530/6455.mvt", **self.same)
        self.assertNotIn("Content-Encoding", r)
        self.assertEqual(r.content, TILE + b"14")

    def test_reopens_rebuilt_file(self):
        write_pmtiles(basemap.path())
        self.assertEqual(basemap.maxzoom(), 14)
        import os
        import time

        write_pmtiles(basemap.path(), gz=False)
        os.utime(basemap.path(), (time.time() + 5, time.time() + 5))
        self.assertFalse(basemap.tile(0, 0, 0)[1])

    def test_external_needs_paid_key(self):
        write_pmtiles(basemap.path())
        url = "/basemap/0/0/0.mvt"
        self.assertEqual(self.client.get(url, HTTP_REFERER="https://other.example/").status_code, 401)
        self.assertEqual(self.client.get(url, {"key": "gpk_nope"}).status_code, 403)
        user = User.objects.create_user("09120000081")
        server = DatabaseServer.objects.create(name="s", host="h", admin_user="a", public_host="p")
        free = Plan.objects.create(name="رایگان آزمون", slug="t-free", is_free=True)
        paid = Plan.objects.create(name="پولی آزمون", slug="t-paid", is_free=False, basemap_api=True)
        db = UserDatabase.objects.create(owner=user, server=server, plan=free, db_name="gp_x", role_name="gp_x_user",
                                         status=UserDatabase.Status.ACTIVE)
        _k, raw = ApiKey.issue(db, user, "k")
        r = self.client.get(url, {"key": raw})
        self.assertEqual(r.status_code, 403)
        self.assertIn("پلن", r.json()["description"])
        db.plan = paid
        db.save()
        self.assertTrue(db.plan.basemap_api)
        r = self.client.get(url, {"key": raw})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
        self.assertEqual(DailyUsage.objects.get(database=db).requests, 1)

    def test_style(self):
        write_pmtiles(basemap.path())
        r = self.client.get("/basemap/style.json", {"key": "gpk_abc"})
        self.assertEqual(r.status_code, 200)
        st = r.json()
        src = st["sources"]["protomaps"]
        self.assertEqual(src["tiles"], ["http://testserver/basemap/{z}/{x}/{y}.mvt?key=gpk_abc"])
        self.assertEqual(src["maxzoom"], 14)
        self.assertIn("OpenStreetMap", src["attribution"])
        self.assertTrue(st["glyphs"].endswith("/basemap/fonts/{fontstack}/{range}.pbf"))
        fonts = {f for layer in st["layers"] for f in str(layer.get("layout", {}).get("text-font", "")).split("'")}
        self.assertFalse(any("Noto" in f for f in fonts))
        self.assertNotIn("sprite", st)

    def test_admin_queue_buttons(self):
        from jobs.models import Job

        admin = User.objects.create_superuser("adm", password="Adm-Pass-123456")
        self.client.force_login(admin)
        r = self.client.get(reverse("admin:iranmap_area_changelist"))
        self.assertContains(r, "ساخته نشده")
        self.client.post(reverse("admin:iranmap_rebuild", args=["basemap"]))
        self.client.post(reverse("admin:iranmap_rebuild", args=["basemap"]))
        self.assertEqual(Job.objects.filter(kind="basemap").count(), 1)


class GlyphTests(TestCase):
    def test_glyph_ranges_built(self):
        font = Path(__file__).resolve().parents[1] / "fonts" / "Vazirmatn-Regular.ttf"
        with tempfile.TemporaryDirectory() as d:
            n = glyphs.build(str(font), "Vazirmatn Regular", Path(d))
            self.assertGreater(n, 500)
            folder = Path(d) / "Vazirmatn Regular"
            self.assertEqual(len(list(folder.iterdir())), 256)
            persian = (folder / "1536-1791.pbf").read_bytes()
            self.assertIn(b"Vazirmatn Regular", persian)
            self.assertGreater(len(persian), 20000)
            self.assertLess(len((folder / "4096-4351.pbf").read_bytes()), 64)  # بازه بی‌استفاده خالی است

    def test_static_glyphs_in_repo(self):
        from django.conf import settings

        root = Path(settings.BASE_DIR) / "static" / "basemap" / "fonts"
        for stack in ("Vazirmatn Regular", "Vazirmatn Bold"):
            self.assertTrue((root / stack / "1536-1791.pbf").exists(), stack)
