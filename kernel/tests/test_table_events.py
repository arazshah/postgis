"""رویدادهای جدول و کارت مصرف: پلاگین‌های نقشه، انتشار و REST به حذف، تغییر نام و پرسش کاربرد جدول پاسخ می‌دهند."""
from django.http import HttpRequest

from databases import services
from databases.tests.test_services import BaseCase
from kernel import events
from maps.models import MapLayer, WebMap
from publish.models import Layer, Service
from restapi.models import ApiTable


class TableEventsTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "tevdb", "Abcdefgh123", ["postgis"])
        svc = Service.objects.create(database=self.db)
        Layer.objects.create(service=svc, table="roads", geom_column="geom")
        Layer.objects.create(service=svc, table="other", geom_column="geom")
        ApiTable.objects.create(service=svc, table="roads")
        wm = WebMap.objects.create(database=self.db, title="m")
        MapLayer.objects.create(webmap=wm, table="roads", geom_column="geom")

    def payload(self, **kw):
        return dict(ws=self.db, schema="public", table="roads", **kw)

    def test_usage_is_merged_from_every_plugin(self):
        got = {}
        for part in events.collect(events.TABLE_USAGE, **self.payload()):
            got.update(part)
        self.assertEqual(got, {"maps": 1, "published": 1, "api": 1})

    def test_rename_follows_the_table_in_all_three_plugins(self):
        events.emit(events.TABLE_RENAMED, **self.payload(new="streets"))
        self.assertEqual(Layer.objects.filter(table="streets").count(), 1)
        self.assertEqual(ApiTable.objects.get().table, "streets")
        self.assertEqual(MapLayer.objects.get().table, "streets")
        self.assertEqual(Layer.objects.filter(table="other").count(), 1)

    def test_drop_removes_references_and_reports_only_unpublished_count(self):
        counts = events.collect(events.TABLE_DROPPED, **self.payload())
        self.assertEqual(sum(n for n in counts if n is not True), 2)  # یک لایه‌ی منتشرشده + یک API؛ لایه‌ی نقشه حساب نمی‌شود
        self.assertFalse(MapLayer.objects.exists() or ApiTable.objects.exists())
        self.assertEqual(list(Layer.objects.values_list("table", flat=True)), ["other"])

    def test_map_targets_only_for_editors(self):
        def merged(editable):
            out = {}
            for part in events.collect(events.TABLE_MAP_TARGETS, ws=self.db, editable=editable):
                out.update(part)
            return out

        self.assertEqual([m.title for m in merged(True)["maps"]], ["m"])
        self.assertEqual(merged(False)["maps"], [])

    def test_publish_adds_a_usage_card_with_14_days_and_the_plan_cap(self):
        cards = [c for c in events.collect(events.USAGE_CARDS, ws=self.db, request=HttpRequest()) if isinstance(c, dict)]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["template"], "publish/_usage_requests.html")
        self.assertEqual(len(cards[0]["ctx"]["requests"]), 14)
        self.assertEqual(cards[0]["ctx"]["chart"]["w"], 600)
