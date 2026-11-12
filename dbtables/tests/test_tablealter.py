"""تغییر ساختار جدول: تولید DDL (واحد) و اجرا روی PostGIS واقعی."""
import json
import os
import unittest
import uuid

import psycopg
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from databases import services
from databases.explorer import Explorer, TableRef
from databases.models import DatabaseServer, EditBatch
from databases.provisioner import Provisioner
from dbtables import tablealter
from dbtables.tablebuilder import BuildError

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def col(name, typ="text", base="text", **kw):
    return {"name": name, "type": typ, "base": base, "not_null": False, "default": "", "identity": "", "generated": False,
            "spatial": False, "pk": False, **kw}


T = TableRef("public", "shops", 1, "r")
COLS = [col("id", "bigint", "int8", pk=True, not_null=True, identity="a"), col("name"), col("qty", "integer", "int4", default="0"),
        col("geom", "geometry(Point,4326)", "geometry", spatial=True)]
IDX = [{"name": "shops_pkey", "primary": True, "constraint": True, "columns": ["id"]},
       {"name": "shops_name_idx", "primary": False, "constraint": False, "columns": ["name"]}]


def script(op, p):
    return tablealter.build(T, COLS, IDX, op, p).script()


class BuildTests(SimpleTestCase):
    def test_add_column_with_index_and_rejects(self):
        s = script("add_column", {"name": "note", "type": "varchar", "length": 80, "not_null": True, "default": "x", "index": True})
        self.assertIn('ADD COLUMN "note" varchar(80) DEFAULT \'x\' NOT NULL', s)
        self.assertIn('CREATE INDEX "shops_note_idx"', s)
        for bad in ({"name": "name", "type": "text"}, {"name": "select", "type": "text"}, {"name": "a", "type": "zzz"}):
            with self.assertRaises(BuildError, msg=bad):
                script("add_column", bad)

    def test_renames_and_drop(self):
        self.assertIn('RENAME COLUMN "name" TO "title"', script("rename_column", {"column": "name", "new_name": "title"}))
        with self.assertRaises(BuildError):
            script("rename_column", {"column": "name", "new_name": "qty"})
        plan = tablealter.build(T, COLS, IDX, "rename_table", {"new_name": "stores"})
        self.assertEqual((plan.danger, plan.renamed_table), ("shops", "stores"))
        plan = tablealter.build(T, COLS, IDX, "drop_column", {"column": "qty"})
        self.assertEqual(plan.danger, "qty")
        self.assertNotIn("CASCADE", plan.script())
        with self.assertRaises(BuildError):
            script("drop_column", {"column": "id"})  # کلید اصلی
        with self.assertRaises(BuildError):
            script("drop_column", {"column": "nope"})

    def test_change_type_drops_default_and_uses_text_cast(self):
        s = script("change_type", {"column": "qty", "type": "numeric", "precision": 10, "scale": 2})
        self.assertIn('ALTER COLUMN "qty" DROP DEFAULT', s)
        self.assertIn('TYPE numeric(10, 2) USING "qty"::text::numeric(10, 2)', s)
        for bad in ({"column": "geom", "type": "text"}, {"column": "qty", "type": "choice"}, {"column": "id", "type": "text"},
                    {"column": "qty", "type": "x; DROP"}):
            with self.assertRaises(BuildError, msg=bad):
                script("change_type", bad)

    def test_not_null_and_default(self):
        self.assertIn('SET NOT NULL', script("set_not_null", {"column": "name", "value": True}))
        self.assertIn('DROP NOT NULL', script("set_not_null", {"column": "name", "value": False}))
        with self.assertRaises(BuildError):
            script("set_not_null", {"column": "id", "value": False})
        self.assertIn("SET DEFAULT 5", script("set_default", {"column": "qty", "value": "5"}))
        self.assertIn("DROP DEFAULT", script("set_default", {"column": "qty", "value": ""}))
        self.assertIn("SET DEFAULT 'x''); DROP", script("set_default", {"column": "name", "value": "x'); DROP"}))
        for bad in ({"column": "qty", "value": "abc"}, {"column": "geom", "value": "1"}, {"column": "id", "value": "1"}):
            with self.assertRaises(BuildError, msg=bad):
                script("set_default", bad)

    def test_indexes(self):
        self.assertIn('CREATE UNIQUE INDEX "shops_name_qty_idx" ON "public"."shops" ("name", "qty")',
                      script("add_index", {"columns": ["name", "qty"], "unique": True}))
        self.assertIn('USING gist ("geom")', script("add_index", {"columns": ["geom"]}))
        for bad in ({"columns": []}, {"columns": ["geom", "name"]}, {"columns": ["zz"]}, {"columns": ["geom"], "unique": True},
                    {"columns": ["name", "name"]}):
            with self.assertRaises(BuildError, msg=bad):
                script("add_index", bad)
        self.assertIn('DROP INDEX "public"."shops_name_idx"', script("drop_index", {"name": "shops_name_idx"}))
        for bad in ("shops_pkey", "nope"):
            with self.assertRaises(BuildError):
                script("drop_index", {"name": bad})

    def test_geometry_change(self):
        s = script("geometry", {"column": "geom", "type": "MultiPolygon", "dim": "XYZ", "srid": 32639, "mode": "transform"})
        self.assertIn('TYPE geometry(MultiPolygonZ, 32639) USING ST_Force3DZ(ST_Multi(ST_Transform("geom", 32639)))', s)
        self.assertIn('ST_SetSRID("geom", 32639)', script("geometry", {"column": "geom", "type": "Point", "srid": 32639, "mode": "label"}))
        for bad in ({"column": "name", "type": "Point", "srid": 4326, "mode": "label"},
                    {"column": "geom", "type": "Point", "srid": 4326, "mode": "x"},
                    {"column": "geom", "type": "Nope", "srid": 4326, "mode": "label"},
                    {"column": "geom", "type": "Point", "srid": "abc", "mode": "label"}):
            with self.assertRaises(BuildError, msg=bad):
                script("geometry", bad)

    def test_unknown_op(self):
        with self.assertRaises(BuildError):
            script("drop_everything", {})


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class AlterIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000087")
        self.db = services.create_database(self.user, f"al_{uuid.uuid4().hex[:8]}", "Alter-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Alter-Pass-123",
                       dbname=self.db.db_name, autocommit=True)
        self.sql("CREATE TABLE shops(id serial PRIMARY KEY, name text, qty text, geom geometry(Point, 4326))")
        self.sql("INSERT INTO shops(name, qty, geom) VALUES ('a', '5', ST_SetSRID(ST_MakePoint(51.4, 35.7), 4326)), "
                 "('b', '7', ST_SetSRID(ST_MakePoint(51.5, 35.8), 4326))")
        self.client.force_login(self.user)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            services.delete_database(self.db)

    def sql(self, q, *a):
        with psycopg.connect(**self.kw) as c:
            cur = c.execute(q, a)
            return cur.fetchall() if cur.description else []

    def op(self, op, params=None, table="shops", **extra):
        url = reverse("databases:table_structure", args=[self.db.pk, "public", table])
        return self.client.post(url, json.dumps({"op": op, "params": params or {}, **extra}), content_type="application/json")

    def test_columns_lifecycle(self):
        r = self.op("add_column", {"name": "city", "type": "text", "default": "تهران", "index": True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.sql("SELECT city FROM shops LIMIT 1")[0][0], "تهران")
        self.assertEqual(self.sql("SELECT count(*) FROM pg_indexes WHERE indexname='shops_city_idx'")[0][0], 1)
        self.assertEqual(self.op("add_column", {"name": "city", "type": "text"}).status_code, 400)
        # اجباری بدون پیش‌فرض روی جدول پر: خطای فارسی و بدون تغییر
        r = self.op("add_column", {"name": "must", "type": "text", "not_null": True})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sql("SELECT count(*) FROM information_schema.columns WHERE table_name='shops' AND column_name='must'")[0][0], 0)
        self.assertEqual(self.op("rename_column", {"column": "city", "new_name": "town"}).status_code, 200)
        self.assertEqual(self.sql("SELECT town FROM shops LIMIT 1")[0][0], "تهران")

    def test_dangerous_ops_need_typed_confirmation(self):
        r = self.op("drop_column", {"column": "qty"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("«qty»", r.json()["error"])
        self.assertEqual(self.op("drop_column", {"column": "qty"}, confirm="wrong").status_code, 400)
        r = self.op("drop_column", {"column": "qty"}, dry_run=True)  # پیش‌نمایش بدون اجرا
        self.assertTrue(r.json()["ok"])
        self.assertIn("DROP COLUMN", r.json()["sql"])
        self.assertEqual(self.sql("SELECT count(*) FROM information_schema.columns WHERE column_name='qty'")[0][0], 1)
        self.assertEqual(self.op("drop_column", {"column": "qty"}, confirm="qty").status_code, 200)
        self.assertEqual(self.sql("SELECT count(*) FROM information_schema.columns WHERE column_name='qty'")[0][0], 0)

    def test_change_type_ok_and_atomic_failure(self):
        self.assertEqual(self.op("change_type", {"column": "qty", "type": "integer"}, confirm="qty").status_code, 200)
        self.assertEqual(self.sql("SELECT sum(qty) FROM shops")[0][0], 12)
        self.sql("UPDATE shops SET name = 'xyz' WHERE id = 1")
        r = self.op("change_type", {"column": "name", "type": "integer"}, confirm="name")
        self.assertEqual(r.status_code, 400)
        self.assertIn("تبدیل", r.json()["error"])
        self.assertEqual(self.sql("SELECT data_type FROM information_schema.columns WHERE column_name='name' AND table_name='shops'")[0][0], "text")

    def test_not_null_default_and_indexes(self):
        self.assertEqual(self.op("set_not_null", {"column": "name", "value": True}).status_code, 200)
        self.sql("UPDATE shops SET qty = NULL WHERE id = 1")
        r = self.op("set_not_null", {"column": "qty", "value": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("خالی", r.json()["error"])
        self.assertEqual(self.op("set_default", {"column": "qty", "value": "9"}).status_code, 200)
        self.assertEqual(self.sql("SELECT column_default FROM information_schema.columns WHERE table_name='shops' AND column_name='qty'")[0][0],
                         "'9'::text")
        self.assertEqual(self.op("add_index", {"columns": ["name"], "unique": True}).status_code, 200)
        self.sql("INSERT INTO shops(name) VALUES ('c')")
        self.assertEqual(self.op("add_index", {"columns": ["geom"]}).status_code, 200)
        names = [i["name"] for i in Explorer(self.db).indexes(Explorer(self.db).find("public", "shops"))]
        self.assertIn("shops_name_idx", names)
        self.assertIn("shops_geom_idx", names)
        self.assertEqual(self.op("drop_index", {"name": "shops_name_idx"}).status_code, 200)
        self.assertEqual(self.op("drop_index", {"name": "shops_pkey"}).status_code, 400)
        # ایندکس یکتا روی داده‌ی تکراری: خطای فارسی
        self.sql("INSERT INTO shops(name) VALUES ('dup'), ('dup')")
        r = self.op("add_index", {"columns": ["name"], "unique": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("تکراری", r.json()["error"])

    def test_geometry_transform_and_label(self):
        r = self.op("geometry", {"column": "geom", "type": "Point", "srid": 32639, "mode": "transform"}, confirm="geom")
        self.assertEqual(r.status_code, 200, r.content)
        row = self.sql("SELECT ST_SRID(geom), round(ST_X(geom)::numeric) FROM shops WHERE id=1")[0]
        self.assertEqual(row[0], 32639)
        self.assertTrue(500000 < row[1] < 600000)  # واقعاً به UTM تبدیل شد
        r = self.op("geometry", {"column": "geom", "type": "MultiPoint", "srid": 4326, "mode": "label"}, confirm="geom")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.sql("SELECT ST_SRID(geom), GeometryType(geom) FROM shops WHERE id=1")[0], (4326, "MULTIPOINT"))
        t = Explorer(self.db).find("public", "shops")
        self.assertEqual((t.geometry[0]["type"], t.geometry[0]["srid"]), ("MULTIPOINT", 4326))

    def test_rename_table_updates_usages_and_clears_undo_history(self):
        from maps.models import MapLayer, WebMap

        wm = WebMap.objects.create(database=self.db, title="m", created_by=self.user)
        layer = MapLayer.objects.create(webmap=wm, schema="public", table="shops", geom_column="geom", geom_type="Point",
                                        title="فروشگاه‌ها")
        EditBatch.objects.create(database=self.db, user=self.user, schema="public", table="shops", undo=[])
        r = self.op("rename_table", {"new_name": "stores"}, confirm="shops")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["url"].endswith("/public/stores/?tab=columns"))
        self.assertEqual(self.sql("SELECT count(*) FROM stores")[0][0], 2)
        self.assertEqual(EditBatch.objects.filter(table="shops").count(), 0)
        layer.refresh_from_db()
        self.assertEqual(layer.table, "stores")  # نقشه‌ها به نام تازه وصل ماندند

    def test_page_and_permissions(self):
        page = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "shops"]) + "?tab=columns")
        self.assertContains(page, "structure-config")
        self.assertContains(page, 'data-st-op="add_column"')
        self.assertContains(page, "shops_pkey")
        self.assertContains(page, 'href="?tab=map"')  # نوار زبانه‌ها سالم مانده
        other = User.objects.create_user("09120000086")
        self.client.force_login(other)
        self.assertEqual(self.op("add_column", {"name": "x", "type": "text"}).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("databases:table_structure", args=[self.db.pk, "public", "shops"])).status_code, 405)
