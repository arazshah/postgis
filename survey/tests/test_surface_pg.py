"""سطح و منحنی میزان روی PostGIS واقعی (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import json
import os
import unittest
import uuid

import psycopg
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from accounts.models import User
from core.models import SiteSettings
from databases import services as db_services
from databases.models import DatabaseServer, Member
from databases.provisioner import Provisioner
from survey import services

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def point(e, n, h, **extra):
    return {"client_uuid": str(uuid.uuid4()), "kind": "point", "srid": 32639,
            "geometry": {"type": "Point", "coordinates": [e, n]}, "properties": {"h_ortho": h, **extra}}


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class SurfaceViewTests(TestCase):
    def setUp(self):
        cache.clear()
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.owner = User.objects.create_user("09120000071")
        self.viewer = User.objects.create_user("09120000072")
        self.db = db_services.create_database(self.owner, f"ss_{uuid.uuid4().hex[:8]}", "Surf-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        plan = self.db.plan
        plan.survey_projects, plan.survey_max_points = 3, 1000
        plan.save()
        Member.objects.create(database=self.db, phone=self.viewer.phone, user=self.viewer, role="viewer")
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Surf-Pass-123",
                       dbname=self.db.db_name, autocommit=True)
        conf = SiteSettings.get()
        conf.survey_enabled = True
        conf.save()
        self.c = Client()
        self.c.force_login(self.owner)
        self.p = services.create_project(self.db, self.owner, "سطح", 32639, "topo")
        self.base = f"/dashboard/{self.db.pk}/survey/{self.p.pk}/"

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _sql(self, q, args=None):
        with psycopg.connect(**self.kw) as c:
            return c.execute(q, args).fetchall()

    def _post(self, url, body, client=None):
        return (client or self.c).post(url, json.dumps(body), content_type="application/json")

    def _grid(self, n=6, step=10.0, slope=0.1):
        items = [point(500000 + i * step, 3950000 + j * step, i * step * slope) for i in range(n) for j in range(n)]
        r = self._post(f"{self.base}sync/", {"items": items})
        self.assertTrue(all(x["status"] == "ok" for x in r.json()["results"]), r.content)

    def test_tin_stats_contours_and_volume_match_the_analytic_plane(self):
        self._grid()  # z = 0.1·E_rel روی مربع ۵۰×۵۰ متر ⇒ z از ۰ تا ۵
        r = self._post(f"{self.base}surface/", {"interval": 1, "ref": 2.5})
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        st = out["stats"]
        self.assertEqual((st["points"], st["triangles"]), (36, 50))
        self.assertAlmostEqual(st["area"], 2500.0, places=3)
        self.assertEqual((st["z_min"], st["z_max"]), (0.0, 5.0))
        self.assertAlmostEqual(st["volume"]["cut"], 50 * 31.25, places=3)  # ۵۰ متر عرض × ∫ از E=۲۵ تا ۵۰ از (۰٫۱E − ۲٫۵)
        self.assertAlmostEqual(st["volume"]["net"], 0.0, places=3)
        levels = sorted({f["properties"]["level"] for f in out["contours"]["features"]})
        self.assertEqual(levels, [1.0, 2.0, 3.0, 4.0, 5.0])
        # منحنی‌ها WGS84اند و در منطقه ۳۹ شمالی (حدود ۵۱°E–۵۴°E) قرار می‌گیرند
        lon, lat = out["contours"]["features"][0]["geometry"]["coordinates"][0]
        self.assertTrue(50 < lon < 55 and 35 < lat < 36, (lon, lat))

    def test_auto_interval_when_blank(self):
        self._grid()
        out = self._post(f"{self.base}surface/", {}).json()
        self.assertEqual(out["stats"]["interval"], 0.5)

    def test_duplicate_shots_are_averaged_not_breaking_the_tin(self):
        self._grid(n=3)
        self._post(f"{self.base}sync/", {"items": [point(500000, 3950000, 1.0), point(500000, 3950000, 3.0)]})
        r = self._post(f"{self.base}surface/", {"interval": 0.5})
        self.assertEqual(r.status_code, 200, r.content)
        st = r.json()["stats"]
        self.assertEqual((st["points"], st["locations"]), (11, 9))  # ۱۱ نقطه، ۹ مکان یکتا

    def test_save_creates_plain_postgis_table_and_replaces_it(self):
        self._grid()
        r = self._post(f"{self.base}surface/", {"interval": 1, "save": True}).json()
        self.assertEqual(r["table"], f"{self.p.slug}.contours")
        n1 = self._sql(f'SELECT count(*), min(level), max(level), bool_or(is_index), min(ST_SRID(geom)) FROM "{self.p.slug}".contours')[0]
        self.assertEqual(n1[0], r["saved"])
        self.assertEqual((n1[1], n1[2], n1[4]), (1.0, 5.0, 32639))
        self._post(f"{self.base}surface/", {"interval": 2, "save": True})
        n2 = self._sql(f'SELECT count(*) FROM "{self.p.slug}".contours')[0][0]
        self.assertLess(n2, n1[0])  # جایگزین شد، اضافه نشد

    def test_viewer_can_compute_but_not_save(self):
        self._grid()
        v = Client()
        v.force_login(self.viewer)
        self.assertEqual(self._post(f"{self.base}surface/", {"interval": 1}, client=v).status_code, 200)
        r = self._post(f"{self.base}surface/", {"interval": 1, "save": True}, client=v)
        self.assertEqual(r.status_code, 403)
        with self.assertRaises(psycopg.errors.UndefinedTable):
            self._sql(f'SELECT 1 FROM "{self.p.slug}".contours')

    def test_dxf_export_has_elevations_layers_and_labels(self):
        self._grid()
        r = self.c.get(f"{self.base}export/contours/?interval=1&index_every=2")
        self.assertEqual(r.status_code, 200)
        text = r.content.decode()
        for needle in ("AC1009", "CONTOUR_INDEX", "CONTOUR", "CONTOUR_LABEL", "POLYLINE", "\n30\n2.0000\n"):
            self.assertIn(needle, text)

    def test_friendly_errors(self):
        r = self._post(f"{self.base}surface/", {})
        self.assertEqual(r.status_code, 400)
        self.assertIn("۳ نقطه", r.json()["message"])
        self._grid()
        self.assertEqual(self._post(f"{self.base}surface/", {"max_edge": 1}).status_code, 400)  # همه مثلث‌ها بلندترند
        self.assertEqual(self._post(f"{self.base}surface/", {"interval": "abc"}).status_code, 400)
        self.assertEqual(self._post(f"{self.base}surface/", {"interval": 0.0001}).status_code, 400)  # بیش از سقف منحنی
        self.assertEqual(self._post(f"{self.base}surface/", {"field": "geom; DROP"}).status_code, 400)
        self.assertEqual(self.c.get(f"{self.base}export/contours/?interval=-1").status_code, 302)

    def test_flag_off(self):
        conf = SiteSettings.get()
        conf.survey_enabled = False
        conf.save()
        self.assertEqual(self._post(f"{self.base}surface/", {}).status_code, 404)

    def _session_points(self, name, h):
        sid = str(uuid.uuid4())
        items = [{"client_uuid": sid, "kind": "session", "name": name}]
        for i in range(6):
            for j in range(6):
                it = point(500000 + i * 10, 3950000 + j * 10, h)
                it["properties"]["session_id"] = sid
                items.append(it)
        r = self._post(f"{self.base}sync/", {"items": items})
        self.assertTrue(all(x["status"] == "ok" for x in r.json()["results"]), r.content)
        return sid

    def test_volume_between_two_sessions(self):
        old = self._session_points("قبل", 10.0)
        new = self._session_points("بعد", 12.0)
        sess = self.c.get(f"{self.base}surface/sessions/").json()["sessions"]
        self.assertEqual({s["id"] for s in sess}, {old, new})
        self.assertTrue(all(s["points"] == 36 for s in sess))
        out = self._post(f"{self.base}surface/", {"session": new, "compare": old, "interval": 1}).json()
        b = out["stats"]["between"]
        self.assertEqual(out["stats"]["points"], 36)  # فقط برداشت جدید
        self.assertAlmostEqual(b["added"], 2.0 * 2500, delta=2500 * 2 * 0.01)  # ۵۰×۵۰ متر × ۲ متر
        self.assertAlmostEqual(b["removed"], 0.0, places=6)
        # برعکس: کاهش
        rev = self._post(f"{self.base}surface/", {"session": old, "compare": new, "interval": 1}).json()["stats"]["between"]
        self.assertAlmostEqual(rev["removed"], b["added"], delta=1)
        self.assertEqual(self._post(f"{self.base}surface/", {"compare": "not-a-uuid"}).status_code, 400)
        self.assertEqual(self._post(f"{self.base}surface/", {"compare": str(uuid.uuid4())}).status_code, 400)
