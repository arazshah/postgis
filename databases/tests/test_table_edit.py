"""ویرایش جدول از مرورگر: افزودن/ویرایش/حذف، هندسه، تعارض، همه‌یاهیچ و بازگردانی."""
import json
import os
import unittest
import uuid

import psycopg
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from databases import editor, services
from databases.editor import EditError, Editor, normalize
from databases.explorer import Explorer
from databases.models import ActivityLog, DatabaseServer, EditBatch, Member
from databases.provisioner import Provisioner

PG_HOST = os.environ.get("TEST_PG_HOST", "")

COLS = [
    {"name": "id", "type": "integer", "pk": True, "spatial": False, "generated": False, "identity": "", "base": "int4"},
    {"name": "name", "type": "text", "pk": False, "spatial": False, "generated": False, "identity": "", "base": "text"},
    {"name": "area", "type": "double precision", "pk": False, "spatial": False, "generated": True, "identity": "",
     "base": "float8"},
    {"name": "uid", "type": "integer", "pk": False, "spatial": False, "generated": False, "identity": "a",
     "base": "int4"},
    {"name": "geom", "type": "geometry(Polygon,32639)", "pk": False, "spatial": True, "generated": False,
     "identity": "", "base": "geometry"},
]
V = "a" * 32


class NormalizeTests(SimpleTestCase):
    def test_empty_and_limits(self):
        with self.assertRaises(EditError):
            normalize([], COLS)
        with self.assertRaisesMessage(EditError, "حداکثر"):
            normalize([{"op": "delete", "pk": {"id": "1"}, "v": V}] * (editor.MAX_CHANGES + 1), COLS)

    def test_rejects_unknown_generated_identity_and_pk_edit(self):
        base = {"op": "update", "pk": {"id": "1"}, "v": V}
        for values in ({"nope": "x"}, {"area": "1"}, {"uid": "1"}, {"id": "2"}):
            with self.assertRaises(EditError, msg=values):
                normalize([{**base, "values": values}], COLS)
        # در بازگردانی (internal) ستون هویت‌ساز مجاز است
        normalize([{"op": "insert", "values": {"uid": "1", "id": "5"}}], COLS, internal=True)

    def test_pk_and_version_required(self):
        with self.assertRaises(EditError):
            normalize([{"op": "delete", "pk": {}, "v": V}], COLS)
        with self.assertRaises(EditError):
            normalize([{"op": "delete", "pk": {"id": "1"}, "v": "x"}], COLS)
        with self.assertRaises(EditError):
            normalize([{"op": "delete", "pk": {"id": "1", "name": "x"}, "v": V}], COLS)

    def test_geometry_validation(self):
        ok = {"op": "update", "pk": {"id": "1"}, "v": V,
              "geom": {"column": "geom", "geojson": {"type": "Polygon", "coordinates": []}}}
        self.assertEqual(normalize([ok], COLS)[0]["geoms"][0]["column"], "geom")
        for bad in ({"column": "name", "geojson": {"type": "Point", "coordinates": [1, 2]}},
                    {"column": "geom", "geojson": {"type": "GeometryCollection", "coordinates": []}},
                    {"column": "geom", "ewkb": "zz"}, {"column": "geom"}):
            with self.assertRaises(EditError, msg=bad):
                normalize([{**ok, "geom": bad}], COLS)

    def test_empty_update_is_rejected(self):
        with self.assertRaises(EditError):
            normalize([{"op": "update", "pk": {"id": "1"}, "v": V, "values": {}}], COLS)


