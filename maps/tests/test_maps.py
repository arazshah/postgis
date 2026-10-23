"""نقشه چندلایه روی PostGIS واقعی: ساخت، افزودن لایه، سبک، کاشی هر لایه، نمایش با هم و دسترسی."""
import json
import os
import unittest
import uuid

import psycopg
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases.models import DatabaseServer, Member
from databases.provisioner import Provisioner
from maps.models import MapLayer, WebMap
from maps.services import default_style
from publish.models import ApiKey, DailyUsage, Layer
from publish.tests.test_publish import T

PG_HOST = os.environ.get("TEST_PG_HOST", "")


class ColumnsTests(TestCase):
    def test_tile_columns_follow_popup(self):
        layer = MapLayer(style={"popup": []})
        self.assertEqual(layer.columns, [])  # همه ستون‌ها
        layer.style = {"popup": ["name"], "field": "students", "label": "name"}
        self.assertEqual(layer.columns, ["name", "students"])

    def test_default_styles_differ(self):
        self.assertNotEqual(default_style(0)["color"], default_style(1)["color"])
        self.assertNotIn("basemap", default_style(0))


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class MapsIntegrationTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000081")
        self.db = db_services.create_database(self.user, f"mp_{uuid.uuid4().hex[:8]}", "Maps-Pass-1", ["postgis"])
        self.addCleanup(self._drop)
        with self._pg() as c:
            c.execute("CREATE TABLE schools(gid serial PRIMARY KEY, name text, students int, secret text,"
                      " geom geometry(Point, 32639))")
            c.execute("INSERT INTO schools(name, students, secret, geom) SELECT 'مدرسه ' || g, g * 10, 'رمز' || g,"
                      " ST_Transform(ST_SetSRID(ST_MakePoint(51.30 + g * 0.002, 35.70), 4326), 32639)"
                      " FROM generate_series(1, 40) g")
            c.execute("CREATE TABLE parks(id serial PRIMARY KEY, name text, geom geometry(Polygon, 4326))")
            c.execute("INSERT INTO parks(name, geom) VALUES ('پارک ملت', ST_Buffer(ST_SetSRID("
                      "ST_MakePoint(51.34, 35.70), 4326), 0.01))")
            c.execute("CREATE TABLE notes(id int, txt text)")
            c.execute("CREATE TABLE nosrid(id int, geom geometry)")
        self.client.force_login(self.user)

    def _pg(self):
        return psycopg.connect(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=self.db.role_name,
                               password="Maps-Pass-1", dbname=self.db.db_name, autocommit=True)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _create(self, *keys, title="مدرسه‌ها و پارک‌ها"):
        r = self.client.post(reverse("maps:create", args=[self.db.pk]), {"title": title, "t": list(keys)})
        return r

    def _save(self, webmap, **data):
        return self.client.post(reverse("maps:composer", args=[self.db.pk, webmap.pk]), json.dumps(data),
                                content_type="application/json")

    # ------------------------------------------------------------------ ساخت و طراحی
    def test_create_map_with_tables(self):
        r = self._create("public.schools", "public.parks")
        m = WebMap.objects.get(database=self.db)
        self.assertRedirects(r, reverse("maps:composer", args=[self.db.pk, m.pk]))
        layers = list(m.layers.all())
        self.assertEqual([x.table for x in layers], ["schools", "parks"])  # اولی بالاتر
        self.assertEqual((layers[0].srid, layers[0].geom_column, layers[0].geom_type), (32639, "geom", "POINT"))
        self.assertAlmostEqual(layers[0].bbox[1], 35.70, places=3)
        self.assertNotEqual(layers[0].style["color"], layers[1].style["color"])
        # سهمیه لایه‌های منتشرشده دست نخورده است
        self.assertFalse(Layer.objects.exists())
        page = self.client.get(reverse("maps:composer", args=[self.db.pk, m.pk]))
        self.assertContains(page, "students")
        self.assertContains(page, f"/maps/{m.slug}/t/{layers[0].pk}/")
        self.assertContains(page, "nosrid", count=0)  # بدون SRID قابل افزودن نیست
        self.assertNotContains(page, ">notes")
        # استودیوی تمام‌صفحه: ریل چهار تب، بدون فوتر سایت؛ صفحه‌های دیگر فوتر دارند
        self.assertContains(page, 'id="studio"')
        self.assertContains(page, 'class="is-studio"')
        for tab in ("layers", "slides", "map", "share"):
            self.assertContains(page, f'data-tab="{tab}"')
        self.assertNotContains(page, 'class="footer"')
        self.assertContains(self.client.get(reverse("maps:index", args=[self.db.pk])), 'class="footer"')

    def test_add_and_remove_layer(self):
        self._create("public.schools")
        m = WebMap.objects.get()
        url = reverse("maps:layer_add", args=[self.db.pk, m.pk])
        r = self.client.post(url, {"t": "public.parks"})
        self.assertEqual(r.status_code, 200)
        data = r.json()["layer"]
        self.assertEqual((data["table"], data["geomType"]), ("parks", "POLYGON"))
        self.assertIn(["name", "text"], data["fields"])
        self.assertEqual([x.table for x in m.layers.all()], ["parks", "schools"])  # تازه بالای بقیه
        self.assertIn("از قبل", self.client.post(url, {"t": "public.parks"}).json()["error"])
        self.assertEqual(self.client.post(url, {"t": "public.notes"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"t": "public.nosrid"}).status_code, 400)
        parks = m.layers.get(table="parks")
        r = self.client.post(reverse("maps:layer_remove", args=[self.db.pk, m.pk, parks.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x.table for x in m.layers.all()], ["schools"])

    def test_save_validates_everything(self):
        self._create("public.schools", "public.parks")
        m = WebMap.objects.get()
        schools, parks = m.layers.get(table="schools"), m.layers.get(table="parks")
        other = WebMap.objects.create(database=self.db, title="x")
        foreign = MapLayer.objects.create(webmap=other, table="parks", geom_column="geom")
        bad_style = {"mode": "graduated", "field": "students", "palette": "Nope", "color": "red;}", "opacity": 7,
                     "popup": ["name", "geom", "missing"], "label": "name", "basemap": "iran", "evil": "<script>"}
        r = self._save(m, title="  نقشه منطقه ۶ ", description="d" * 2000, is_public=True, basemap="evil",
                       view={"center": [51.3, 35.7], "zoom": 99},
                       layers=[{"id": parks.pk, "title": "پارک‌ها", "visible": False, "style": {"color": "#112233"}},
                               {"id": schools.pk, "style": bad_style}, {"id": foreign.pk, "title": "hack"},
                               {"id": "x"}, "junk"])
        self.assertEqual(r.status_code, 200)
        m.refresh_from_db()
        self.assertEqual((m.title, len(m.description), m.is_public, m.basemap, m.view),
                         ("نقشه منطقه ۶", 1000, True, "osm", {}))
        self.assertEqual([x.table for x in m.layers.all()], ["parks", "schools"])
        parks.refresh_from_db()
        schools.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual((parks.title, parks.visible, parks.style["color"]), ("پارک‌ها", False, "#112233"))
        st = schools.style
        self.assertEqual((st["mode"], st["field"], st["palette"], st["color"], st["opacity"]),
                         ("graduated", "students", "YlOrRd", "#0F5C59", 1))
        self.assertEqual((st["popup"], st["label"]), (["name"], "name"))
        self.assertNotIn("evil", st)
        self.assertNotIn("basemap", st)
        self.assertEqual(foreign.title, "")  # لایه نقشه دیگر دست نخورد
        self._save(m, title="", view={"center": [51.3, 35.7], "zoom": 12.345}, layers=[])
        m.refresh_from_db()
        self.assertEqual((m.title, m.view), ("نقشه منطقه ۶", {"center": [51.3, 35.7], "zoom": 12.35}))
        self.assertEqual(self.client.post(reverse("maps:composer", args=[self.db.pk, m.pk]), "nope",
                                          content_type="application/json").status_code, 400)

    def test_layer_stats_use_all_columns(self):
        self._create("public.schools")
        m = WebMap.objects.get()
        layer = m.layers.get()
        layer.style = {**layer.style, "popup": ["name"]}  # کاشی فقط name دارد، ولی آمار روی همه ستون‌ها
        layer.save()
        url = reverse("maps:layer_stats", args=[self.db.pk, m.pk, layer.pk])
        r = self.client.get(url, {"field": "students", "mode": "graduated", "classes": 4})
        self.assertEqual(len(r.json()["breaks"]), 3)
        r = self.client.get(url, {"field": "name", "mode": "categorized"})
        self.assertEqual(len(r.json()["values"]), len(r.json()["colors"]))
        self.assertEqual(self.client.get(url, {"field": "x; drop", "mode": "graduated"}).status_code, 400)

    def test_quotas(self):
        self.db.plan.maps, self.db.plan.map_layers = 1, 1
        self.db.plan.save()
        r = self._create("public.schools", "public.parks")
        self.assertRedirects(r, reverse("maps:index", args=[self.db.pk]), fetch_redirect_response=False)
        self.assertFalse(WebMap.objects.exists())
        self._create("public.schools")
        m = WebMap.objects.get()
        r = self.client.post(reverse("maps:layer_add", args=[self.db.pk, m.pk]), {"t": "public.parks"})
        self.assertIn("حداکثر 1 لایه", r.json()["error"])
        r = self.client.post(reverse("maps:create", args=[self.db.pk]), {"title": "دوم"}, follow=True)
        self.assertContains(r, "حداکثر 1 نقشه")
        self.client.post(reverse("maps:duplicate", args=[self.db.pk, m.pk]))
        self.assertEqual(WebMap.objects.count(), 1)
        self.db.plan.maps = 2
        self.db.plan.save()
        self.client.post(reverse("maps:duplicate", args=[self.db.pk, m.pk]))
        copy = WebMap.objects.exclude(pk=m.pk).get()
        self.assertEqual([x.table for x in copy.layers.all()], ["schools"])
        self.assertNotEqual(copy.slug, m.slug)

    # ------------------------------------------------------------------ مرورگر جدول
    def test_add_table_from_explorer(self):
        url = reverse("maps:add_table", args=[self.db.pk])
        r = self.client.post(url, {"schema": "public", "table": "schools", "map": "new"})
        m = WebMap.objects.get()
        self.assertRedirects(r, reverse("maps:composer", args=[self.db.pk, m.pk]))
        self.assertEqual(m.title, "نقشه schools")
        self.client.post(url, {"schema": "public", "table": "parks", "map": str(m.pk)})
        self.assertEqual(m.layers.count(), 2)
        page = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "parks"]) + "?tab=map")
        self.assertContains(page, "افزودن به نقشه")
        self.assertContains(page, m.title)
        page = self.client.get(reverse("databases:explore", args=[self.db.pk]))
        self.assertContains(page, 'value="public.schools"')
        self.assertNotContains(page, 'value="public.nosrid"')
        # حذف جدول، لایه نقشه را هم برمی‌دارد
        self.client.post(reverse("databases:explore_drop", args=[self.db.pk, "public", "parks"]), {"confirm": "parks"})
        self.assertEqual([x.table for x in m.layers.all()], ["schools"])

    def test_quick_view_and_preview_tiles(self):
        url = reverse("maps:quick", args=[self.db.pk])
        r = self.client.get(url, {"t": ["public.parks", "public.schools", "public.notes", "public.nope"]})
        self.assertEqual(r.status_code, 200)
        cfg = r.context["config"]
        self.assertEqual([x["table"] for x in cfg["layers"]], ["parks", "schools"])
        self.assertFalse(WebMap.objects.exists())  # چیزی ذخیره نشد
        tile = self.client.get(cfg["layers"][1]["tiles"].replace("http://testserver", "").replace("{z}/{x}/{y}", T))
        self.assertEqual(tile.status_code, 200)
        self.assertIn("مدرسه".encode(), tile.content)
        self.assertEqual(tile["Cache-Control"], "private, max-age=0, no-store")
        self.assertRedirects(self.client.get(url), reverse("databases:explore", args=[self.db.pk]),
                             fetch_redirect_response=False)
        # ذخیره همان انتخاب به‌عنوان نقشه
        r = self.client.post(reverse("maps:create", args=[self.db.pk]),
                             {"title": "مقایسه", "t": ["public.parks", "public.schools"], "back": "quick"})
        self.assertEqual([x.table for x in WebMap.objects.get().layers.all()], ["parks", "schools"])
        # بیرونی‌ها کاشی پیش‌نمایش ندارند
        self.client.logout()
        self.assertEqual(self.client.get(f"/dashboard/{self.db.pk}/maps/preview/public/schools/{T}.mvt").status_code,
                         302)

    # ------------------------------------------------------------------ صفحه عمومی و کاشی‌ها
    def test_public_and_private_map(self):
        self._create("public.schools", "public.parks")
        m = WebMap.objects.get()
        schools = m.layers.get(table="schools")
        schools.style = {**schools.style, "popup": ["name"]}
        schools.save()
        tile_url = f"/maps/{m.slug}/t/{schools.pk}/{T}.mvt"
        # مالک نقشه خصوصی را می‌بیند و شمرده نمی‌شود
        self.assertEqual(self.client.get(f"/maps/{m.slug}/").status_code, 200)
        self.assertEqual(self.client.get(tile_url).status_code, 200)
        self.assertFalse(DailyUsage.objects.exists())
        self.client.logout()
        self.assertEqual(self.client.get(f"/maps/{m.slug}/").status_code, 404)
        self.assertEqual(self.client.get(f"/maps/{m.slug}/embed/").status_code, 404)
        self.assertEqual(self.client.get(tile_url).status_code, 401)
        _k, raw = ApiKey.issue(self.db, self.user, "k")
        self.assertEqual(self.client.get(tile_url + f"?key={raw}").status_code, 200)
        m.is_public = True
        m.save()
        r = self.client.get(f"/maps/{m.slug}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertContains(r, "ساخته‌شده با")
        self.assertEqual(len(r.context["config"]["layers"]), 2)
        self.assertNotIn("fields", r.context["config"]["layers"][0])
        r = self.client.get(f"/maps/{m.slug}/embed/")
        self.assertNotIn("X-Frame-Options", r)
        tile = self.client.get(tile_url)
        self.assertEqual(tile.status_code, 200)
        self.assertEqual(tile["Access-Control-Allow-Origin"], "*")
        self.assertIn("مدرسه".encode(), tile.content)
        self.assertNotIn("رمز".encode(), tile.content)  # ستون بیرون از پنجره اطلاعات فرستاده نمی‌شود
        self.assertEqual(DailyUsage.objects.get(database=self.db).requests, 2)
        # لایه نقشه دیگر با slug این نقشه در دسترس نیست
        other = WebMap.objects.create(database=self.db, title="o")
        hidden = MapLayer.objects.create(webmap=other, table="schools", geom_column="geom", srid=32639)
        self.assertEqual(self.client.get(f"/maps/{m.slug}/t/{hidden.pk}/{T}.mvt").status_code, 404)
        self.assertEqual(self.client.get(f"/maps/{m.slug}/t/{schools.pk}/3/99/0.mvt").status_code, 400)
        # سقف روزانه
        self.db.plan.publish_daily_requests = 2
        self.db.plan.save()
        self.assertEqual(self.client.get(tile_url).status_code, 429)
        # پایگاه داده غیرفعال
        self.db.status = "expired"
        self.db.save(update_fields=["status"])
        self.assertEqual(self.client.get(f"/maps/{m.slug}/").status_code, 404)
        self.assertEqual(self.client.get(tile_url).status_code, 403)

    def test_missing_table_tile_is_404(self):
        self._create("public.parks")
        m = WebMap.objects.get()
        layer = m.layers.get()
        with self._pg() as c:
            c.execute("ALTER TABLE parks RENAME TO gardens")
        self.assertEqual(self.client.get(f"/maps/{m.slug}/t/{layer.pk}/{T}.mvt").status_code, 404)
        page = self.client.get(reverse("maps:composer", args=[self.db.pk, m.pk]))
        self.assertTrue(page.context["config"]["layers"][0]["missing"])

    # ------------------------------------------------------------------ تیم
    def test_team_levels(self):
        self._create("public.schools")
        m = WebMap.objects.get()
        viewer = User.objects.create_user("09120000082")
        Member.objects.create(database=self.db, user=viewer, phone=viewer.phone, role=Member.Role.VIEWER)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("maps:index", args=[self.db.pk])).status_code, 200)
        self.assertEqual(self.client.get(f"/maps/{m.slug}/").status_code, 200)  # نقشه خصوصی تیم
        self.assertEqual(self.client.get(reverse("maps:quick", args=[self.db.pk]), {"t": "public.schools"})
                         .status_code, 200)
        self.assertEqual(self.client.get(reverse("maps:composer", args=[self.db.pk, m.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("maps:delete", args=[self.db.pk, m.pk])).status_code, 404)
        stranger = User.objects.create_user("09120000083")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("maps:index", args=[self.db.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("maps:quick", args=[self.db.pk]), {"t": "public.schools"})
                         .status_code, 404)
        self.assertEqual(self.client.get(f"/dashboard/{self.db.pk}/maps/preview/public/schools/{T}.mvt").status_code,
                         404)
        self.client.force_login(self.user)
        self.client.post(reverse("maps:delete", args=[self.db.pk, m.pk]))
        self.assertFalse(WebMap.objects.exists())
