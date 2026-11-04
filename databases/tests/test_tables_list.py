"""فهرست جدول‌ها: صفحه‌ی خلاصه (جست‌وجو/فیلتر/آیکون هندسه)، فهرست بازشو و نقطه‌ی Ctrl+K."""
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from core.templatetags.fa import farows
from databases import services
from databases.explorer import Explorer, TableRef
from databases.tests.test_services import BaseCase
from databases.tests.test_workspace_nav import STORAGES


def _geo(kind, srid=4326):
    return [{"column": "geom", "type": kind, "srid": srid, "geography": False}]


def _tables():
    return [
        TableRef("public", "roads", 1, "r", 775_000, 650_000_000, _geo("MULTILINESTRING")),
        TableRef("public", "schools", 2, "r", 900, 1_000_000, _geo("POINT")),
        TableRef("public", "zones", 3, "r", 22, 500_000, _geo("MULTIPOLYGON", 32639)),
        TableRef("gis", "notes", 4, "r", 10, 8192, []),
        TableRef("gis", "v_active", 5, "v", 0, 0, []),
    ]


class TableRefTests(SimpleTestCase):
    def test_geo_kind(self):
        kinds = {t.name: t.geo_kind for t in _tables()}
        self.assertEqual(kinds, {"roads": "line", "schools": "point", "zones": "polygon", "notes": "", "v_active": ""})
        self.assertEqual(_tables()[2].srid, 32639)
        self.assertIsNone(_tables()[3].srid)

    def test_farows(self):
        self.assertEqual(farows(900), "۹۰۰")
        self.assertEqual(farows(775_000), "۷۷۵ هزار")
        self.assertEqual(farows(1_300_000), "۱٫۳ میلیون")
        self.assertEqual(farows(None), "—")


@override_settings(STORAGES=STORAGES)
class TablesListViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "tlist", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        p = mock.patch.object(Explorer, "tables", return_value=_tables())
        p.start()
        self.addCleanup(p.stop)

    def test_summary_has_toolbar_rows_and_menus(self):
        r = self.client.get(reverse("databases:explore", args=[self.db.pk]))
        self.assertContains(r, "data-tl-q")                        # جست‌وجو
        self.assertContains(r, 'data-f="geo"')                     # چیپ مکانی
        self.assertContains(r, 'data-f="view"')                    # چیپ نما (یک view دارد)
        self.assertContains(r, 'data-f="s:gis"')                   # چند schema → چیپ schema
        self.assertContains(r, 'data-name="roads"')
        self.assertContains(r, "۷۷۵ هزار")
        self.assertContains(r, "?tab=columns")                     # منوی ⋯ ردیف
        self.assertContains(r, "5 جدول".replace("5", "۵"))         # خط خلاصه
        self.assertContains(r, "data-tl-sel")                      # نوار انتخاب (چند جدول مکانی)

    def test_popover_list_shows_geometry_and_rows(self):
        with mock.patch.object(Explorer, "columns", return_value=[]), mock.patch.object(Explorer, "indexes", return_value=[]), \
                mock.patch("databases.views._edit_config", return_value=None), \
                mock.patch("databases.views._structure_config", return_value=None):
            r = self.client.get(reverse("databases:explore_table", args=[self.db.pk, "public", "roads"]) + "?tab=columns")
        self.assertContains(r, 'data-geo="line"')
        self.assertContains(r, "data-ex-recent")

    def test_tables_json_for_palette(self):
        r = self.client.get(reverse("databases:tables_json", args=[self.db.pk]))
        items = {i["t"]: i for i in r.json()["items"]}
        self.assertIn("roads", items)
        self.assertIn("gis.notes", items)
        self.assertEqual(items["roads"]["u"], reverse("databases:explore_table", args=[self.db.pk, "public", "roads"]))
        self.assertEqual(items["roads"]["g"], "جدول مکانی")

    def test_tables_json_needs_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("databases:tables_json", args=[self.db.pk])).status_code, 302)
