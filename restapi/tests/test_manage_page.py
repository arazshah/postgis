"""صفحه‌ی مدیریت REST API: زبانه‌ها، فهرست جدول‌ها (فعال‌ها اول)، مودال دسترسی و نمونه کد (بدون PostGIS)."""
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from databases import services
from databases.explorer import Explorer, TableRef
from databases.tests.test_services import BaseCase
from databases.tests.test_workspace_nav import STORAGES
from publish.models import Service
from restapi.models import ApiTable, FieldForm

META = {"columns": [{"name": "id"}, {"name": "name"}, {"name": "geom"}], "pk": "id", "geom": None}


@override_settings(STORAGES=STORAGES)
class RestManagePageTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "rpage", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("restapi:manage", args=[self.db.pk])
        geo = [{"column": "geom", "type": "POINT", "srid": 4326, "geography": False}]
        tables = [TableRef("public", "alpha", 1, "r", 10, 0, []), TableRef("public", "trees", 2, "r", 5, 0, geo),
                  TableRef("gis", "zeta", 3, "r", 7, 0, geo), TableRef("public", "v", 4, "v", 0, 0, [])]
        svc = Service.objects.create(database=self.db)
        self.trees = ApiTable.objects.create(service=svc, table="trees", public_read=True, can_insert=True)
        FieldForm.objects.create(api_table=self.trees, title="ثبت درخت", fields=["name"], submissions=3)
        for target, value in (("tables", tables), ("single_pk_tables", {("public", "trees")})):
            p = mock.patch.object(Explorer, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("restapi.engine.describe", return_value=META)
        p.start()
        self.addCleanup(p.stop)

    def test_tabs_rows_and_counters(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'data-hash-tabs')
        for tab in ("p-tables", "p-forms", "p-code"):
            self.assertContains(r, f'id="{tab}"')
        self.assertEqual(r.context["n_active"], 1)
        names = [x["t"].name for x in r.context["rows"]]
        self.assertEqual(names[0], "trees")                     # فعال‌ها اول
        self.assertNotIn("v", names)                            # نما در REST نیست
        self.assertContains(r, "خواندن عمومی")
        self.assertContains(r, 'data-lf-chip="on"')

    def test_pk_flag_and_access_dialog(self):
        r = self.client.get(self.url)
        rows = {x["t"].name: x for x in r.context["rows"]}
        self.assertTrue(rows["trees"]["has_pk"])
        self.assertFalse(rows["alpha"]["has_pk"])
        self.assertContains(r, 'id="rest-dlg"')
        self.assertContains(r, 'name="preset" value="collect"')
        self.assertContains(r, "data-rest-access")

    def test_sample_chip_and_forms_tab(self):
        r = self.client.get(self.url)
        self.assertContains(r, f'data-rest-chip="{self.trees.pk}"')
        self.assertContains(r, "data-rest-path")
        self.assertContains(r, "ثبت درخت")
        self.assertContains(r, f'data-rest-form="{self.trees.pk}"')   # ساخت فرم از منوی ردیف

    def test_save_table_still_works(self):
        self.client.post(self.url, {"action": "save_table", "table": "public.trees", "enabled": "on"})
        t = ApiTable.objects.get(table="trees")
        self.assertFalse(t.public_read)
        self.client.post(self.url, {"action": "save_table", "table": "public.trees"})
        self.assertFalse(ApiTable.objects.filter(table="trees").exists())

    def test_no_active_tables_shows_empty_code_tab(self):
        ApiTable.objects.all().delete()
        r = self.client.get(self.url)
        self.assertContains(r, "اول یک جدول را فعال کنید")
