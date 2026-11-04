"""صفحه‌ی «نقشه و API»: زبانه‌ها، فهرست لایه‌ها، انتشار گروهی و داده‌ی مودال‌ها (بدون PostGIS)."""
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from databases import services
from databases.explorer import Explorer, TableRef
from databases.tests.test_services import BaseCase
from databases.tests.test_workspace_nav import STORAGES
from publish.models import ApiKey, Layer, Service

META = {"columns": [("id", "int4"), ("name", "text"), ("geom", "geometry")], "pk": "id"}


def _geo(kind="POINT", srid=4326):
    return [{"column": "geom", "type": kind, "srid": srid, "geography": False}]


@override_settings(STORAGES=STORAGES)
class PublishManagePageTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "ppage", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("publish:manage", args=[self.db.pk])
        self.tables = [TableRef("public", n, i, "r", 100 * i, 0, _geo()) for i, n in enumerate("abcde")]
        self.tables.append(TableRef("public", "nosrid", 9, "r", 1, 0, _geo(srid=0)))
        self.tables.append(TableRef("public", "plain", 10, "r", 1, 0, []))
        svc = Service.objects.create(database=self.db)
        self.layer = Layer.objects.create(service=svc, table="c", geom_column="geom", is_public=True)
        patches = [mock.patch.object(Explorer, "tables", return_value=self.tables),
                   mock.patch.object(Explorer, "find", side_effect=lambda s, n: next(t for t in self.tables if t.name == n)),
                   mock.patch("publish.engine.describe", return_value=META),
                   mock.patch("publish.engine.extent", return_value=[44.0, 25.0, 63.0, 40.0])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_rows_published_first_and_tabs(self):
        r = self.client.get(self.url)
        names = [x["t"].name for x in r.context["rows"]]
        self.assertEqual(names[0], "c")                              # منتشرشده اول
        self.assertNotIn("plain", names)                              # غیرمکانی در انتشار نیست
        for tab in ("p-layers", "p-connect", "p-keys"):
            self.assertContains(r, f'id="{tab}"')
        self.assertContains(r, 'data-lf-chip="unpub"')

    def test_layer_data_for_shared_dialogs(self):
        r = self.client.get(self.url)
        data = r.context["layer_data"][self.layer.pk]
        self.assertEqual(data["table"], "c")
        self.assertEqual([c["name"] for c in data["columns"]], ["id", "name"])   # ستون هندسه نیست
        self.assertEqual(data["save"], reverse("publish:update_layer", args=[self.db.pk, self.layer.pk]))
        self.assertContains(r, 'id="pl-data"')
        self.assertContains(r, 'id="urls-dlg"')

    def test_nosrid_row_links_to_health_and_has_no_checkbox(self):
        r = self.client.get(self.url)
        html = r.content.decode()
        row = html[html.index('data-sort-name="nosrid"'):]
        row = row[:row.index("</tr>")]
        self.assertNotIn("data-lf-pick", row)
        self.assertIn(reverse("databases:explore_health", args=[self.db.pk]), row)

    def test_bulk_publish(self):
        self.db.plan.publish_layers = 10
        self.db.plan.save()
        r = self.client.post(reverse("publish:publish_bulk", args=[self.db.pk]),
                             {"tables": ["public.a", "public.b", "public.c"], "public": "on"})
        self.assertRedirects(r, self.url)
        self.assertEqual(set(Layer.objects.values_list("table", flat=True)), {"a", "b", "c"})
        self.assertTrue(Layer.objects.get(table="a").is_public)
        self.assertFalse(Layer.objects.get(table="c") is None)       # قبلاً منتشر بود و دست نخورد

    def test_bulk_publish_respects_plan_limit(self):
        self.db.plan.publish_layers = 2          # یک لایه از قبل هست
        self.db.plan.save()
        r = self.client.post(reverse("publish:publish_bulk", args=[self.db.pk]),
                             {"tables": ["public.a", "public.b", "public.d"]}, follow=True)
        self.assertEqual(Layer.objects.count(), 2)                    # فقط یکی جا داشت
        self.assertTrue(any("حداکثر" in str(m) for m in r.context["messages"]))

    def test_bulk_publish_rejects_empty_and_bad_srid(self):
        self.client.post(reverse("publish:publish_bulk", args=[self.db.pk]), {})
        self.client.post(reverse("publish:publish_bulk", args=[self.db.pk]), {"tables": ["public.nosrid"]})
        self.assertEqual(Layer.objects.count(), 1)

    def test_keys_tab_lists_keys(self):
        ApiKey.objects.create(database=self.db, name="سایت شهرداری", prefix="gp_ab", key_hash="h1")
        r = self.client.get(self.url)
        self.assertContains(r, "سایت شهرداری")
        self.assertContains(r, 'id="key-new"')

