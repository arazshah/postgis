"""مسیرهای وب برداشت میدانی روی PostGIS واقعی (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import io
import json
import os
import unittest
import uuid

import psycopg
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.models import SiteSettings
from databases import services as db_services
from databases.models import DatabaseServer, Member
from databases.provisioner import Provisioner
from publish.models import ApiKey
from survey import services
from survey.models import SurveyProject

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def pt(lon, lat, **props):
    return {"client_uuid": str(uuid.uuid4()), "kind": "point", "srid": 4326,
            "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class SurveyViewTests(TestCase):
    def setUp(self):
        cache.clear()
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.owner = User.objects.create_user("09120000051")
        self.viewer = User.objects.create_user("09120000052")
        self.db = db_services.create_database(self.owner, f"sw_{uuid.uuid4().hex[:8]}", "View-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        plan = self.db.plan
        plan.survey_projects, plan.survey_max_points, plan.gnss_external = 3, 5, True
        plan.save()
        Member.objects.create(database=self.db, phone=self.viewer.phone, user=self.viewer, role="viewer")
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="View-Pass-123",
                       dbname=self.db.db_name, autocommit=True)
        conf = SiteSettings.get()
        conf.survey_enabled = True
        conf.save()
        self.c = Client()
        self.c.force_login(self.owner)
        self.p = services.create_project(self.db, self.owner, "نمونه", 32639, "topo")
        self.base = f"/dashboard/{self.db.pk}/survey/"
        self.sync_url = f"{self.base}{self.p.pk}/sync/"

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _sql(self, q, args=None):
        with psycopg.connect(**self.kw) as c:
            return c.execute(q, args).fetchall()

    def _post(self, url, body, client=None):
        return (client or self.c).post(url, json.dumps(body), content_type="application/json")

    # ---------------------------------------------------------------- پرچم
    def test_flag_off_returns_404_everywhere_and_hides_nav(self):
        conf = SiteSettings.get()
        conf.survey_enabled = False
        conf.save()
        for url in (self.base, f"{self.base}{self.p.pk}/", f"{self.base}{self.p.pk}/data/", f"{self.base}sw.js"):
            self.assertEqual(self.c.get(url).status_code, 404, url)
        self.assertEqual(self.c.post(f"{self.base}new/", {"name": "x", "srid": 4326}).status_code, 404)
        self.assertEqual(self.c.post(f"/api/v1/survey/{self.p.slug}/sync/").status_code, 404)
        r = self.c.get(reverse("databases:detail", args=[self.db.pk]))
        self.assertNotContains(r, "برداشت میدانی")

    def test_flag_on_shows_nav_and_pages_render(self):
        r = self.c.get(reverse("databases:detail", args=[self.db.pk]))
        self.assertContains(r, "برداشت میدانی")
        r = self.c.get(self.base)
        self.assertContains(r, "نمونه")
        r = self.c.get(f"{self.base}{self.p.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "sv-conf")
        self.assertContains(r, "survey/studio.js")
        self.assertEqual(r.context["conf"]["srid"], 32639)
        self.assertEqual(len(r.context["conf"]["codes"]), 6)
        ids = {d["id"] for d in r.context["conf"]["drivers"]}
        self.assertEqual(ids, {"phone-geolocation", "nmea-generic"})

    def test_free_plan_gets_phone_driver_only(self):
        plan = self.db.plan
        plan.gnss_external = False
        plan.save()
        r = self.c.get(f"{self.base}{self.p.pk}/")
        self.assertEqual([d["id"] for d in r.context["conf"]["drivers"]], ["phone-geolocation"])

    def test_service_worker_scope_header(self):
        r = self.c.get(f"{self.base}sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Service-Worker-Allowed"], f"/dashboard/{self.db.pk}/survey/")
        self.assertIn("javascript", r["Content-Type"])

    # ---------------------------------------------------------------- ساخت پروژه
    def test_create_and_archive_flow(self):
        r = self.c.post(f"{self.base}new/", {"name": "پروژه دو", "srid": "32640", "template": "cadastre"})
        self.assertEqual(r.status_code, 302)
        p2 = SurveyProject.objects.get(name="پروژه دو")
        self.assertEqual(p2.srid, 32640)
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{p2.slug}".codes')[0][0], 4)
        r = self.c.post(f"{self.base}new/", {"name": "بد", "srid": "99999"})
        self.assertEqual(SurveyProject.objects.filter(name="بد").count(), 0)
        self.assertEqual(r.status_code, 302)
        r = self.c.post(f"{self.base}{p2.pk}/archive/")
        self.assertEqual(r.status_code, 302)
        p2.refresh_from_db()
        self.assertIsNotNone(p2.archived_at)
        self.assertEqual(self.c.get(f"{self.base}{p2.pk}/").status_code, 404)
        self.assertEqual(self._sql("SELECT count(*) FROM pg_namespace WHERE nspname = %s", (p2.slug,))[0][0], 1)

    def test_viewer_cannot_create_write_or_archive(self):
        v = Client()
        v.force_login(self.viewer)
        self.assertEqual(v.get(f"{self.base}{self.p.pk}/").status_code, 200)
        self.assertEqual(v.get(f"{self.base}{self.p.pk}/data/").status_code, 200)
        self.assertEqual(v.post(f"{self.base}new/", {"name": "x", "srid": "4326"}).status_code, 404)
        self.assertEqual(self._post(self.sync_url, {"items": [pt(51.4, 35.7)]}, v).status_code, 404)
        self.assertEqual(v.post(f"{self.base}{self.p.pk}/archive/").status_code, 404)
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{self.p.slug}".points')[0][0], 0)

    # ---------------------------------------------------------------- همگام‌سازی
    def test_sync_idempotent_with_transform_and_data(self):
        a = pt(51.4, 35.7, pt_no="1", code="GR", fix_quality=4, hdop=0.8, acc_h=0.02, h_ellip=1190.5, evil="x")
        r = self._post(self.sync_url, {"items": [a, a]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["status"] for x in r.json()["results"]], ["ok", "duplicate"])
        x, y, srid = self._sql(f'SELECT ST_X(geom), ST_Y(geom), ST_SRID(geom) FROM "{self.p.slug}".points')[0]
        self.assertEqual(srid, 32639)
        self.assertAlmostEqual(x, 536187.189, places=2)
        self.assertAlmostEqual(y, 3950748.613, places=2)
        d = self.c.get(f"{self.base}{self.p.pk}/data/").json()
        self.assertEqual(d["counts"]["points"], 1)
        f = d["points"]["features"][0]
        self.assertAlmostEqual(f["geometry"]["coordinates"][0], 51.4, places=6)
        self.assertEqual(f["properties"]["pt_no"], "1")
        self.assertAlmostEqual(f["properties"]["x"], 536187.189, places=2)
        self.assertEqual(f["properties"]["captured_by"], self.owner.phone)

    def test_sync_item_errors_do_not_block_others(self):
        good = pt(51.4, 35.7)
        bad_geom = dict(pt(51.4, 35.7), geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]})
        bad_range = pt(51.4, 35.7, fix_quality=99)
        bad_srid = dict(pt(51.4, 35.7), srid=3857)
        bad_id = dict(pt(51.4, 35.7), client_uuid="nope")
        r = self._post(self.sync_url, {"items": [bad_geom, bad_range, bad_srid, bad_id, good]}).json()["results"]
        self.assertEqual([x["status"] for x in r], ["error"] * 4 + ["ok"])
        self.assertEqual([x.get("code") for x in r[:4]], ["geometry", "range", "srid", "invalid"])
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{self.p.slug}".points')[0][0], 1)

    def test_quota_stops_points_at_plan_cap(self):
        items = [pt(51.4 + i * 1e-5, 35.7) for i in range(8)]
        r = self._post(self.sync_url, {"items": items}).json()["results"]
        self.assertEqual([x["status"] for x in r], ["ok"] * 5 + ["error"] * 3)
        self.assertEqual({x.get("code") for x in r[5:]}, {"quota"})
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{self.p.slug}".points')[0][0], 5)

    def test_lines_polygons_sessions_and_soft_delete(self):
        sid = str(uuid.uuid4())
        line = {"client_uuid": str(uuid.uuid4()), "kind": "line", "srid": 4326, "properties": {"code": "RD", "session_id": sid},
                "geometry": {"type": "LineString", "coordinates": [[51.4, 35.7], [51.401, 35.701]]}}
        poly = {"client_uuid": str(uuid.uuid4()), "kind": "polygon", "srid": 4326, "properties": {"code": "BL"},
                "geometry": {"type": "Polygon", "coordinates": [[[51.4, 35.7], [51.401, 35.7], [51.401, 35.701], [51.4, 35.7]]]}}
        p1 = pt(51.4, 35.7)
        session = {"client_uuid": sid, "kind": "session", "properties": {"name": "روز اول", "driver_id": "phone-geolocation"}}
        r = self._post(self.sync_url, {"items": [session, line, poly, p1]}).json()["results"]
        self.assertEqual([x["status"] for x in r], ["ok"] * 4)
        again = self._post(self.sync_url, {"items": [session]}).json()["results"]
        self.assertEqual(again[0]["status"], "duplicate")
        d = self.c.get(f"{self.base}{self.p.pk}/data/").json()
        self.assertEqual([d["counts"][k] for k in ("points", "lines", "polygons")], [1, 1, 1])
        dele = {"client_uuid": p1["client_uuid"], "kind": "point", "op": "delete"}
        self.assertEqual(self._post(self.sync_url, {"items": [dele]}).json()["results"][0]["status"], "ok")
        self.assertEqual(self._post(self.sync_url, {"items": [dele]}).json()["results"][0]["status"], "missing")
        self.assertEqual(self.c.get(f"{self.base}{self.p.pk}/data/").json()["counts"]["points"], 0)
        # ردیف حذف نرم است، پاک نشده
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{self.p.slug}".points')[0][0], 1)

    def test_bad_bodies(self):
        self.assertEqual(self.c.post(self.sync_url, "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self._post(self.sync_url, {"items": "x"}).status_code, 400)
        self.assertEqual(self._post(self.sync_url, {"items": [pt(1, 1)] * 1001}).status_code, 413)

    # ---------------------------------------------------------------- کلید API
    def test_api_key_sync(self):
        url = f"/api/v1/survey/{self.p.slug}/sync/"
        item = pt(51.4, 35.7, pt_no="K1")
        body = json.dumps({"items": [item]})
        anon = Client()
        self.assertEqual(anon.post(url, body, content_type="application/json").status_code, 401)
        _k, rkey = ApiKey.issue(self.db, self.owner, "ro")
        _k, wkey = ApiKey.issue(self.db, self.owner, "rw", can_write=True)
        r = anon.post(url, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {rkey}")
        self.assertEqual(r.status_code, 403)
        r = anon.post(url, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {wkey}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["results"][0]["status"], "ok")
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
        self.assertEqual(self._sql(f'SELECT captured_by FROM "{self.p.slug}".points')[0][0], "rw")
        # پروژه‌ی بایگانی‌شده یا ناشناخته
        r = anon.post("/api/v1/survey/s_zzzzzzzz/sync/", body, content_type="application/json",
                      HTTP_AUTHORIZATION=f"Bearer {wkey}")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(anon.options(url).status_code, 204)

    # ---------------------------------------------------------------- ورود و خروجی
    def test_import_csv_and_geojson_then_exports(self):
        csv_body = b"P1,536187.19,3950748.61,1190.5,GR\nP2,536200,3950760,1191,BL\nbad,x,y\n"
        r = self.c.post(f"{self.base}{self.p.pk}/import/", {"file": SimpleUploadedFile("pts.csv", csv_body),
                                                           "order": "pen", "crs": "project"})
        d = r.json()
        self.assertEqual((d["imported"], d["skipped"]), (2, 1), d)
        x, y = self._sql(f'SELECT ST_X(geom), ST_Y(geom) FROM "{self.p.slug}".points WHERE pt_no = \'P1\'')[0]
        self.assertAlmostEqual(x, 536187.19, places=2)
        gj = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.4, 35.7]}, "properties": {"pt_no": "G1"}},
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[51.4, 35.7], [51.41, 35.71]]}, "properties": {"code": "RD"}},
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[51.4, 35.7], [51.41, 35.7], [51.41, 35.71], [51.4, 35.7]]]}, "properties": {}}]}
        r = self.c.post(f"{self.base}{self.p.pk}/import/", {"file": SimpleUploadedFile("a.geojson", json.dumps(gj).encode())})
        self.assertEqual(r.json()["imported"], 3)
        self.assertEqual(self.c.post(f"{self.base}{self.p.pk}/import/", {"file": SimpleUploadedFile("e.csv", b"")}).status_code, 400)
        self.assertEqual(self.c.post(f"{self.base}{self.p.pk}/import/", {}).status_code, 400)

        csv_out = self.c.get(f"{self.base}{self.p.pk}/export/csv/")
        self.assertIn("text/csv", csv_out["Content-Type"])
        text = csv_out.content.decode("utf-8-sig")
        self.assertIn("P1,536187.19", text)
        self.assertEqual(len(text.strip().splitlines()), 4)
        geo = self.c.get(f"{self.base}{self.p.pk}/export/geojson/").json()
        self.assertEqual(len(geo["features"]), 5)
        dxf = self.c.get(f"{self.base}{self.p.pk}/export/dxf/").content.decode()
        self.assertTrue(dxf.rstrip().endswith("EOF"))
        self.assertIn("536187.1900", dxf)
        self.assertIn("POLYLINE", dxf)
        rep = self.c.get(f"{self.base}{self.p.pk}/export/report/")
        self.assertContains(rep, "P1")
        self.assertEqual(self.c.get(f"{self.base}{self.p.pk}/export/xlsx/").status_code, 404)

    def test_import_respects_point_quota(self):
        rows = "\n".join(f"{i},{536000 + i},3950000,10,GR" for i in range(9)).encode()
        d = self.c.post(f"{self.base}{self.p.pk}/import/", {"file": SimpleUploadedFile("p.csv", rows)}).json()
        self.assertEqual((d["imported"], d["failed"], d["quota"]), (5, 4, True))

    # ---------------------------------------------------------------- COGO
    def test_cogo_endpoint(self):
        u = f"{self.base}{self.p.pk}/cogo/"
        r = self._post(u, {"op": "inverse", "from": [0, 0], "to": [3, 4]}).json()
        self.assertAlmostEqual(r["distance"], 5)
        r = self._post(u, {"op": "area", "ring": [[0, 0], [10, 0], [10, 10], [0, 10]]}).json()
        self.assertAlmostEqual(r["area"], 100)
        r = self._post(u, {"op": "traverse", "start": [0, 0], "azimuth": 0, "close": [0, 0],
                           "legs": [[0, 100], [90, 100], [90, 100], [90, 100]]}).json()
        self.assertIsNone(r["precision"])  # بسته‌شدن کامل: بی‌نهایت در JSON نمی‌آید
        self.assertEqual(self._post(u, {"op": "area", "ring": [[0, 0]]}).status_code, 400)
        self.assertEqual(self._post(u, {"op": "nope"}).status_code, 400)
        self.assertEqual(self._post(u, {"op": "inverse", "from": "x"}).status_code, 400)
        self.assertEqual(Client().post(u, "{}", content_type="application/json").status_code, 302)

    # ---------------------------------------------------------------- یکپارچگی با بقیه سایت
    def test_survey_tables_work_with_other_features(self):
        self._post(self.sync_url, {"items": [pt(51.4, 35.7, pt_no="M1")]})
        from maps import services as map_services

        keys = {t["key"] for t in map_services.spatial_tables(self.db)} if isinstance(
            map_services.spatial_tables(self.db)[0], dict) else {t.key for t in map_services.spatial_tables(self.db)}
        self.assertIn(f"{self.p.slug}.points", keys)
        buf = io.StringIO()
        buf.write("ok")
