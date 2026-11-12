"""سازنده‌ی جدول: اعتبارسنجی مشخصات، تولید DDL و ساخت واقعی روی PostGIS."""
import json
import os
import unittest
import uuid

import psycopg
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from databases import services
from databases.explorer import Explorer
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from dbtables import tablebuilder
from dbtables.tablebuilder import BuildError, build

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def spec(**kw):
    base = {"name": "parcels", "geometry": {"type": "Polygon", "srid": 32639},
            "columns": [{"name": "code", "type": "text", "not_null": True, "unique": True}]}
    base.update(kw)
    return base


class SpecTests(SimpleTestCase):
    def test_full_script(self):
        plan = build(spec(
            comment="قطعه‌ها",
            columns=[{"name": "st", "type": "choice", "choices": ["a", "b'c"], "default": "a"},
                     {"name": "d", "type": "date", "default": "@now"},
                     {"name": "n", "type": "numeric", "precision": 10, "scale": 2, "default": "1.5"},
                     {"name": "u", "type": "uuid", "default": "@uuid"}],
            indexes=[{"columns": ["st", "d"]}]))
        s = plan.script()
        self.assertIn('"id" bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY', s)
        self.assertIn("geometry(Polygon, 32639)", s)
        self.assertIn("CHECK (\"st\" IN ('a', 'b''c'))", s)  # نقل‌قول درست
        self.assertIn("DEFAULT CURRENT_DATE", s)
        self.assertIn("gen_random_uuid()", s)
        self.assertIn('USING gist ("geom")', s)
        self.assertIn('("st", "d")', s)
        self.assertIn("COMMENT ON TABLE", s)

    def test_dimension_geography_and_plain(self):
        self.assertIn("geometry(PointZ, 4326)", build(spec(geometry={"type": "Point", "dim": "XYZ", "srid": 4326})).script())
        self.assertIn("geography(Point, 4326)", build(spec(geometry={"type": "Point", "geography": True})).script())
        plain = build({"name": "notes", "geometry": None, "columns": []}).script()
        self.assertNotIn("geom", plain)
        self.assertNotIn("gist", plain)

    def test_composite_primary_key_and_none(self):
        s = build(spec(pk={"mode": "columns", "columns": ["code"]})).script()
        self.assertIn('PRIMARY KEY ("code")', s)
        self.assertNotIn("IDENTITY", s)
        self.assertNotIn("PRIMARY KEY", build(spec(pk={"mode": "none"})).script())

    def test_names_rejected(self):
        for bad in ("select", "Bad", "1a", "a-b", "", "x" * 64, "pg_x", "جدول", 'a"; DROP TABLE x;--'):
            with self.assertRaises(BuildError, msg=bad):
                build(spec(name=bad))
        with self.assertRaises(BuildError):
            build(spec(columns=[{"name": "user", "type": "text"}]))

    def test_columns_rejected(self):
        bads = [
            [{"name": "a", "type": "text"}, {"name": "a", "type": "text"}],  # تکراری
            [{"name": "geom", "type": "text"}],  # با ستون هندسه برخورد دارد
            [{"name": "id", "type": "text"}],  # با کلید خودکار
            [{"name": "a", "type": "evil; DROP"}],
            [{"name": "a", "type": "integer", "default": "1; DROP TABLE x"}],
            [{"name": "a", "type": "date", "default": "yesterday"}],
            [{"name": "a", "type": "text", "default": "@uuid"}],
            [{"name": "a", "type": "varchar", "length": 0}],
            [{"name": "a", "type": "numeric", "precision": 5, "scale": 9}],
            [{"name": "a", "type": "choice", "choices": []}],
            [{"name": "a", "type": "choice", "choices": ["x"], "default": "y"}],
            [{"name": "a", "type": "jsonb", "default": "{}"}],
        ]
        for cols in bads:
            with self.assertRaises(BuildError, msg=cols):
                build(spec(columns=cols))

    def test_default_literal_is_quoted(self):
        s = build(spec(columns=[{"name": "t", "type": "text", "default": "x'); DROP TABLE y;--"}])).script()
        self.assertIn("DEFAULT 'x''); DROP TABLE y;--'", s)

    def test_geometry_rejected(self):
        for g in ({"type": "Nope"}, {"type": "Point", "srid": 0}, {"type": "Point", "srid": "abc"},
                  {"type": "Point", "dim": "XYZM"}, {"type": "Point", "srid": 32639, "geography": True},
                  {"type": "Geometry", "geography": True}, {"type": "Point", "name": "Select"}):
            with self.assertRaises(BuildError, msg=g):
                build(spec(geometry=g))

    def test_pk_and_index_rejected(self):
        for kw in ({"pk": {"mode": "columns", "columns": []}}, {"pk": {"mode": "columns", "columns": ["zzz"]}},
                   {"pk": {"mode": "weird"}}, {"indexes": [{"columns": ["zzz"]}]}, {"indexes": [{"columns": []}]}):
            with self.assertRaises(BuildError, msg=kw):
                build(spec(**kw))

    def test_limits(self):
        many = [{"name": f"c{i}", "type": "text"} for i in range(tablebuilder.MAX_COLUMNS)]
        with self.assertRaisesMessage(BuildError, "حداکثر"):
            build(spec(columns=many))
        build(spec(columns=many[:tablebuilder.MAX_COLUMNS - 2]))

    def test_presets_are_valid(self):
        for key, p in tablebuilder.PRESETS.items():
            cols = [{k: v for k, v in c.items() if k != "label"} for c in p["columns"]]
            build({"name": key, "geometry": p["geometry"], "columns": cols})


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class BuilderIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000078")
        self.db = services.create_database(self.user, f"tb_{uuid.uuid4().hex[:8]}", "Builder-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        self.conn_kwargs = dict(host=server.host, port=server.port, user=self.db.role_name, password="Builder-Pass-1",
                                dbname=self.db.db_name, autocommit=True)
        self.client.force_login(self.user)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            services.delete_database(self.db)

    def post(self, name, body):
        return self.client.post(reverse(f"databases:{name}", args=[self.db.pk]), json.dumps(body),
                                content_type="application/json")

    def test_create_table_end_to_end(self):
        body = {"spec": spec(columns=[{"name": "code", "type": "text", "not_null": True, "unique": True},
                                      {"name": "st", "type": "choice", "choices": ["x", "y"], "default": "x"},
                                      {"name": "seen", "type": "date", "default": "@now"}],
                             indexes=[{"columns": ["st"]}], comment="آزمون")}
        r = self.post("table_preview", body)
        self.assertTrue(r.json()["ok"])
        r = self.post("table_new", body)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["url"].endswith("/public/parcels/"))
        with psycopg.connect(**self.conn_kwargs) as c:
            c.execute("INSERT INTO parcels(code, geom) VALUES ('a', ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 0))', 32639))")
            row = c.execute("SELECT id, st, seen IS NOT NULL FROM parcels").fetchone()
            self.assertEqual(row, (1, "x", True))
            with self.assertRaises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO parcels(code, st) VALUES ('b', 'zzz')")
            self.assertEqual(c.execute("SELECT count(*) FROM pg_indexes WHERE tablename='parcels'").fetchone()[0], 4)
            self.assertEqual(c.execute("SELECT obj_description('parcels'::regclass)").fetchone()[0], "آزمون")
        t = Explorer(self.db).find("public", "parcels")
        self.assertEqual(t.geometry[0]["srid"], 32639)

    def test_duplicate_and_bad_srid_and_invalid(self):
        body = {"spec": spec()}
        self.assertEqual(self.post("table_new", body).status_code, 200)
        r = self.post("table_new", body)
        self.assertEqual(r.status_code, 400)
        self.assertIn("وجود دارد", r.json()["error"])
        r = self.post("table_new", {"spec": spec(name="other", geometry={"type": "Point", "srid": 998999})})
        self.assertEqual(r.status_code, 400)
        self.assertIn("پیدا نشد", r.json()["error"])
        self.assertEqual(self.post("table_new", {"spec": spec(name="table")}).status_code, 400)

    def test_failed_create_is_atomic(self):
        # ایندکس تکراریِ دو ستون یکسان نباید ساخته شود؛ خطای میانه، جدول را هم برنمی‌گذارد
        body = {"spec": spec(name="atomic", columns=[{"name": "a", "type": "text"}], indexes=[{"columns": ["a"]}])}
        with psycopg.connect(**self.conn_kwargs) as c:
            c.execute("CREATE TABLE other_t(a text)")
            c.execute("CREATE INDEX atomic_a_idx ON other_t(a)")  # نام ایندکس را اشغال می‌کند
        r = self.post("table_new", body)
        self.assertEqual(r.status_code, 400)
        with psycopg.connect(**self.conn_kwargs) as c:
            self.assertIsNone(c.execute("SELECT to_regclass('atomic')").fetchone()[0])

    def test_quota_readonly_and_viewer(self):
        self.db.size_bytes = self.db.quota_bytes
        self.db.save(update_fields=["size_bytes"])
        r = self.post("table_new", {"spec": spec()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("سهمیه", r.json()["error"])

    def test_srid_search_and_page(self):
        r = self.client.get(reverse("databases:table_srid", args=[self.db.pk]), {"q": "32639"})
        self.assertEqual(r.json()["items"][0]["srid"], 32639)
        r = self.client.get(reverse("databases:table_srid", args=[self.db.pk]), {"q": "UTM zone 39N"})
        self.assertTrue(r.json()["items"])
        page = self.client.get(reverse("databases:explore", args=[self.db.pk]))
        self.assertContains(page, "جدول جدید")
        self.assertContains(page, 'id="builder-config"')

    def test_other_user_cannot_create(self):
        other = User.objects.create_user("09120000079")
        self.client.force_login(other)
        r = self.post("table_new", {"spec": spec()})
        self.assertEqual(r.status_code, 404)
