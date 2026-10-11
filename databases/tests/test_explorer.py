"""مرورگر پایگاه داده روی PostGIS واقعی (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import json
import os
import unittest
import uuid

import psycopg
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from databases import crypto, services
from databases.explorer import Explorer, ExplorerError
from databases.models import DatabaseServer
from databases.provisioner import Provisioner

PG_HOST = os.environ.get("TEST_PG_HOST", "")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class ExplorerIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000099")
        label = f"ex_{uuid.uuid4().hex[:8]}"
        self.db = services.create_database(self.user, label, "Explorer-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        with psycopg.connect(host=server.host, port=server.port, user=self.db.role_name, password="Explorer-Pass-1",
                             dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE parcels(id serial PRIMARY KEY, name text, geom geometry(Polygon, 32639))")
            c.execute("INSERT INTO parcels(name, geom) SELECT 'قطعه ' || g, ST_Buffer(ST_SetSRID("
                      "ST_MakePoint(535000 + g * 100, 3950000), 32639), 40) FROM generate_series(1, 75) g")
            c.execute("CREATE TABLE notes(id int, txt text)")
        self.ex = Explorer(self.db)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            services.delete_database(self.db)

    def test_tables_rows_columns(self):
        names = [t.qualified for t in self.ex.tables()]
        self.assertEqual(names, ["public.notes", "public.parcels"])  # جدول‌های سیستمی پنهان‌اند
        t = self.ex.find("public", "parcels")
        self.assertEqual(t.geometry[0]["srid"], 32639)
        page = self.ex.rows(t, 2)
        self.assertEqual((page["total"], page["pages"], page["offset"]), (75, 2, 50))
        self.assertTrue(page["rows"][0][2].startswith("POLYGON(("))
        cols = {c["name"]: c for c in self.ex.columns(t)}
        self.assertTrue(cols["id"]["pk"] and cols["geom"]["spatial"])

    def test_geojson_reprojected(self):
        data = json.loads(self.ex.geojson(self.ex.find("public", "parcels")))
        self.assertEqual(len(data["features"]), 75)
        lon, lat = data["features"][0]["geometry"]["coordinates"][0][0]
        self.assertTrue(50 < lon < 53 and 34 < lat < 37)
        self.assertEqual(data["features"][0]["properties"]["name"], "قطعه 1")

    def test_sql_safety(self):
        self.assertEqual(self.ex.run_sql("SELECT count(*), '%x%' FROM parcels")["rows"], [["75", "%x%"]])
        with self.assertRaisesRegex(ExplorerError, "تغییر"):
            self.ex.run_sql("DELETE FROM parcels")
        with self.assertRaisesRegex(ExplorerError, "یک دستور"):
            self.ex.run_sql("SELECT 1; DROP TABLE parcels")
        with self.assertRaises(ExplorerError):
            self.ex.run_sql("SELECT * FROM pg_authid")
        self.assertEqual(self.ex.run_sql("DELETE FROM notes", allow_write=True)["status"], "DELETE 0")

    def test_browser_role_isolated(self):
        web = Provisioner.browser_role_name(self.db.role_name)
        self.ex.tables()
        self.db.refresh_from_db()
        pw = crypto.decrypt(self.db.browser_password_encrypted)
        with self.assertRaises(psycopg.OperationalError):
            psycopg.connect(host=self.db.server.host, port=self.db.server.port, user=web, password=pw,
                            dbname="postgres", connect_timeout=5)
        with psycopg.connect(host=self.db.server.host, port=self.db.server.port, user=web, password=pw,
                             dbname=self.db.db_name) as c:
            self.assertFalse(c.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0])

    def test_views(self):
        self.client.force_login(self.user)
        pk = self.db.pk
        self.assertContains(self.client.get(reverse("databases:explore", args=[pk])), "parcels")
        url = reverse("databases:explore_table", args=[pk, "public", "parcels"])
        self.assertContains(self.client.get(url), "POLYGON")
        self.assertContains(self.client.get(url + "?tab=columns"), "کلید اصلی")
        self.assertContains(self.client.get(url + "?tab=map"), 'id="map"')
        gj = self.client.get(reverse("databases:explore_geojson", args=[pk, "public", "parcels"]))
        self.assertEqual(len(json.loads(gj.content)["features"]), 75)
        csv_resp = self.client.get(reverse("databases:explore_csv", args=[pk, "public", "parcels"]))
        body = b"".join(csv_resp.streaming_content).decode("utf-8-sig")
        self.assertEqual(len(body.strip().splitlines()), 76)
        r = self.client.post(reverse("databases:explore_sql", args=[pk]), {"query": "SELECT name FROM parcels LIMIT 2"})
        self.assertContains(r, "قطعه 1")
        self.assertEqual(self.client.get(reverse("databases:explore_table", args=[pk, "public", "nope"])).status_code,
                         302)
        other = User.objects.create_user("09120000098")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("databases:explore", args=[pk])).status_code, 404)

    def test_delete_removes_browser_role(self):
        self.ex.tables()
        role = self.db.role_name
        services.delete_database(self.db)
        server = self.db.server
        with psycopg.connect(**server.connection_kwargs()) as c:
            left = c.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                             ([role, Provisioner.browser_role_name(role)],)).fetchall()
        self.assertEqual(left, [])
