"""ابزارهای نقشه چندلایه: اسلایدهای ارائه، صفحه چاپ و مقایسه، پروژه QGIS و انتشار WMS/WFS."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import psycopg
from defusedxml import ElementTree as SafeET
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from maps import qgis_export
from maps.models import MapLayer, MapSlide, WebMap
from publish import ows, qgis
from publish.models import OwsProject

PG_HOST = os.environ.get("TEST_PG_HOST", "")
QGIS_BIN = shutil.which("qgis_mapserver")


class ExportHelpersTests(SimpleTestCase):
    def test_colors_and_palette_pick_match_web_map(self):
        self.assertEqual(qgis_export._rgba("#0F5C59", 0.5), "15,92,89,128")
        self.assertEqual(qgis_export.pick(["a", "b", "c", "d", "e"], 3), ["a", "c", "e"])
        self.assertEqual(qgis_export._kind("MULTILINESTRING"), "Line")
        self.assertEqual(qgis_export._wkb("MULTIPOLYGON"), "MultiPolygon")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"], SITE_URL="https://postgis.example",
                   QGIS_SERVER_URL="http://qgis.internal/ows/")
class MapToolsTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(OWS_ROOT=str(self.tmp))
        o.enable()
        self.addCleanup(o.disable)
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        self.server = server
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000071")
        self.db = db_services.create_database(self.user, f"mt_{uuid.uuid4().hex[:8]}", "Tools-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        with psycopg.connect(host=PG_HOST, port=server.port, user=self.db.role_name, password="Tools-Pass-1",
                             dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE schools(gid serial PRIMARY KEY, name text, students int, geom geometry(Point, 4326))")
            c.execute("INSERT INTO schools(name, students, geom) SELECT 'مدرسه ' || g, g * 10, "
                      "ST_SetSRID(ST_MakePoint(51.3 + g * 0.002, 35.7), 4326) FROM generate_series(1, 20) g")
            c.execute("CREATE TABLE parks(id serial PRIMARY KEY, kind text, geom geometry(Polygon, 4326))")
            c.execute("INSERT INTO parks(kind, geom) SELECT (ARRAY['محلی','شهری'])[1 + g % 2], ST_Buffer(ST_SetSRID("
                      "ST_MakePoint(51.30 + g * 0.01, 35.71), 4326), 0.003) FROM generate_series(1, 4) g")
        self.client.force_login(self.user)
        self.client.post(reverse("maps:create", args=[self.db.pk]),
                         {"title": "مدارس و پارک‌ها", "t": ["public.schools", "public.parks"]})
        self.m = WebMap.objects.get()
        self.schools = self.m.layers.get(table="schools")
        self.parks = self.m.layers.get(table="parks")

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _save(self, **data):
        base = {"title": self.m.title, "basemap": "osm", "layers": [
            {"id": self.schools.pk, "style": self.schools.style}, {"id": self.parks.pk, "style": self.parks.style}]}
        return self.client.post(reverse("maps:composer", args=[self.db.pk, self.m.pk]), json.dumps({**base, **data}),
                                content_type="application/json")

    def _style(self):
        """مدارس: طبقه‌بندی عددی با برچسب؛ پارک‌ها: دسته‌ای."""
        st = {**self.schools.style, "mode": "graduated", "field": "students", "breaks": [50, 100, 150],
              "palette": "Blues", "label": "name"}
        pk = {**self.parks.style, "mode": "categorized", "field": "kind",
              "categories": [{"value": "محلی", "color": "#E0A526"}, {"value": "شهری", "color": "#0F5C59"}]}
        r = self._save(layers=[{"id": self.schools.pk, "style": st}, {"id": self.parks.pk, "style": pk}])
        self.assertEqual(r.status_code, 200)

    # ------------------------------------------------------------------ ارائه
    def test_slides_saved_validated_and_duplicated(self):
        self.db.plan.maps = 5
        self.db.plan.save()
        other = WebMap.objects.create(database=self.db, title="دیگر")
        foreign = MapLayer.objects.create(webmap=other, table="schools", geom_column="geom")
        slides = [
            {"title": "مدارس", "body": "متن " * 10, "view": {"center": [51.31, 35.7], "zoom": 14, "bearing": 30},
             "layers": [self.schools.pk, f"ml{self.schools.pk}", foreign.pk, "x"]},
            {"title": "t" * 500, "view": {"center": [500, 0], "zoom": 3}, "layers": "bad"},
            "junk",
        ]
        self.assertEqual(self._save(slides=slides).status_code, 200)
        saved = list(self.m.slides.all())
        self.assertEqual(len(saved), 2)
        self.assertEqual((saved[0].title, saved[0].layers), ("مدارس", [self.schools.pk]))
        self.assertEqual(saved[0].view, {"center": [51.31, 35.7], "zoom": 14.0, "bearing": 30.0})
        self.assertEqual((len(saved[1].title), saved[1].view, saved[1].layers), (120, {}, []))
        # ذخیره بدون کلید slides اسلایدها را دست نمی‌زند؛ فهرست خالی همه را پاک می‌کند
        self._save()
        self.assertEqual(self.m.slides.count(), 2)
        r = self.client.get(f"/maps/{self.m.slug}/present/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["config"]["slides"][0]["layers"], [f"ml{self.schools.pk}"])
        # کپی نقشه: اسلایدها به لایه‌های تازه اشاره می‌کنند
        self.client.post(reverse("maps:duplicate", args=[self.db.pk, self.m.pk]))
        copy = WebMap.objects.filter(title__endswith="(کپی)").get()
        new_schools = copy.layers.get(table="schools")
        self.assertEqual([s.layers for s in copy.slides.all()], [[new_schools.pk], []])
        self._save(slides=[])
        self.assertFalse(MapSlide.objects.filter(webmap=self.m).exists())

    # ------------------------------------------------------------------ صفحه‌های عمومی
    def test_present_print_compare_follow_map_access(self):
        pages = [f"/maps/{self.m.slug}/{p}/" for p in ("present", "print", "compare")]
        for url in pages:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.get(f"/maps/{self.m.slug}/")
        self.assertContains(r, "مقایسه لایه‌ها")
        self.assertNotContains(r, "▶ ارائه")  # هنوز اسلایدی نیست
        r = self.client.get(pages[1])
        self.assertContains(r, "@page{size:A4 landscape")
        self.client.logout()
        for url in pages:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.m.is_public = True
        self.m.save()
        for url in pages:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, 'name="robots" content="noindex"')
            self.assertEqual(r["X-Frame-Options"], "DENY")

    # ------------------------------------------------------------------ QGIS
    def test_qgis_project_download(self):
        self._style()
        r = self.client.get(reverse("maps:qgis", args=[self.db.pk, self.m.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'{self.m.slug}.qgs"', r["Content-Disposition"])
        text = r.content.decode()
        self.assertNotIn("password", text)
        root = SafeET.fromstring(r.content)
        self.assertEqual(root.find("title").text, "مدارس و پارک‌ها")
        names = [x.get("name") for x in root.find("layer-tree-group")]
        self.assertEqual(names, ["schools", "parks"])  # همان ترتیب نقشه (بالایی اول)
        layers = {x.find("layername").text: x for x in root.find("projectlayers")}
        src = layers["schools"].find("datasource").text
        self.assertIn(f"dbname='{self.db.db_name}' host=db.example", src)
        self.assertIn(f"user='{self.db.role_name}'", src)
        self.assertIn("key='gid' srid=4326 type=Point", src)
        self.assertIn('table="public"."schools" (geom)', src)
        r_s = layers["schools"].find("renderer-v2")
        self.assertEqual((r_s.get("type"), r_s.get("attr")), ("graduatedSymbol", "students"))
        self.assertEqual(len(r_s.find("ranges")), 4)
        self.assertEqual(layers["schools"].get("labelsEnabled"), "1")
        self.assertEqual(layers["schools"].find("labeling/settings/text-style").get("fieldName"), "name")
        r_p = layers["parks"].find("renderer-v2")
        self.assertEqual(r_p.get("type"), "categorizedSymbol")
        self.assertEqual([c.get("value") for c in r_p.find("categories")], ["محلی", "شهری", ""])
        self.assertEqual(layers["parks"].find("renderer-v2/symbols/symbol/layer").get("class"), "SimpleFill")
        # پاک‌سازی پروژه‌های آپلودی هم آن را می‌پذیرد
        result = qgis.sanitize(r.content)
        self.assertEqual(sorted(x.table for x in result.layers), ["parks", "schools"])
        self.assertEqual(result.warnings, [])

    def test_publish_as_wms(self):
        self._style()
        r = self.client.post(reverse("maps:publish_ows", args=[self.db.pk, self.m.pk]))
        p = OwsProject.objects.get(service__database=self.db)
        self.assertRedirects(r, reverse("publish:ows_detail", args=[self.db.pk, p.pk]))
        self.assertEqual((p.title, p.is_public), ("مدارس و پارک‌ها", False))
        self.assertEqual(sorted(x["table"] for x in p.layers), ["parks", "schools"])
        self.assertEqual(p.warnings, [])
        text = ows.project_path(p).read_text()
        self.assertIn(f"user='{Provisioner.ows_role_name(self.db.role_name)}'", text)
        self.assertIn("key='gid' srid=4326 type=Point", text)
        # سهمیه WMS/WFS پلن
        r = self.client.post(reverse("maps:publish_ows", args=[self.db.pk, self.m.pk]), follow=True)
        self.assertContains(r, "حداکثر")
        self.assertEqual(OwsProject.objects.count(), 1)

    @unittest.skipUnless(QGIS_BIN, "qgis_mapserver not installed")
    def test_real_qgis_server_renders_map(self):
        self._style()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        proc = subprocess.Popen([QGIS_BIN, f"127.0.0.1:{port}"], env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/ows/?SERVICE=WMS&REQUEST=GetCapabilities", timeout=5)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.5)
        self.m.is_public = True
        self.m.save()
        self.client.post(reverse("maps:publish_ows", args=[self.db.pk, self.m.pk]))
        p = OwsProject.objects.get()
        self.client.logout()
        with override_settings(QGIS_SERVER_URL=f"http://127.0.0.1:{port}/ows/"):
            r = self.client.get(f"/ows/{p.slug}/", {
                "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "all", "STYLES": "",
                "CRS": "EPSG:4326", "BBOX": "35.69,51.29,35.72,51.36", "WIDTH": "300", "HEIGHT": "200",
                "FORMAT": "image/png", "TRANSPARENT": "true"})
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertEqual(r["Content-Type"], "image/png")
            self.assertGreater(len(r.content), 1500)  # تصویر خالی نیست
            r = self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                                                    "TYPENAME": "schools", "OUTPUTFORMAT": "application/json",
                                                    "MAXFEATURES": "2"})
            self.assertEqual(len(json.loads(r.content)["features"]), 2)
