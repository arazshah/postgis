"""WMS/WFS با QGIS Server: پاک‌سازی پروژه، نقش فقط‌خواندنی، پراکسی و دسترسی."""
import io
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
import zipfile
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import psycopg
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from publish import ows, qgis
from publish.models import ApiKey, DailyUsage, OwsProject

PG_HOST = os.environ.get("TEST_PG_HOST", "")
FIXTURE = Path(__file__).parent / "fixtures" / "tehran.qgs"
QGIS_BIN = shutil.which("qgis_mapserver")


class SanitizeTests(SimpleTestCase):
    def setUp(self):
        self.result = qgis.sanitize(FIXTURE.read_bytes())

    def test_only_postgis_layers_kept(self):
        self.assertEqual(sorted(x.table for x in self.result.layers), ["neighborhoods", "parks", "schools"])
        self.assertEqual(self.result.title, "نقشه مدارس تهران")
        joined = " ".join(self.result.warnings)
        self.assertIn("OSM", joined)
        self.assertIn("secret", joined)
        self.assertIn("ماکرو", joined)

    def test_no_credentials_files_or_code_left(self):
        xml = self.result.xml
        for bad in ("fixture-secret-pw", "desktop_user", "192.168.1.20", "my_local_gis", "/etc/passwd",
                    "os.system", "tile.openstreetmap.org", "delimitedtext"):
            self.assertNotIn(bad, xml, bad)
        self.assertEqual(xml.count(qgis.PLACEHOLDER), 6)  # منبع لایه + درخت لایه، برای هر سه لایه
        self.assertIn('<WMSRootName type="QString">all</WMSRootName>', xml)

    def test_render_inserts_escaped_connection(self):
        conn = qgis.connection_string("db", 5432, "gp_x", "gp_x_ows", "p&ss'\"w", "require")
        out = qgis.render(self.result.xml, conn)
        self.assertNotIn(qgis.PLACEHOLDER, out)
        self.assertIn("password='p&amp;ss\\'&quot;w'", out)
        self.assertIn("user='gp_x_ows'", out)

    def test_wfs_toggle(self):
        off = qgis.sanitize(FIXTURE.read_bytes(), wfs=False)
        self.assertRegex(off.xml, r'<WFSLayers type="QStringList"\s*/>')
        self.assertIn("<value>", self.result.xml.split("<WFSLayers")[1].split("</WFSLayers>")[0])

    def test_qgz_and_bad_files(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("p.qgs", FIXTURE.read_bytes())
            zf.writestr("p_styles.db", b"x")
        self.assertEqual(qgis.read_project_bytes(buf.getvalue(), "p.qgz"), FIXTURE.read_bytes())
        with self.assertRaises(qgis.ProjectError):
            qgis.sanitize(b"<html></html>")
        with self.assertRaises(qgis.ProjectError):
            qgis.sanitize(b'<?xml version="1.0"?><!DOCTYPE qgis [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                          b'<qgis version="3.34">&x;</qgis>')
        with self.assertRaises(qgis.ProjectError):  # بدون لایه PostGIS
            qgis.sanitize(b'<qgis version="3.34.4"><projectlayers/></qgis>')

    def test_parse_uri(self):
        p = qgis.parse_uri("dbname='a b' host=h port=5 user='u' password='p\\'q' key='gid' srid=4326 type=Point "
                           "checkPrimaryKeyUnicity='1' table=\"my \"\"s\"\"\".\"t 1\" (the_geom) sql=\"x\" = 'a b'")
        self.assertEqual((p["schema"], p["table"], p["geom"], p["sql"]), ('my "s"', "t 1", "the_geom", "\"x\" = 'a b'"))
        self.assertEqual(p["params"]["password"], "p'q")
        out = qgis.build_uri(p, "CONN")
        self.assertTrue(out.startswith("CONN key='gid' srid=4326 type=Point"))
        self.assertNotIn("password", out)
        self.assertIn('table="my ""s"""."t 1" (the_geom)', out)


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"], SITE_URL="https://postgis.example",
                   QGIS_SERVER_URL="http://qgis.internal/ows/")
class OwsIntegrationTests(TestCase):
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
        self.user = User.objects.create_user("09120000094")
        self.db = db_services.create_database(self.user, f"ow_{uuid.uuid4().hex[:8]}", "Ows-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        with psycopg.connect(host=server.host, port=server.port, user=self.db.role_name, password="Ows-Pass-123",
                             dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE schools(gid serial PRIMARY KEY, name text, students int, geom geometry(Point, 4326))")
            c.execute("INSERT INTO schools(name, students, geom) SELECT 'مدرسه ' || g, g * 10, "
                      "ST_SetSRID(ST_MakePoint(51.3 + g * 0.002, 35.7), 4326) FROM generate_series(1, 20) g")
            c.execute("CREATE TABLE parks(gid serial PRIMARY KEY, name text, geom geometry(MultiPolygon, 4326))")
            c.execute("INSERT INTO parks(name, geom) VALUES ('پارک', ST_Multi(ST_Buffer(ST_SetSRID("
                      "ST_MakePoint(51.32, 35.71), 4326), 0.005)))")
        self.client.force_login(self.user)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _upload(self, public=False):
        data = {"file": SimpleUploadedFile("tehran.qgs", FIXTURE.read_bytes())}
        if public:
            data["public"] = "on"
        r = self.client.post(reverse("publish:ows", args=[self.db.pk]), data)
        project = OwsProject.objects.get(service__database=self.db)
        self.assertRedirects(r, reverse("publish:ows_detail", args=[self.db.pk, project.pk]))
        return project

    def test_upload_writes_project_with_readonly_role(self):
        p = self._upload()
        self.assertEqual([x["table"] for x in p.layers], ["parks", "neighborhoods", "schools"])
        self.assertTrue(any("neighborhoods" in w for w in p.warnings))  # جدول در پایگاه داده نیست
        self.assertAlmostEqual(p.bbox[1], 35.70, places=2)
        self.assertNotIn("password=", p.xml)  # نسخه پایگاه داده بدون رمز
        text = ows.project_path(p).read_text()
        ows_role = Provisioner.ows_role_name(self.db.role_name)
        self.assertIn(f"user='{ows_role}'", text)
        self.assertIn("https://postgis.example/ows/", text)
        password = ows.ows_password(p.service)
        with psycopg.connect(host=self.server.host, port=self.server.port, user=ows_role, password=password,
                             dbname=self.db.db_name, autocommit=True) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM schools").fetchone()[0], 20)
            with self.assertRaises(psycopg.Error):
                c.execute("INSERT INTO schools(name) VALUES ('x')")
            with self.assertRaises(psycopg.Error):
                c.execute("SET transaction_read_only = off; CREATE TABLE evil(id int)")
        # به هیچ پایگاه داده دیگری (حتی دیتابیس‌هایی که مدیر جدا ساخته) وصل نمی‌شود
        admin = dict(host=self.server.host, port=self.server.port, user=os.environ.get("TEST_PG_USER", "postgres"),
                     password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **admin) as c:
            c.execute("DROP DATABASE IF EXISTS gp_other_app")
            c.execute("CREATE DATABASE gp_other_app")
        self.addCleanup(lambda: psycopg.connect(dbname="postgres", **admin).execute("DROP DATABASE gp_other_app"))
        Provisioner.for_server(self.server).harden()
        for other in ("postgres", "gp_other_app"):
            with self.assertRaises(psycopg.OperationalError):
                psycopg.connect(host=self.server.host, port=self.server.port, user=ows_role, password=password,
                                dbname=other).close()

    def test_plan_limit_and_bad_file(self):
        r = self.client.post(reverse("publish:ows", args=[self.db.pk]),
                             {"file": SimpleUploadedFile("x.qgs", b"<qgis version='3.34'><projectlayers/></qgis>")},
                             follow=True)
        self.assertContains(r, "هیچ لایه‌ای از پایگاه داده")
        self._upload()
        r = self.client.post(reverse("publish:ows", args=[self.db.pk]),
                             {"file": SimpleUploadedFile("t.qgs", FIXTURE.read_bytes())}, follow=True)
        self.assertContains(r, "حداکثر ۱ پروژه")

    def _fetch_ok(self, body=b"<WMS_Capabilities/>", ctype="text/xml"):
        return mock.patch.object(ows, "_fetch", return_value=(200, ctype, body))

    def test_proxy_access_and_params(self):
        p = self._upload()
        url = f"/ows/{p.slug}/"
        self.client.logout()
        with self._fetch_ok() as f:
            r = self.client.get(url, {"SERVICE": "WMS", "REQUEST": "GetCapabilities"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(self.client.get(url, {"SERVICE": "WMS", "REQUEST": "GetCapabilities",
                                                   "key": "gpk_wrong"}).status_code, 403)
            _key, raw = ApiKey.issue(self.db, self.user, "qgis")
            r = self.client.get(url, {"service": "WMS", "request": "GetMap", "key": raw, "MAP": "/etc/passwd",
                                      "LAYERS": "all"})
            self.assertEqual(r.status_code, 200)
            upstream, headers = f.call_args[0]
            q = parse_qs(urlparse(upstream).query)
            self.assertEqual(q["MAP"], [str(ows.project_path(p))])
            self.assertNotIn("KEY", q)
            self.assertEqual(headers["X-Qgis-Service-Url"], f"https://postgis.example/ows/{p.slug}/")
            # درخواست‌های غیرمجاز به QGIS Server نمی‌رسند
            calls = f.call_count
            for bad in ({"SERVICE": "WMS", "REQUEST": "GetPrint"}, {"SERVICE": "WFS", "REQUEST": "Transaction"},
                        {"SERVICE": "WCS", "REQUEST": "GetCoverage"}, {"REQUEST": "GetMap"},
                        {"SERVICE": "WMS", "REQUEST": "GetMap", "FILTER": "مدارس:\"gid\" = 1; DROP TABLE x"}):
                self.assertEqual(self.client.get(url, {**bad, "key": raw}).status_code, 400, bad)
            self.assertEqual(f.call_count, calls)
            # WFS: سقف تعداد عوارض
            self.client.get(url, {"SERVICE": "WFS", "REQUEST": "GetFeature", "TYPENAME": "مدارس", "key": raw})
            self.assertEqual(parse_qs(urlparse(f.call_args[0][0]).query)["MAXFEATURES"], ["10000"])
            self.client.get(url, {"SERVICE": "WFS", "REQUEST": "GetFeature", "MAXFEATURES": "999999", "key": raw})
            self.assertEqual(parse_qs(urlparse(f.call_args[0][0]).query)["MAXFEATURES"], ["10000"])
        self.assertGreaterEqual(DailyUsage.objects.get(database=self.db).requests, 3)

    def test_capabilities_keep_key_and_public_toggle(self):
        p = self._upload()
        base = f"https://postgis.example/ows/{p.slug}/"
        body = f'<OnlineResource xlink:href="{base}?"/><Get xlink:href="{base}"/>'.encode()
        _key, raw = ApiKey.issue(self.db, self.user, "k")
        self.client.logout()
        with self._fetch_ok(body):
            r = self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WMS", "REQUEST": "GetCapabilities", "key": raw})
        self.assertIn(f'{base}?key={raw}&amp;"'.encode(), r.content)
        self.assertIn(f'{base}?key={raw}"'.encode(), r.content)
        self.client.force_login(self.user)
        self.client.post(reverse("publish:ows_detail", args=[self.db.pk, p.pk]),
                         {"title": "نقشه", "public": "on"})  # WFS خاموش
        p.refresh_from_db()
        self.assertTrue(p.is_public)
        self.assertFalse(p.wfs_enabled)
        self.client.logout()
        with self._fetch_ok():
            self.assertEqual(self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WMS", "REQUEST": "GetMap"}).status_code,
                             200)
            self.assertEqual(self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WFS", "REQUEST": "GetFeature"})
                             .status_code, 400)

    def test_upstream_down_and_inactive_database(self):
        p = self._upload(public=True)
        self.client.logout()
        with mock.patch.object(ows, "_fetch", side_effect=TimeoutError):
            r = self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WMS", "REQUEST": "GetMap"})
        self.assertEqual(r.status_code, 504)
        self.db.status = "suspended"
        self.db.save(update_fields=["status"])
        with self._fetch_ok():
            self.assertEqual(self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WMS", "REQUEST": "GetMap"}).status_code,
                             403)

    def test_project_saved_in_database(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("tehran.qgs", FIXTURE.read_bytes())
        with psycopg.connect(host=self.server.host, port=self.server.port, user=self.db.role_name,
                             password="Ows-Pass-123", dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE qgis_projects(name text PRIMARY KEY, metadata jsonb, content bytea)")
            c.execute("INSERT INTO qgis_projects VALUES ('نقشه من', '{}', %s)", (buf.getvalue(),))
        r = self.client.get(reverse("publish:ows", args=[self.db.pk]))
        self.assertContains(r, "نقشه من")
        r = self.client.post(reverse("publish:ows_import_saved", args=[self.db.pk]),
                             {"schema": "public", "name": "نقشه من"})
        p = OwsProject.objects.get()
        self.assertEqual((p.source, p.source_name), ("database", "نقشه من"))
        self.client.post(reverse("publish:ows_refresh", args=[self.db.pk, p.pk]))
        self.assertEqual(OwsProject.objects.get().layers, p.layers)

    def test_delete_database_removes_files(self):
        p = self._upload()
        path = ows.project_path(p)
        self.assertTrue(path.exists())
        db_services.delete_database(self.db)
        self.assertFalse(path.exists())

    @unittest.skipUnless(QGIS_BIN, "qgis_mapserver not installed")
    def test_real_qgis_server_renders(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QGIS_SERVER_IGNORE_BAD_LAYERS": "true"}
        proc = subprocess.Popen([QGIS_BIN, f"127.0.0.1:{port}"], env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        deadline = time.time() + 60  # آغاز QGIS زیر بار ممکن است چند ثانیه طول بکشد
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/ows/?SERVICE=WMS&REQUEST=GetCapabilities", timeout=5)
                break
            except urllib.error.HTTPError:
                break  # سرور بالا است (بدون MAP خطا می‌دهد)
            except OSError:
                time.sleep(0.5)
        p = self._upload(public=True)
        self.client.logout()
        with override_settings(QGIS_SERVER_URL=f"http://127.0.0.1:{port}/ows/"):
            r = self.client.get(f"/ows/{p.slug}/", {
                "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "all", "STYLES": "",
                "CRS": "EPSG:4326", "BBOX": "35.69,51.29,35.72,51.35", "WIDTH": "300", "HEIGHT": "200",
                "FORMAT": "image/png", "TRANSPARENT": "true"})
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertEqual(r["Content-Type"], "image/png")
            r = self.client.get(f"/ows/{p.slug}/", {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
                                                    "TYPENAME": "مدارس", "OUTPUTFORMAT": "application/json",
                                                    "MAXFEATURES": "2"})
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertEqual(len(r.json()["features"]), 2)
