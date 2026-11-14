"""صفحه‌ی سلامت داده: گروه‌بندی بر اساس مشکل، شمارنده‌ها، اصلاح گروهی و مودال SRID."""
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from databases import services
from databases.explorer import Explorer, ExplorerError, TableRef
from databases.tests.test_services import BaseCase
from databases.tests.test_workspace_nav import STORAGES


def _issues():
    return [
        {"schema": "public", "table": "a", "fix": "add_pk", "level": "warning", "text": "کلید اصلی ندارد"},
        {"schema": "public", "table": "b", "fix": "add_pk", "level": "warning", "text": "کلید اصلی ندارد"},
        {"schema": "gis", "table": "c", "column": "geom", "fix": "add_index", "level": "warning", "text": "نمایه ندارد"},
        {"schema": "public", "table": "d", "column": "geom", "fix": "set_srid", "level": "error", "text": "SRID 0"},
    ]


def _tables():
    return [TableRef("public", n, i, "r", 1, 0, []) for i, n in enumerate("abcdefg")]


@override_settings(STORAGES=STORAGES)
class HealthPageTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "hpage", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("databases:explore_health", args=[self.db.pk])
        for target, value in (("tables", _tables()), ("health", _issues())):
            p = mock.patch.object(Explorer, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_groups_counters_and_bulk_buttons(self):
        r = self.client.get(self.url)
        self.assertEqual((r.context["n_error"], r.context["n_warning"], r.context["n_info"]), (1, 3, 0))
        self.assertEqual(r.context["n_healthy"], 3)            # ۷ جدول، ۴ جدول مشکل‌دار
        self.assertEqual(r.context["n_auto"], 3)               # SRID خودکار نیست
        self.assertEqual([g["fix"] for g in r.context["problems"]], ["set_srid", "add_pk", "add_index"])  # خطا اول
        self.assertContains(r, 'name="kind" value="add_pk"')   # اصلاح گروهی فقط برای نوعی با بیش از یک مورد
        self.assertNotContains(r, 'name="kind" value="add_index"')
        self.assertNotContains(r, 'name="kind" value="set_srid"')
        self.assertContains(r, "data-srid-open")
        self.assertContains(r, 'id="srid-dlg"')
        self.assertContains(r, "gis.c")

    def test_viewer_has_no_fix_controls(self):
        from accounts.models import User
        from databases.models import Member

        owner = User.objects.create_user("09120000009")
        shared = services.create_database(owner, "hshare", "Abcdefgh123", ["postgis"])
        Member.objects.create(database=shared, phone=self.user.phone, user=self.user, role="viewer")
        r = self.client.get(reverse("databases:explore_health", args=[shared.pk]))
        self.assertNotContains(r, 'name="fix"')
        self.assertNotContains(r, 'id="srid-dlg"')

    def test_plugin_tables_card_and_rebuild(self):
        row = {"plugin": "mon", "table": "mon_points", "state": "missing", "lost": []}
        with mock.patch("kernel.tables.status", return_value=[row, {**row, "table": "ok_t", "state": "ok"}]):
            r = self.client.get(self.url)
        self.assertContains(r, "جدول پلاگین حذف شده است")
        self.assertContains(r, "mon_points")
        self.assertNotContains(r, "ok_t")
        with mock.patch("kernel.tables.rebuild", return_value=["mon_points"]) as m:
            r = self.client.post(self.url, {"fix": "plugin_tables"})
        m.assert_called_once_with(mock.ANY, None)
        self.assertRedirects(r, self.url)

    def test_group_fix_posts_to_explorer(self):
        with mock.patch.object(Explorer, "fix_group", return_value=(["a: ok", "b: ok"], [])) as m:
            r = self.client.post(self.url, {"fix": "group", "kind": "add_pk"})
        m.assert_called_once_with("add_pk")
        self.assertRedirects(r, self.url)

    def test_set_srid_accepts_other_select(self):
        with mock.patch.object(Explorer, "fix", return_value="ok") as m:
            self.client.post(self.url, {"fix": "set_srid", "schema": "public", "table": "d", "column": "geom",
                                        "srid": "", "srid_other": "23039"})
        self.assertEqual(m.call_args.args[-1], 23039)

    def test_fix_group_rejects_set_srid(self):
        with self.assertRaises(ExplorerError):
            Explorer(self.db).fix_group("set_srid")

    def test_all_healthy_empty_state(self):
        with mock.patch.object(Explorer, "health", return_value=[]):
            r = self.client.get(self.url)
        self.assertContains(r, "مشکلی پیدا نشد")
        self.assertNotContains(r, "data-lf-q")
