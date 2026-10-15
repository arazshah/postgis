"""انتشار لایه: کاشی برداری، OGC API Features، کلید API و سقف روزانه روی PostGIS واقعی."""
import json
import os
import unittest
import uuid

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from publish.models import ApiKey, DailyUsage, Layer

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def tile_of(lon, lat, z):
    import math
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return f"{z}/{x}/{y}"


T = tile_of(51.34, 35.70, 10)


class KeyTests(TestCase):
    def test_key_hashing(self):
        self.assertEqual(len(ApiKey.digest("gpk_x")), 64)
        self.assertNotEqual(ApiKey.digest("gpk_a"), ApiKey.digest("gpk_b"))


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class PublishIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000096")
        self.db = db_services.create_database(self.user, f"pb_{uuid.uuid4().hex[:8]}", "Publish-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        with psycopg.connect(host=server.host, port=server.port, user=self.db.role_name, password="Publish-Pass-1",
                             dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE schools(gid serial PRIMARY KEY, name text, students int, price numeric,"
                      " geom geometry(Point, 32639))")
            c.execute("INSERT INTO schools(name, students, price, geom) SELECT 'مدرسه ' || g, g * 10, g * 1.5,"
                      " ST_Transform(ST_SetSRID(ST_MakePoint(51.30 + g * 0.002, 35.70), 4326), 32639)"
                      " FROM generate_series(1, 40) g")
            c.execute("CREATE TABLE parks(id serial PRIMARY KEY, name text, geom geometry(Polygon, 4326))")
            c.execute("INSERT INTO parks(name, geom) VALUES ('پارک', ST_Buffer(ST_SetSRID(ST_MakePoint(51.4, 35.7),"
                      " 4326), 0.01))")
        self.client.force_login(self.user)
        self._publish("schools", public=True)
        self._publish("parks", public=False)
        self.schools = Layer.objects.get(table="schools")
        self.parks = Layer.objects.get(table="parks")
        self.svc = self.schools.service.slug
        self.client.logout()  # درخواست‌های بعدی مثل یک بازدیدکننده بیرونی

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _publish(self, table, public):
        data = {"schema": "public", "table": table}
        if public:
            data["public"] = "on"
        self.client.post(reverse("publish:publish_table", args=[self.db.pk]), data)

    def test_layers_created_with_metadata(self):
        self.assertEqual((self.schools.srid, self.schools.pk_column), (32639, "gid"))
        self.assertAlmostEqual(self.schools.bbox[1], 35.70, places=3)

    def test_public_tile_and_tilejson(self):
        r = self.client.get(f"/tiles/{self.schools.slug}.json")
        self.assertEqual(r.status_code, 200)
        tj = r.json()
        self.assertTrue(tj["tiles"][0].endswith(f"/tiles/{self.schools.slug}/{{z}}/{{x}}/{{y}}.mvt"))
        self.assertEqual(tj["vector_layers"][0]["id"], "schools")
        r = self.client.get(f"/tiles/{self.schools.slug}/{T}.mvt")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/vnd.mapbox-vector-tile")
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
        self.assertGreater(len(r.content), 100)
        self.assertIn("مدرسه".encode(), r.content)
        self.assertEqual(self.client.get(f"/tiles/{self.schools.slug}/3/0/0.mvt").content, b"")  # خارج از داده
        self.assertEqual(self.client.get(f"/tiles/{self.schools.slug}/3/99/0.mvt").status_code, 400)

    def test_private_layer_needs_key(self):
        url = f"/tiles/{self.parks.slug}/{T}.mvt"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url + "?key=gpk_wrong").status_code, 403)
        key, raw = ApiKey.issue(self.db, self.user, "t")
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {raw}").status_code, 200)
        self.assertEqual(self.client.get(url, HTTP_X_API_KEY=raw).status_code, 200)
        key.revoke()
        self.assertEqual(self.client.get(url, HTTP_X_API_KEY=raw).status_code, 403)
        # کلید یک پایگاه داده دیگر کار نمی‌کند
        other_user = User.objects.create_user("09120000094")
        other = db_services.create_database(other_user, f"o_{uuid.uuid4().hex[:6]}", "Publish-Pass-1", ["postgis"])
        self.addCleanup(db_services.delete_database, other)
        _k, raw2 = ApiKey.issue(other, other_user, "o")
        self.assertEqual(self.client.get(url + f"?key={raw2}").status_code, 403)

    def test_ogc_api(self):
        base = f"/ogc/{self.svc}"
        land = self.client.get(base + "/").json()
        self.assertIn("conformance", [x["rel"] for x in land["links"]])
        self.assertIn("http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                      self.client.get(base + "/conformance").json()["conformsTo"])
        ids = [c["id"] for c in self.client.get(base + "/collections").json()["collections"]]
        self.assertEqual(ids, ["schools"])  # لایه خصوصی بدون کلید دیده نمی‌شود
        _k, raw = ApiKey.issue(self.db, self.user, "q")
        ids = [c["id"] for c in self.client.get(base + "/collections", HTTP_AUTHORIZATION=f"Bearer {raw}")
               .json()["collections"]]
        self.assertEqual(sorted(ids), ["parks", "schools"])
        r = self.client.get(base + "/collections/schools/items?limit=10")
        self.assertEqual(r["Content-Type"], "application/geo+json; charset=utf-8")
        fc = r.json()
        self.assertEqual(fc["numberReturned"], 10)
        lon, lat = fc["features"][0]["geometry"]["coordinates"]
        self.assertAlmostEqual(lat, 35.70, places=3)  # از UTM به طول و عرض
        self.assertIsInstance(fc["features"][0]["properties"]["price"], float)
        self.assertIn("next", [x["rel"] for x in fc["links"]])
        fc = self.client.get(base + "/collections/schools/items", {"name": "مدرسه 3"}).json()
        self.assertEqual([f["id"] for f in fc["features"]], [3])
        fc = self.client.get(base + "/collections/schools/items?bbox=51.30,35.69,51.31,35.71").json()
        self.assertEqual(fc["numberReturned"], 5)
        feat = self.client.get(base + "/collections/schools/items/7").json()
        self.assertEqual(feat["properties"]["name"], "مدرسه 7")
        self.assertEqual(self.client.get(base + "/collections/parks/items").status_code, 404)
        self.assertEqual(self.client.get(base + "/collections/schools/items?bbox=1,2").status_code, 400)

    def test_column_selection(self):
        self.schools.columns = ["name"]
        self.schools.save()
        fc = self.client.get(f"/ogc/{self.svc}/collections/schools/items?limit=1").json()
        self.assertEqual(list(fc["features"][0]["properties"]), ["name"])

    def test_daily_cap(self):
        self.db.plan.publish_daily_requests = 3
        self.db.plan.save()
        url = f"/tiles/{self.schools.slug}/{T}.mvt"
        codes = [self.client.get(url).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(DailyUsage.objects.get(database=self.db).requests, 4)
        self.client.force_login(self.user)  # پیش‌نمایش مالک در سایت شمرده نمی‌شود و بسته نمی‌شود
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_inactive_database_and_unpublish(self):
        url = f"/tiles/{self.schools.slug}/{T}.mvt"
        self.db.status = "expired"
        self.db.save()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.db.status = "active"
        self.db.save()
        self.client.force_login(self.user)
        self.client.post(reverse("publish:update_layer", args=[self.db.pk, self.schools.pk]), {"action": "unpublish"})
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_layer_limit_and_manage_page(self):
        self.db.plan.publish_layers = 2
        self.db.plan.save()
        with psycopg.connect(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=self.db.role_name,
                             password="Publish-Pass-1", dbname=self.db.db_name, autocommit=True) as c:
            c.execute("CREATE TABLE extra(id int primary key, geom geometry(Point, 4326))")
        self.client.force_login(self.user)
        r = self.client.post(reverse("publish:publish_table", args=[self.db.pk]),
                             {"schema": "public", "table": "extra"}, follow=True)
        self.assertContains(r, "حداکثر 2 لایه")
        r = self.client.get(reverse("publish:manage", args=[self.db.pk]))
        self.assertContains(r, f"/tiles/{self.schools.slug}.json")
        self.assertContains(r, f"/ogc/{self.svc}/")
        stranger = User.objects.create_user("09120000095")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("publish:manage", args=[self.db.pk])).status_code, 404)

    # ------------------------------------------------------------------ صفحه نقشه
    def test_map_builder_validates_style(self):
        self.client.force_login(self.user)
        url = reverse("publish:map_builder", args=[self.db.pk, self.schools.pk])
        r = self.client.get(url)
        self.assertContains(r, "students")
        self.assertContains(r, f"/m/{self.schools.slug}/embed/")
        bad = {"mode": "graduated", "field": "students", "palette": "Nope", "color": "red;}", "outline": "#FFFFFF",
               "opacity": 7, "size": "x", "classes": 50, "breaks": [100, "200", 300],
               "categories": [{"value": "a", "color": "javascript:"}], "popup": ["name", "geom", "missing"],
               "evil": "<script>", "label": "name", "label_size": 99, "label_color": "blue", "basemap": "iran"}
        r = self.client.post(url, {"style": json.dumps(bad), "title": "مدارس تهران"})
        self.assertRedirects(r, url)
        self.schools.refresh_from_db()
        st = self.schools.style
        self.assertEqual((st["mode"], st["field"], st["palette"], st["color"]), ("graduated", "students", "YlOrRd",
                                                                               "#0F5C59"))
        self.assertEqual((st["opacity"], st["size"], st["classes"]), (1, 6, 9))
        self.assertEqual(st["breaks"], [100.0, 200.0, 300.0])
        self.assertEqual(st["categories"], [])
        self.assertEqual(st["popup"], ["name"])
        self.assertNotIn("evil", st)
        self.assertEqual((st["label"], st["label_size"], st["label_color"], st["basemap"]),
                         ("name", 24, "#1B2B2F", "iran"))
        self.assertEqual(self.schools.title, "مدارس تهران")
        # ستونی که وجود ندارد: برمی‌گردد به تک‌رنگ
        self.client.post(url, {"style": json.dumps({"mode": "categorized", "field": "nope"})})
        self.schools.refresh_from_db()
        self.assertEqual((self.schools.style["mode"], self.schools.style["field"]), ("single", ""))

    def test_map_builder_only_owner(self):
        other = User.objects.create_user("09120000095")
        self.client.force_login(other)
        r = self.client.get(reverse("publish:map_builder", args=[self.db.pk, self.schools.pk]))
        self.assertEqual(r.status_code, 404)

    def test_map_stats(self):
        self.client.force_login(self.user)
        url = reverse("publish:map_stats", args=[self.db.pk, self.schools.pk])
        r = self.client.get(url, {"field": "students", "mode": "graduated", "classes": 4})
        self.assertEqual(r.status_code, 200)
        breaks = r.json()["breaks"]
        self.assertEqual(len(breaks), 3)
        self.assertEqual(breaks, sorted(breaks))
        r = self.client.get(url, {"field": "name", "mode": "categorized"})
        self.assertEqual(len(r.json()["values"]), len(r.json()["colors"]))
        r = self.client.get(url, {"field": "nope; drop table", "mode": "graduated"})
        self.assertEqual(r.status_code, 400)

    def test_public_map_and_embed(self):
        r = self.client.get(f"/m/{self.schools.slug}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertContains(r, f"/tiles/{self.schools.slug}/")
        self.assertContains(r, "ساخته‌شده با")  # پلن رایگان: نشان سایت
        r = self.client.get(f"/m/{self.schools.slug}/embed/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("X-Frame-Options", r)
        # لایه خصوصی برای بیرونی‌ها وجود ندارد؛ مالک می‌بیند
        self.assertEqual(self.client.get(f"/m/{self.parks.slug}/").status_code, 404)
        self.assertEqual(self.client.get(f"/m/{self.parks.slug}/embed/").status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/m/{self.parks.slug}/").status_code, 200)
        self.client.logout()
        # پایگاه داده غیرفعال: نقشه هم بسته می‌شود
        self.db.status = "suspended"
        self.db.save(update_fields=["status"])
        self.assertEqual(self.client.get(f"/m/{self.schools.slug}/").status_code, 404)

    def test_parallel_tiles_share_connection_limit(self):
        """بیشتر از سقف ۳ اتصال نقش مرورگر، کاشی هم‌زمان؛ هیچ‌کدام نباید 503 بدهد."""
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connections

        from publish import engine

        layer = Layer.objects.select_related("service__database__server").get(pk=self.schools.pk)
        z, x, y = (int(v) for v in T.split("/"))

        def one(i):
            try:
                return len(engine.tile(layer, z, x + (i % 2), y)) >= 0
            finally:
                connections.close_all()

        with ThreadPoolExecutor(8) as pool:
            self.assertTrue(all(pool.map(one, range(16))))
