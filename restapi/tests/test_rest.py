"""REST API جدول‌ها و فرم میدانی روی PostGIS واقعی."""
import json
import os
import unittest
import uuid

import psycopg
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases import team
from databases.models import DatabaseServer, Plan
from databases.provisioner import Provisioner
from publish.models import ApiKey, DailyUsage, Service
from restapi.models import ApiTable, FieldForm

PG_HOST = os.environ.get("TEST_PG_HOST", "")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class RestTests(TestCase):
    def setUp(self):
        cache.clear()
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.owner = User.objects.create_user("09120000031")
        self.db = db_services.create_database(self.owner, f"rs_{uuid.uuid4().hex[:8]}", "Rest-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Rest-Pass-123",
                       dbname=self.db.db_name, autocommit=True)
        with psycopg.connect(**self.kw) as c:
            c.execute("CREATE TABLE trees(id serial PRIMARY KEY, species text NOT NULL, height numeric, healthy boolean,"
                      " planted date, geom geometry(Point, 32639))")
            c.execute("INSERT INTO trees(species, height, healthy, geom) SELECT 'چنار', g, g % 2 = 0, "
                      "ST_Transform(ST_SetSRID(ST_MakePoint(51.38 + g * 0.001, 35.70), 4326), 32639) "
                      "FROM generate_series(1, 30) g")
            c.execute("CREATE TABLE notes(id int PRIMARY KEY, body text)")
        self.svc = Service.objects.create(database=self.db)
        self.trees = ApiTable.objects.create(service=self.svc, table="trees", can_insert=True, can_update=True,
                                             can_delete=True)
        self.url = f"/rest/{self.svc.slug}/trees/"
        _k, self.rkey = ApiKey.issue(self.db, self.owner, "read")
        _k, self.wkey = ApiKey.issue(self.db, self.owner, "write", can_write=True)
        self.anon = Client()

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _h(self, key):
        return {"HTTP_AUTHORIZATION": f"Bearer {key}"}

    def _sql(self, q):
        with psycopg.connect(**self.kw) as c:
            return c.execute(q).fetchall()

    def test_read_filters_and_auth(self):
        self.assertEqual(self.anon.get(self.url).status_code, 401)
        r = self.anon.get(self.url, {"limit": 5, "order": "-height"}, **self._h(self.rkey))
        self.assertEqual(r.status_code, 200)
        fc = r.json()
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertEqual(len(fc["features"]), 5)
        f = fc["features"][0]
        self.assertEqual(f["properties"]["height"], 30)
        self.assertAlmostEqual(f["geometry"]["coordinates"][1], 35.70, places=3)  # برگردانده به WGS84
        self.assertEqual(f["id"], f["properties"]["id"])
        r = self.anon.get(self.url, {"height__gte": "25", "healthy": "true"}, **self._h(self.rkey))
        self.assertEqual(len(r.json()["features"]), 3)
        r = self.anon.get(self.url, {"species__like": "*نار", "id__in": "1,2,3"}, **self._h(self.rkey))
        self.assertEqual(len(r.json()["features"]), 3)
        r = self.anon.get(self.url, {"bbox": "51.380,35.69,51.3855,35.71"}, **self._h(self.rkey))
        self.assertEqual(len(r.json()["features"]), 5)
        r = self.anon.get(self.url + "7/", **self._h(self.rkey))
        self.assertEqual(r.json()["properties"]["id"], 7)
        for bad in ({"nope": "1"}, {"height__regex": "x"}, {"order": "geom"}, {"bbox": "1,2"}):
            self.assertEqual(self.anon.get(self.url, bad, **self._h(self.rkey)).status_code, 400, bad)
        self.assertEqual(self.anon.get(self.url + "999/", **self._h(self.rkey)).status_code, 404)
        # جدول باز نشده
        self.assertEqual(self.anon.get(f"/rest/{self.svc.slug}/notes/", **self._h(self.rkey)).status_code, 404)
        # خواندن عمومی
        self.trees.public_read = True
        self.trees.save()
        self.assertEqual(self.anon.get(self.url).status_code, 200)
        self.assertGreater(DailyUsage.objects.get(database=self.db).requests, 5)
        r = self.anon.options(self.url)
        self.assertIn("PATCH", r["Access-Control-Allow-Methods"])

    def test_write(self):
        feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.41, 35.72]},
                "properties": {"species": "کاج", "height": 3.5, "planted": "2026-03-21"}}
        body = json.dumps(feat, ensure_ascii=False)
        r = self.anon.post(self.url, body, content_type="application/json", **self._h(self.rkey))
        self.assertEqual(r.status_code, 403)  # کلید فقط‌خواندنی
        r = self.anon.post(self.url, body, content_type="application/json")
        self.assertEqual(r.status_code, 401)
        r = self.anon.post(self.url, body, content_type="application/json", **self._h(self.wkey))
        self.assertEqual(r.status_code, 201, r.content)
        new = r.json()
        self.assertEqual(new["properties"]["species"], "کاج")
        srid, x = self._sql(f"SELECT ST_SRID(geom), ST_X(ST_Transform(geom, 4326)) FROM trees WHERE id = {new['id']}")[0]
        self.assertEqual(srid, 32639)
        self.assertAlmostEqual(x, 51.41, places=5)
        r = self.anon.post(self.url, json.dumps({"height": 2}), content_type="application/json", **self._h(self.wkey))
        self.assertContains(r, "species", status_code=400)  # NOT NULL
        r = self.anon.post(self.url, json.dumps({"species": "x", "evil": 1}), content_type="application/json",
                           **self._h(self.wkey))
        self.assertContains(r, "ناشناخته", status_code=400)
        r = self.anon.post(self.url, json.dumps({"species": "x", "height": "بلند"}), content_type="application/json",
                           **self._h(self.wkey))
        self.assertEqual(r.status_code, 400)
        r = self.anon.patch(self.url + f"{new['id']}/", json.dumps({"height": 4, "healthy": True}),
                            content_type="application/json", **self._h(self.wkey))
        self.assertEqual(r.json()["properties"]["height"], 4)
        r = self.anon.delete(self.url + f"{new['id']}/", **self._h(self.wkey))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._sql("SELECT count(*) FROM trees")[0][0], 30)
        self.trees.can_delete = False
        self.trees.save()
        self.assertEqual(self.anon.delete(self.url + "1/", **self._h(self.wkey)).status_code, 405)
        # SQL injection در نام و مقدار
        r = self.anon.get(self.url, {"species": "x'; DROP TABLE trees; --"}, **self._h(self.rkey))
        self.assertEqual(r.json()["features"], [])
        self.assertEqual(self._sql("SELECT count(*) FROM trees")[0][0], 30)

    def test_manage_page(self):
        c = Client()
        c.force_login(self.owner)
        url = reverse("restapi:manage", args=[self.db.pk])
        self.assertContains(c.get(url), "trees")
        c.post(url, {"action": "save_table", "table": "public.notes", "enabled": "on", "public_read": "on"})
        self.assertTrue(ApiTable.objects.get(table="notes").public_read)
        self.assertEqual(self.anon.get(f"/rest/{self.svc.slug}/notes/").json()["rows"], [])
        c.post(url, {"action": "save_table", "table": "public.notes"})
        self.assertFalse(ApiTable.objects.filter(table="notes").exists())
        viewer = User.objects.create_user("09120000032")
        self.db.plan = Plan.objects.create(name="p", slug="t-rs", is_free=False, team_members=2)
        self.db.save(update_fields=["plan"])
        team.invite(self.db, self.owner, "09120000032", "viewer")
        c.force_login(viewer)
        self.assertEqual(c.get(url).status_code, 404)

    def test_field_form(self):
        owner = Client()
        owner.force_login(self.owner)
        owner.post(reverse("restapi:manage", args=[self.db.pk]), {
            "action": "form_create", "api_table": self.trees.pk, "title": "ثبت درخت", "access": "public",
            "fields": ["species", "height", "healthy"]})
        form = FieldForm.objects.get()
        browser = Client(enforce_csrf_checks=True)
        r = browser.get(f"/f/{form.slug}/")
        self.assertContains(r, "ثبت درخت")
        token = r.cookies["csrftoken"].value
        cfg = r.context["cfg"]
        self.assertEqual([f["name"] for f in cfg["fields"]], ["species", "height", "healthy"])
        self.assertTrue(cfg["hasGeom"])
        sub = f"/f/{form.slug}/submit/"
        item = {"geometry": {"type": "Point", "coordinates": [51.4, 35.7]},
                "properties": {"species": "اقاقیا", "height": 2, "planted": "1999-01-01"}}
        r = browser.post(sub, json.dumps(item), content_type="application/json")
        self.assertEqual(r.status_code, 403)  # بدون CSRF
        r = browser.post(sub, json.dumps(item), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 201, r.content)
        row = self._sql("SELECT species, planted FROM trees WHERE species = 'اقاقیا'")[0]
        self.assertEqual(row, ("اقاقیا", None))  # ستون خارج از فرم نادیده گرفته شد
        r = browser.post(sub, json.dumps({"properties": {"species": "x"}}), content_type="application/json",
                         HTTP_X_CSRFTOKEN=token)
        self.assertContains(r, "موقعیت", status_code=400)
        form.refresh_from_db()
        self.assertEqual(form.submissions, 1)
        self.assertEqual(browser.get(f"/f/{form.slug}/sw.js")["Service-Worker-Allowed"], f"/f/{form.slug}/")
        self.assertEqual(json.loads(browser.get(f"/f/{form.slug}/manifest.webmanifest").content)["dir"], "rtl")
        # فرم تیمی: بیرونی‌ها به ورود هدایت می‌شوند
        form.access = "team"
        form.save()
        self.assertEqual(Client().get(f"/f/{form.slug}/").status_code, 302)
        r = Client().post(sub, json.dumps(item), content_type="application/json")
        self.assertEqual(r.status_code, 403)
        form.is_open = False
        form.save()
        r = owner.post(sub, json.dumps(item), content_type="application/json")
        self.assertContains(r, "بسته", status_code=403)