def square(x, y, d=0.001):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class TableEditTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000077")
        label = f"ed_{uuid.uuid4().hex[:8]}"
        self.db = services.create_database(self.user, label, "Editor-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        self.conn_kwargs = dict(host=server.host, port=server.port, user=self.db.role_name, password="Editor-Pass-1",
                                dbname=self.db.db_name, autocommit=True)
        with psycopg.connect(**self.conn_kwargs) as c:
            c.execute("CREATE TABLE parcels(id serial PRIMARY KEY, name text NOT NULL, owner_id int, "
                      "geom geometry(Polygon, 32639))")
            c.execute("INSERT INTO parcels(name, owner_id, geom) SELECT 'قطعه ' || g, g, ST_Buffer(ST_SetSRID("
                      "ST_MakePoint(535000 + g * 100, 3950000), 32639), 40) FROM generate_series(1, 5) g")
            c.execute("CREATE TABLE notes(id int, txt text)")
            c.execute("CREATE TABLE ident(id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, txt text, "
                      "n int GENERATED ALWAYS AS (length(txt)) STORED)")
        self.ex = Explorer(self.db)
        self.ed = Editor(self.ex)
        self.t = self.ex.find("public", "parcels")

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            services.delete_database(self.db)

    def sql(self, q, *a):
        with psycopg.connect(**self.conn_kwargs) as c:
            cur = c.execute(q, a)
            return cur.fetchall() if cur.description else []

    def version(self, pk):
        return self.sql("SELECT md5(t::text) FROM parcels t WHERE id=%s", pk)[0][0]

    # ----------------------------------------------------------------- منطق
    def test_update_insert_delete_and_undo_roundtrip(self):
        before = self.sql("SELECT id, name, owner_id, encode(ST_AsEWKB(geom),'hex') FROM parcels ORDER BY id")
        changes = [
            {"op": "update", "pk": {"id": "1"}, "v": self.version(1), "values": {"name": "تغییر‌یافته", "owner_id": None}},
            {"op": "update", "pk": {"id": "2"}, "v": self.version(2),
             "geom": {"column": "geom", "geojson": square(51.4, 35.7)}},
            {"op": "delete", "pk": {"id": "3"}, "v": self.version(3)},
            {"op": "insert", "values": {"name": "تازه", "owner_id": "9"},
             "geom": {"column": "geom", "geojson": square(51.5, 35.8)}},
        ]
        out = self.ed.apply(self.t, changes)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["counts"], {"insert": 1, "update": 2, "delete": 1})
        rows = {r[0]: r for r in self.sql("SELECT id, name, owner_id, ST_SRID(geom), ST_X(ST_Centroid(ST_Transform(geom,4326))) "
                                          "FROM parcels")}
        self.assertEqual(rows[1][1:3], ("تغییر‌یافته", None))
        self.assertNotIn(3, rows)
        self.assertEqual(rows[2][3], 32639)  # از 4326 به SRID جدول برگشته
        self.assertAlmostEqual(rows[2][4], 51.4005, places=3)
        self.assertEqual(len(rows), 5)
        # بازگردانی کامل
        undo = self.ed.apply(self.t, out["undo"], internal=True)
        self.assertTrue(undo["ok"], undo)
        after = self.sql("SELECT id, name, owner_id, encode(ST_AsEWKB(geom),'hex') FROM parcels ORDER BY id")
        self.assertEqual(before, after)

    def test_atomic_all_or_nothing_and_per_change_errors(self):
        changes = [
            {"op": "update", "pk": {"id": "1"}, "v": self.version(1), "values": {"name": "نباید بماند"}},
            {"op": "update", "pk": {"id": "2"}, "v": self.version(2), "values": {"name": None}},  # NOT NULL
            {"op": "update", "pk": {"id": "3"}, "v": self.version(3), "values": {"owner_id": "abc"}},  # نوع نادرست
        ]
        out = self.ed.apply(self.t, changes)
        self.assertFalse(out["ok"])
        self.assertEqual([r["status"] for r in out["results"]], ["ok", "error", "error"])
        self.assertIn("name", out["results"][1]["message"])
        self.assertEqual(self.sql("SELECT name FROM parcels WHERE id=1")[0][0], "قطعه 1")

    def test_conflict_detected(self):
        v = self.version(1)
        self.sql("UPDATE parcels SET name='دیگری' WHERE id=1")
        out = self.ed.apply(self.t, [{"op": "update", "pk": {"id": "1"}, "v": v, "values": {"name": "من"}}])
        self.assertEqual(out["results"][0]["status"], "conflict")
        self.assertEqual(self.sql("SELECT name FROM parcels WHERE id=1")[0][0], "دیگری")
        out = self.ed.apply(self.t, [{"op": "delete", "pk": {"id": "1"}, "v": v}])
        self.assertEqual(out["results"][0]["status"], "conflict")
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)

    def test_dry_run_writes_nothing(self):
        out = self.ed.apply(self.t, [{"op": "delete", "pk": {"id": "1"}, "v": self.version(1)}], dry_run=True)
        self.assertTrue(out["ok"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)

    def test_invalid_geometry_and_repair(self):
        bow = {"type": "Polygon", "coordinates": [[[51.4, 35.7], [51.401, 35.701], [51.401, 35.7], [51.4, 35.701],
                                                   [51.4, 35.7]]]}
        change = [{"op": "update", "pk": {"id": "1"}, "v": self.version(1), "geom": {"column": "geom", "geojson": bow}}]
        out = self.ed.apply(self.t, change)
        self.assertEqual(out["results"][0]["status"], "invalid")
        self.assertIn("هندسه نامعتبر", out["results"][0]["message"])
        # ستون Polygon فقط یک تکه می‌پذیرد؛ ترمیم «پاپیونی» دو تکه می‌سازد و باید صریح رد شود، نه بی‌صدا تکه‌ای حذف شود
        fixed = self.ed.apply(self.t, change, repair=True)
        self.assertEqual(fixed["results"][0]["status"], "invalid")
        self.assertIn("چند تکه", fixed["results"][0]["message"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels WHERE ST_IsValid(geom)")[0][0], 5)

    def test_repair_on_multipolygon_column(self):
        with psycopg.connect(**self.conn_kwargs) as c:
            c.execute("CREATE TABLE zones(id serial PRIMARY KEY, geom geometry(MultiPolygon, 4326))")
        zones = self.ex.find("public", "zones")
        bow = {"type": "Polygon", "coordinates": [[[51.4, 35.7], [51.401, 35.701], [51.401, 35.7], [51.4, 35.701],
                                                   [51.4, 35.7]]]}
        out = self.ed.apply(zones, [{"op": "insert", "geom": {"column": "geom", "geojson": bow}}], repair=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.sql("SELECT ST_IsValid(geom), GeometryType(geom) FROM zones")[0], (True, "MULTIPOLYGON"))

    def test_wrong_geometry_type_is_an_error_not_a_crash(self):
        point = {"type": "Point", "coordinates": [51.4, 35.7]}
        out = self.ed.apply(self.t, [{"op": "update", "pk": {"id": "1"}, "v": self.version(1),
                                      "geom": {"column": "geom", "geojson": point}}])
        self.assertFalse(out["ok"])
        self.assertIn(out["results"][0]["status"], ("error", "invalid"))

    def test_tables_without_pk_or_views_are_refused(self):
        notes = self.ex.find("public", "notes")
        with self.assertRaisesMessage(EditError, "کلید اصلی"):
            self.ed.apply(notes, [{"op": "insert", "values": {"txt": "x"}}])
        with psycopg.connect(**self.conn_kwargs) as c:
            c.execute("CREATE VIEW v_parcels AS SELECT * FROM parcels")
        with self.assertRaisesMessage(EditError, "نما"):
            self.ed.apply(self.ex.find("public", "v_parcels"), [{"op": "insert", "values": {"name": "x"}}])

    def test_identity_and_generated_columns(self):
        t = self.ex.find("public", "ident")
        out = self.ed.apply(t, [{"op": "insert", "values": {"txt": "abc"}}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.sql("SELECT id, txt, n FROM ident")[0][1:], ("abc", 3))
        with self.assertRaises(EditError):
            self.ed.apply(t, [{"op": "insert", "values": {"id": "9", "txt": "x"}}])
        with self.assertRaises(EditError):
            self.ed.apply(t, [{"op": "insert", "values": {"n": "9", "txt": "x"}}])
        # حذف و بازگردانی با کلید هویت‌ساز
        row = self.ed.row(t, {"id": "1"})
        gone = self.ed.apply(t, [{"op": "delete", "pk": {"id": "1"}, "v": row["v"]}])
        self.assertTrue(self.ed.apply(t, gone["undo"], internal=True)["ok"])
        self.assertEqual(self.sql("SELECT id, txt FROM ident")[0], (1, "abc"))

    def test_sql_injection_in_values_and_pk_is_inert(self):
        evil = "x'); DROP TABLE parcels; --"
        out = self.ed.apply(self.t, [{"op": "update", "pk": {"id": "1"}, "v": self.version(1), "values": {"name": evil}}])
        self.assertTrue(out["ok"])
        self.assertEqual(self.sql("SELECT name FROM parcels WHERE id=1")[0][0], evil)
        out = self.ed.apply(self.t, [{"op": "delete", "pk": {"id": "1; DROP TABLE parcels"}, "v": self.version(1)}])
        self.assertFalse(out["ok"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)

    def test_undo_conflicts_when_row_changed_again(self):
        out = self.ed.apply(self.t, [{"op": "update", "pk": {"id": "1"}, "v": self.version(1), "values": {"name": "الف"}}])
        self.sql("UPDATE parcels SET name='ب' WHERE id=1")
        undo = self.ed.apply(self.t, out["undo"], internal=True)
        self.assertFalse(undo["ok"])
        self.assertEqual(self.sql("SELECT name FROM parcels WHERE id=1")[0][0], "ب")

    def test_row_returns_full_untruncated_values(self):
        long = "ن" * 500
        self.sql("UPDATE parcels SET name=%s WHERE id=1", long)
        self.assertEqual(self.ed.row(self.t, {"id": "1"})["values"]["name"], long)

    # ----------------------------------------------------------------- نماها
    def _url(self, name, table="parcels"):
        return reverse(f"databases:explore_edit_{name}", args=[self.db.pk, "public", table])

    def _post(self, name, body, table="parcels"):
        return self.client.post(self._url(name, table), json.dumps(body), content_type="application/json")

    def test_views_require_edit_mode_and_permission(self):
        self.client.force_login(self.user)
        change = {"changes": [{"op": "delete", "pk": {"id": "1"}, "v": self.version(1)}]}
        # حالت ویرایش خاموش است
        r = self._post("apply", change)
        self.assertEqual(r.status_code, 400)
        self.assertIn("حالت ویرایش", r.json()["error"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)
        # روشن کردن
        self.assertTrue(self._post("mode", {"on": True}).json()["ok"])
        # GET برای apply مجاز نیست
        self.assertEqual(self.client.get(self._url("apply")).status_code, 405)
        r = self._post("apply", {**change, "dry_run": True})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)
        r = self._post("apply", change).json()
        self.assertTrue(r["ok"] and r["batch"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 4)
        self.assertTrue(ActivityLog.objects.filter(database=self.db, action="table_edit").exists())
        # بازگردانی
        bad = self._post("undo", {"batch": r["batch"] + 1})
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(self._post("undo", {"batch": r["batch"]}).json()["ok"])
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)
        self.assertEqual(self._post("undo", {"batch": r["batch"]}).status_code, 400)  # دوباره نه
        # خاموش کردن
        self._post("mode", {"on": False})
        self.assertEqual(self._post("apply", change).status_code, 400)

    def test_expired_edit_mode(self):
        self.client.force_login(self.user)
        self._post("mode", {"on": True})
        s = self.client.session
        s[f"gp_edit_until_{self.db.pk}"] = 1
        s.save()
        r = self._post("apply", {"changes": [{"op": "insert", "values": {"name": "x"}}]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)

    def test_viewer_and_outsider_cannot_edit(self):
        viewer = User.objects.create_user("09120000066")
        Member.objects.create(database=self.db, user=viewer, phone="09120000066", role="viewer")
        outsider = User.objects.create_user("09120000055")
        for who in (viewer, outsider):
            self.client.force_login(who)
            self.assertEqual(self._post("mode", {"on": True}).status_code, 404)
            self.assertEqual(self._post("apply", {"changes": [{"op": "insert", "values": {"name": "x"}}]}).status_code, 404)
        self.assertEqual(self.sql("SELECT count(*) FROM parcels")[0][0], 5)
        # مشاهده‌گر دکمه‌ی ویرایش را نمی‌بیند
        self.client.force_login(viewer)
        page = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "parcels"]))
        self.assertNotContains(page, "edit-config")

    def test_editor_member_can_edit_and_page_has_controls(self):
        member = User.objects.create_user("09120000044")
        Member.objects.create(database=self.db, user=member, phone="09120000044", role="editor")
        self.client.force_login(member)
        self.assertTrue(self._post("mode", {"on": True}).json()["ok"])
        page = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "parcels"]))
        self.assertContains(page, "edit-config")
        self.assertContains(page, "data-key=")

    def test_mode_refused_for_table_without_pk_and_shown_reason(self):
        self.client.force_login(self.user)
        r = self._post("mode", {"on": True}, table="notes")
        self.assertEqual(r.status_code, 400)
        self.assertIn("کلید اصلی", r.json()["error"])
        page = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "notes"]))
        self.assertContains(page, "کلید اصلی")

    def test_geojson_keys_only_on_request(self):
        self.client.force_login(self.user)
        url = reverse("databases:explore_geojson", args=[self.db.pk, "public", "parcels"])
        plain = json.loads(self.client.get(url).content)["features"][0]["properties"]
        self.assertNotIn("__v", plain)
        keyed = json.loads(self.client.get(url + "?keys=1").content)["features"][0]["properties"]
        self.assertEqual(len(keyed["__v"]), 32)
        self.assertEqual(set(keyed["__pk"]), {"id"})

    def test_batch_history_is_pruned(self):
        for _ in range(editor.KEEP_BATCHES + 3):
            EditBatch.objects.create(database=self.db, user=self.user, schema="public", table="parcels")
        self.client.force_login(self.user)
        self._post("mode", {"on": True})
        self._post("apply", {"changes": [{"op": "insert", "values": {"name": "n"}}]})
        self.assertEqual(EditBatch.objects.filter(database=self.db).count(), editor.KEEP_BATCHES)
