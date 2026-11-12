"""یافتن عارضه: ساخت امن شرط‌ها (بدون PostGIS) و اجرای واقعی روی PostGIS (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import json
import os
import unittest
import uuid
from datetime import timedelta

import psycopg
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases import services
from databases.explorer import Explorer
from databases.models import DatabaseServer, FindLog, Plan
from databases.provisioner import Provisioner
from dbfind import find_credits, find_save
from dbfind.find import Finder, FindError, _cond_sql, _date, _num, normalize, spec_hash, uses_other_layer

PG_HOST = os.environ.get("TEST_PG_HOST", "")
TEXT = {"name": "name", "base": "text", "spatial": False}
NUM = {"name": "pop", "base": "int4", "spatial": False}
DATE = {"name": "built", "base": "date", "spatial": False}


class FindUnitTests(SimpleTestCase):
    def test_persian_normalize(self):
        self.assertEqual(normalize("  كتابخانه‌ي  مركزي ۱۲ "), "کتابخانهی مرکزی 12")
        self.assertEqual(normalize("Tehran"), "tehran")

    def test_numbers_and_dates(self):
        self.assertEqual(_num("۱٬۲۵۰"), "1250")
        self.assertEqual(_num("-3.5"), "-3.5")
        with self.assertRaises(FindError):
            _num("1; DROP TABLE x")
        self.assertEqual(str(_date("۱۴۰۵/۰۸/۱۲")), "2026-11-03")
        self.assertEqual(str(_date("2026-11-03")), "2026-11-03")
        with self.assertRaises(FindError):
            _date("دیروز")

    def test_values_are_parameters(self):
        s, p = _cond_sql("a", TEXT, {"col": "name", "op": "contains", "v": "x' OR 1=1 --%"})
        self.assertEqual(p, ["%x' or 1=1 --\\%%"])
        s, p = _cond_sql("a", NUM, {"col": "pop", "op": "between", "v": "۵۰۰", "v2": "10"})
        self.assertEqual(p, ["10", "500"])
        s, p = _cond_sql("a", TEXT, {"col": "name", "op": "in", "v": "الف، ب,ج"})
        self.assertEqual(p, [["الف", "ب", "ج"]])
        s, p = _cond_sql("a", TEXT, {"col": "name", "op": "empty"})
        self.assertEqual(p, [])

    def test_bad_operator_or_missing_value(self):
        with self.assertRaises(FindError):
            _cond_sql("a", NUM, {"col": "pop", "op": "contains", "v": "1"})
        with self.assertRaises(FindError):
            _cond_sql("a", TEXT, {"col": "name", "op": "drop", "v": "1"})
        with self.assertRaises(FindError):
            _cond_sql("a", DATE, {"col": "built", "op": "between", "v": "1400/01/01"})
        with self.assertRaises(FindError):
            _cond_sql("a", TEXT, {"col": "name", "op": "eq", "v": "  "})

    def test_spec_helpers(self):
        a = {"layer": "public.x", "conds": [], "spatial": {"rel": "within", "target": {"kind": "layer", "layer": "public.y"}}}
        b = {"spatial": {"target": {"kind": "layer", "layer": "public.y"}, "rel": "within"}, "conds": [], "layer": "public.x"}
        self.assertEqual(spec_hash(a), spec_hash(b))
        self.assertTrue(uses_other_layer(a))
        self.assertFalse(uses_other_layer({"layer": "public.x", "spatial": {"target": {"kind": "shape"}}}))
        self.assertFalse(uses_other_layer({"layer": "public.x"}))


class FindSaveUnitTests(SimpleTestCase):
    def test_parse_opts(self):
        o = find_save.parse_opts({"name": " Schools_Found ", "kind": "view", "scope": "selected", "ids": [1, "1", 2]})
        self.assertEqual((o["name"], o["kind"], o["ids"], o["srid"]), ("schools_found", "view", ["1", "2"], "keep"))
        self.assertEqual(find_save.parse_opts({"name": "a", "srid": 4326})["srid"], "4326")
        for bad in ({"name": "نام"}, {"name": "1abc"}, {"name": "a" * 64}, {"name": "x", "kind": "mview"},
                    {"name": "x", "scope": "selected"}, {"name": "x", "scope": "except", "ids": []},
                    {"name": "x", "join_cols": ["c"] * 21}, {"name": "x", "ids": "1,2", "scope": "selected"}, "x"):
            with self.assertRaises(FindError, msg=bad):
                find_save.parse_opts(bad)
        with self.assertRaises(FindError):
            find_save.parse_opts({"name": "x", "scope": "selected", "ids": [str(i) for i in range(5001)]})

    def test_describe_is_persian_and_marks_options(self):
        spec = {"layer": "public.schools", "match": "any", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}],
                "spatial": {"rel": "dwithin", "dist": 500, "target": {"kind": "layer", "layer": "public.roads"}}}
        text = find_save.describe(spec, {"invert": True, "scope": "except"})
        for part in ("public.schools", "kind برابر «دخترانه»", "تا فاصله‌ی 500 متر", "public.roads", "وارونه", "به‌جز"):
            self.assertIn(part, text)


class FindCreditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09120000201")
        server = DatabaseServer.objects.create(name="s", host="h", admin_user="postgres")
        self.plan = Plan.objects.create(name="p", slug="p-find", find_layer_credits=2)
        from databases.models import UserDatabase

        self.db = UserDatabase.objects.create(owner=self.user, server=server, plan=self.plan, label="fc_test",
                                              db_name="fc_test", role_name="fc_test_user")

    def test_only_cross_layer_is_charged_and_repeat_is_free(self):
        self.assertFalse(find_credits.record(self.db, self.user, "h0", "public.a", False))
        self.assertTrue(find_credits.record(self.db, self.user, "h1", "public.a", True))
        self.assertFalse(find_credits.record(self.db, self.user, "h1", "public.a", True))  # همان پرسش در نیم ساعت
        self.assertEqual(find_credits.status(self.db), {"cap": 2, "used": 1, "left": 1})
        self.assertTrue(find_credits.record(self.db, self.user, "h2", "public.a", True))
        self.assertFalse(find_credits.check(self.db, "h3", True))
        self.assertTrue(find_credits.check(self.db, "h2", True))  # تکرار همان پرسش هنوز آزاد است
        self.assertTrue(find_credits.check(self.db, "h3", False))

    def test_period_is_thirty_days(self):
        find_credits.record(self.db, self.user, "old", "public.a", True)
        FindLog.objects.update(created_at=timezone.now() - timedelta(days=31))
        self.assertEqual(find_credits.status(self.db)["used"], 0)

    def test_zero_cap_blocks_cross_layer(self):
        self.plan.find_layer_credits = 0
        self.plan.save()
        self.assertFalse(find_credits.check(self.db, "x", True))


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
class FindIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000202")
        label = f"fd_{uuid.uuid4().hex[:8]}"
        self.db = services.create_database(self.user, label, "Find-Pass-12", ["postgis"])
        self.addCleanup(self._drop)
        with psycopg.connect(host=server.host, port=server.port, user=self.db.role_name, password="Find-Pass-12",
                             dbname=self.db.db_name, autocommit=True) as c:
            # ۲۰ مدرسه در یک ردیف روی طول ۵۱٫۴۰ تا ۵۱٫۴۹۵؛ نیمی «دخترانه» (با ي و ك عربی در داده)
            c.execute("CREATE TABLE schools(id serial PRIMARY KEY, name text, kind text, students int, opened date, "
                      "geom geometry(Point, 4326))")
            c.execute("INSERT INTO schools(name, kind, students, opened, geom) SELECT 'مدرسه ' || g, "
                      "CASE WHEN g % 2 = 0 THEN 'دخترانه' ELSE 'پسرانه' END, g * 50, date '2020-01-01' + g, "
                      "ST_SetSRID(ST_MakePoint(51.4 + g * 0.005, 35.7), 4326) FROM generate_series(1, 20) g")
            c.execute("UPDATE schools SET name = 'كتابخانه‌ي مركزي' WHERE id = 3")
            # دو محله در UTM 39N؛ نارمک شرق را می‌پوشاند
            c.execute("CREATE TABLE districts(id serial PRIMARY KEY, name text, geom geometry(Polygon, 32639))")
            c.execute("INSERT INTO districts(name, geom) VALUES "
                      "('نارمک', ST_Transform(ST_MakeEnvelope(51.4475, 35.69, 51.4975, 35.71, 4326), 32639)), "
                      "('ونک', ST_Transform(ST_MakeEnvelope(51.40, 35.69, 51.4275, 35.71, 4326), 32639))")
            c.execute("CREATE TABLE roads(id int PRIMARY KEY, geom geometry(LineString, 4326))")
            c.execute("INSERT INTO roads VALUES (1, ST_GeomFromText('LINESTRING(51.45 35.0, 51.45 36.0)', 4326))")
            c.execute("CREATE TABLE notes(id int PRIMARY KEY, txt text)")
            c.execute("INSERT INTO notes VALUES (1, 'سلام'), (2, NULL)")
        self.finder = Finder(Explorer(self.db))

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            services.delete_database(self.db)

    def _names(self, spec):
        out = self.finder.run(spec)
        return out, {r["v"][out["columns"].index("id")] for r in out["rows"]}

    def test_attribute_filters_with_persian_normalization(self):
        out, ids = self._names({"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}]})
        self.assertEqual(out["total"], 10)
        self.assertEqual(len(out["features"]["features"]), 10)
        self.assertEqual(len(out["bbox"]), 4)
        _, ids = self._names({"layer": "public.schools", "conds": [{"col": "name", "op": "contains", "v": "كتابخانه ي"}]})
        self.assertEqual(ids, set())  # فاصله‌ی اضافه درون عبارت هم‌خوان نیست
        _, ids = self._names({"layer": "public.schools", "conds": [{"col": "name", "op": "contains", "v": "کتابخانهی مرکزی"}]})
        self.assertEqual(ids, {"3"})
        _, ids = self._names({"layer": "public.schools", "match": "any", "conds": [
            {"col": "students", "op": "gte", "v": "۹۵۰"}, {"col": "opened", "op": "lte", "v": "1398/10/12"}]})
        self.assertEqual(ids, {"1", "19", "20"})  # ۲۰۲۰-۰۱-۰۲ = ۱۳۹۸/۱۰/۱۲
        out, _ = self._names({"layer": "public.notes", "conds": [{"col": "txt", "op": "empty"}]})
        self.assertEqual((out["total"], out["features"], out["bbox"]), (1, None, None))

    def test_cross_layer_relations_and_srid(self):
        narmak = {"kind": "layer", "layer": "public.districts", "conds": [{"col": "name", "op": "eq", "v": "نارمک"}]}
        out, ids = self._names({"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}],
                                "spatial": {"rel": "within", "target": narmak}})
        self.assertEqual(ids, {str(g) for g in range(10, 20, 2)})  # طول ۵۱٫۴۵ به بعد
        out, ids = self._names({"layer": "public.schools", "spatial": {"rel": "disjoint", "target": {
            "kind": "layer", "layer": "public.districts"}}})
        self.assertEqual(ids, {"6", "7", "8", "9", "20"})
        out, ids = self._names({"layer": "public.schools", "spatial": {"rel": "dwithin", "dist": "500", "target": {
            "kind": "layer", "layer": "public.roads"}}})
        self.assertEqual(ids, {"9", "10", "11"})  # هر ۰٫۰۰۵ درجه حدود ۴۵۰ متر
        out, ids = self._names({"layer": "public.districts", "spatial": {"rel": "contains", "target": {
            "kind": "layer", "layer": "public.schools", "conds": [{"col": "id", "op": "eq", "v": "3"}]}}})
        self.assertEqual(ids, {"2"})

    def test_drawn_shape_circle_and_extent(self):
        poly = {"type": "Polygon", "coordinates": [[[51.401, 35.69], [51.416, 35.69], [51.416, 35.71], [51.401, 35.71], [51.401, 35.69]]]}
        _, ids = self._names({"layer": "public.schools", "spatial": {"rel": "within", "target": {"kind": "shape", "geojson": poly}}})
        self.assertEqual(ids, {"1", "2", "3"})
        _, ids = self._names({"layer": "public.districts", "spatial": {"rel": "intersects", "target": {
            "kind": "circle", "lon": 51.41, "lat": 35.7, "r": 300}}})
        self.assertEqual(ids, {"2"})
        _, ids = self._names({"layer": "public.schools", "spatial": {"rel": "intersects", "target": {
            "kind": "extent", "bbox": [51.4, 35.6, 51.411, 35.8]}}})
        self.assertEqual(ids, {"1", "2"})
        _, ids = self._names({"layer": "public.schools", "spatial": {"rel": "dwithin", "dist": 100, "target": {
            "kind": "shape", "geojson": {"type": "Point", "coordinates": [51.45, 35.7]}}}})
        self.assertEqual(ids, {"10"})

    def test_rejects_unknown_names_and_empty_search(self):
        with self.assertRaises(FindError):
            self.finder.run({"layer": "public.missing", "conds": [{"col": "x", "op": "eq", "v": "1"}]})
        with self.assertRaises(FindError):
            self.finder.run({"layer": "public.schools", "conds": [{"col": "kind; drop", "op": "eq", "v": "1"}]})
        with self.assertRaises(FindError):
            self.finder.run({"layer": "public.schools"})
        with self.assertRaises(FindError):
            self.finder.run({"layer": "public.notes", "spatial": {"rel": "intersects", "target": {"kind": "extent", "bbox": [0, 0, 1, 1]}}})

    def test_values_and_endpoints(self):
        v = self.finder.values("public.schools", "kind")
        self.assertEqual({x["v"] for x in v["top"]}, {"دخترانه", "پسرانه"})
        self.assertEqual(self.finder.values("public.schools", "students")["min"], "50")
        self.client.force_login(self.user)
        page = self.client.get(reverse("databases:find", args=[self.db.pk]) + "?t=public.schools")
        self.assertContains(page, "یافتن عارضه")
        cols = self.client.get(reverse("databases:find_columns", args=[self.db.pk]), {"t": "public.schools"}).json()
        self.assertIn({"name": "kind", "kind": "text", "type": "text", "pk": False}, cols["columns"])

        self.db.plan.find_layer_credits = 1
        self.db.plan.save()
        url = reverse("databases:find_run", args=[self.db.pk])
        cross = {"layer": "public.schools", "spatial": {"rel": "intersects", "target": {"kind": "layer", "layer": "public.districts"}}}
        post = lambda spec, page=1: self.client.post(url, json.dumps({"spec": spec, "page": page}),  # noqa: E731
                                                     content_type="application/json")
        r = post(cross).json()
        self.assertTrue(r["ok"] and r["charged"])
        self.assertEqual((r["total"], r["credits"]["left"]), (15, 0))
        self.assertTrue(post(cross, 2).json()["ok"])  # ورق زدن همان پرسش رایگان است
        other = {**cross, "conds": [{"col": "kind", "op": "eq", "v": "پسرانه"}]}
        r = post(other)
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.json()["upgrade"])
        r = post({"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "پسرانه"}]}).json()
        self.assertTrue(r["ok"] and not r["charged"])  # شرط توصیفی همیشه آزاد
        bad = post({"layer": "public.schools", "conds": [{"col": "students", "op": "gt", "v": "زیاد"}]})
        self.assertEqual(bad.status_code, 400)

        stranger = User.objects.create_user("09120000203")
        self.client.force_login(stranger)
        self.assertEqual(post(cross).status_code, 404)

    # ------------------------------------------------------------------ ذخیره به‌صورت لایه
    def _save(self, spec, **opts):
        """ساخت لایه با همان مسیر کارگر؛ نتیجه‌ی کار پس‌زمینه را برمی‌گرداند."""
        from jobs import services as jobs
        from jobs.models import Job

        self.client.force_login(self.user)
        r = self.client.post(reverse("databases:find_save", args=[self.db.pk]),
                             json.dumps({"spec": spec, "opts": opts}), content_type="application/json")
        if r.status_code != 200:
            return r.json(), None
        job = jobs.claim_next()
        self.assertEqual(job.pk, r.json()["job"])
        jobs.run(job)
        job = Job.objects.get(pk=job.pk)
        st = self.client.get(reverse("databases:find_save_status", args=[self.db.pk]), {"job": job.pk}).json()
        return st, job

    def _q(self, query, *args):
        with psycopg.connect(host=self.db.server.host, port=self.db.server.port, user=self.db.role_name,
                             password="Find-Pass-12", dbname=self.db.db_name, autocommit=True) as c:
            cur = c.execute(query, args)
            return cur.fetchall() if cur.description else []

    def test_save_table_and_live_view(self):
        spec = {"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}]}
        st, _ = self._save(spec, name="girls_found")
        self.assertEqual((st["status"], st["rows"], st["kind"]), ("done", 10, "table"))
        self.assertEqual(self._q("SELECT count(*) FROM girls_found")[0][0], 10)
        # کلید اصلی منبع می‌ماند و نمایه‌ی مکانی ساخته می‌شود؛ هندسه‌ی نوع‌دار است
        self.assertEqual(self._q("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                                 "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = 'girls_found'::regclass AND i.indisprimary"),
                         [("id",)])
        self.assertEqual(self._q("SELECT type, srid FROM geometry_columns WHERE f_table_name = 'girls_found'"), [("POINT", 4326)])
        self.assertIn("kind", self._q("SELECT obj_description('girls_found'::regclass)")[0][0])
        # نمای زنده با تغییر داده‌ی اصلی به‌روز می‌شود
        st, _ = self._save(spec, name="girls_live", kind="view")
        self.assertEqual((st["status"], st["rows"], st["kind"]), ("done", 10, "view"))
        self._q("UPDATE schools SET kind = 'دخترانه' WHERE id = 1")
        self.assertEqual(self._q("SELECT count(*) FROM girls_live")[0][0], 11)
        self.assertEqual(self._q("SELECT count(*) FROM girls_found")[0][0], 10)

    def test_scope_invert_and_columns(self):
        spec = {"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}]}  # شناسه‌های زوج
        st, _ = self._save(spec, name="pick", scope="selected", ids=["2", "4", "5"], cols=["name"])
        self.assertEqual(st["rows"], 2)  # ۵ دخترانه نیست و کنار گذاشته می‌شود
        self.assertEqual({r[0] for r in self._q("SELECT column_name FROM information_schema.columns WHERE table_name = 'pick'")},
                         {"id", "name", "geom"})
        st, _ = self._save(spec, name="rest", scope="except", ids=["2", "4"])
        self.assertEqual(st["rows"], 8)
        st, _ = self._save(spec, name="boys", invert=True)
        self.assertEqual(st["rows"], 10)
        self.assertEqual(self._q("SELECT DISTINCT kind FROM boys"), [("پسرانه",)])

    def test_join_columns_distance_and_srid(self):
        spec = {"layer": "public.schools", "spatial": {"rel": "dwithin", "dist": 500, "target": {
            "kind": "layer", "layer": "public.roads"}}}
        st, _ = self._save(spec, name="near_road", cols=["name"], join_cols=["id"], dist_col=True, srid="4326")
        self.assertEqual((st["status"], st["rows"]), ("done", 3))
        cols = {r[0] for r in self._q("SELECT column_name FROM information_schema.columns WHERE table_name = 'near_road'")}
        self.assertEqual(cols, {"id", "name", "geom", "roads_id", "distance_m"})
        self.assertTrue(all(0 <= r[0] <= 500 for r in self._q("SELECT distance_m FROM near_road")))
        # لایه‌ی هدف چندضلعی در UTM: تبدیل به ۴۳۲۶
        st, _ = self._save({"layer": "public.districts", "conds": [{"col": "name", "op": "eq", "v": "نارمک"}]},
                           name="narmak", srid="4326")
        self.assertEqual(self._q("SELECT srid FROM geometry_columns WHERE f_table_name = 'narmak'"), [(4326,)])
        # خطاهای معنایی
        for opts in ({"name": "x", "join_cols": ["id"]}, {"name": "x", "dist_col": True}):
            st, _ = self._save({"layer": "public.schools", "conds": [{"col": "id", "op": "gt", "v": "0"}]}, **opts)
            self.assertFalse(st["ok"])
        st, _ = self._save({**spec, "spatial": {**spec["spatial"], "rel": "disjoint"}}, name="x", join_cols=["id"])
        self.assertFalse(st["ok"])

    def test_name_clash_replace_and_permissions(self):
        spec = {"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}]}
        self._save(spec, name="dup")
        st, _ = self._save(spec, name="dup")
        self.assertFalse(st["ok"])
        self.assertIn("از قبل", st["error"])
        st, _ = self._save({"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "پسرانه"}]},
                           name="dup", replace=True)
        self.assertEqual((st["status"], st["rows"]), ("done", 10))
        self.assertEqual(self._q("SELECT DISTINCT kind FROM dup"), [("پسرانه",)])
        st, _ = self._save(spec, name="schools")  # روی لایه‌ی اصلی نمی‌نویسد
        self.assertFalse(st["ok"])
        # بدون کلید اصلی انتخاب دستی ممکن نیست؛ و غیراعضا ۴۰۴ می‌گیرند
        st, _ = self._save({"layer": "public.notes", "conds": [{"col": "txt", "op": "notempty"}]}, name="n1", scope="selected", ids=["1"])
        self.assertEqual((st["status"], st["rows"]), ("done", 1))
        stranger = User.objects.create_user("09120000204")
        self.client.force_login(stranger)
        r = self.client.post(reverse("databases:find_save", args=[self.db.pk]), json.dumps({"spec": spec, "opts": {"name": "zz"}}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_sql_preview_and_run_exposes_pk(self):
        out = self.finder.run({"layer": "public.schools", "conds": [{"col": "id", "op": "lte", "v": "3"}]})
        self.assertEqual(out["pk"], "id")
        self.assertEqual([r["k"] for r in out["rows"]], ["1", "2", "3"])
        self.assertEqual({f["properties"]["__k"] for f in out["features"]["features"]}, {"1", "2", "3"})
        self.client.force_login(self.user)
        r = self.client.post(reverse("databases:find_sql", args=[self.db.pk]), json.dumps({
            "spec": {"layer": "public.schools", "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}]},
            "opts": {"kind": "view"}}), content_type="application/json").json()
        self.assertTrue(r["ok"])
        self.assertTrue(r["sql"].startswith("CREATE VIEW public.find_result AS"))
        self.assertIn("'دخترانه'", r["sql"])
