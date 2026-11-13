"""نماهای ویرایش/حذف ردیف `[[records]]`: دسترسی، فقط POST برای حذف، پیام‌ها و ثبت در گزارش فعالیت (بدون PostgreSQL مشتری)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, pagekit
from kernel.plugins import registry
from kernel.tests.test_geometry import PAGE
from kernel.tests.test_pagekit import STORAGES


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class RecordViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        self.page = pagekit.parse_page("demo", PAGE)
        p = mock.patch("kernel.pagekit.get", lambda a, b: self.page if (a, b) == ("demo", "farms") else None)
        p.start()
        self.addCleanup(p.stop)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.args = [self.db.pk, "demo", "farms", "farms", 7]

    def test_edit_form_is_prefilled_and_saves(self):
        cur = {"name": "الف", "crop": "corn", "area": '{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}'}
        with mock.patch("kernel.pagekit.fetch_record", return_value=cur), mock.patch("kernel.pagekit.update_record") as up, \
                mock.patch("kernel.workspace.log_event") as log:
            r = self.client.get(reverse("kernel:record_edit", args=self.args))
            self.assertContains(r, 'value="الف"')
            self.assertContains(r, "data-pk-draw")
            self.assertContains(r, "&quot;Polygon&quot;")
            r = self.client.post(reverse("kernel:record_edit", args=self.args), {"f_name": "ب", "f_crop": "wheat", "f_area": ""})
        self.assertEqual(r.status_code, 302)
        rc, rid, values = up.call_args.args[1:]
        self.assertEqual((rid, values["name"], values["crop"], values["area"]), (7, "ب", "wheat", None))
        self.assertTrue(any(c.args[0] == "plugin_record" for c in log.call_args_list))

    def test_invalid_input_shows_error_and_keeps_typed_values(self):
        with mock.patch("kernel.pagekit.update_record") as up:
            r = self.client.post(reverse("kernel:record_edit", args=self.args), {"f_name": "", "f_crop": "wheat"})
        up.assert_not_called()
        self.assertContains(r, "الزامی")
        self.assertContains(r, "wheat")

    def test_missing_row_404_and_spec_error_message(self):
        with mock.patch("kernel.pagekit.fetch_record", return_value=None):
            self.assertEqual(self.client.get(reverse("kernel:record_edit", args=self.args)).status_code, 404)
        with mock.patch("kernel.pagekit.update_record", side_effect=pagekit.SpecError("شکل معتبر نیست")):
            r = self.client.post(reverse("kernel:record_edit", args=self.args), {"f_name": "x"})
        self.assertContains(r, "شکل معتبر نیست")

    def test_delete_is_post_only_and_logged(self):
        url = reverse("kernel:record_delete", args=self.args)
        self.assertEqual(self.client.get(url).status_code, 405)
        with mock.patch("kernel.pagekit.delete_record") as de, mock.patch("kernel.workspace.log_event") as log:
            self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(de.call_args.args[2], 7)
        self.assertTrue(any(c.args[0] == "plugin_record" for c in log.call_args_list))

    def test_can_delete_false_is_404(self):
        page = pagekit.parse_page("demo", {**PAGE, "records": [{**PAGE["records"][0], "can_delete": False}]})
        with mock.patch("kernel.pagekit.get", lambda a, b: page), mock.patch("kernel.pagekit.delete_record") as de:
            self.assertEqual(self.client.post(reverse("kernel:record_delete", args=self.args)).status_code, 404)
        de.assert_not_called()

    def test_other_users_workspace_denied(self):
        other = get_user_model().objects.create_user(username="x9", phone="09120000999", password="x")
        self.client.force_login(other)
        with mock.patch("kernel.pagekit.delete_record") as de, mock.patch("kernel.pagekit.update_record") as up:
            for name in ("record_edit", "record_delete"):
                r = self.client.post(reverse(f"kernel:{name}", args=self.args), {"f_name": "x"})
                self.assertIn(r.status_code, (403, 404))
        de.assert_not_called()
        up.assert_not_called()

    def test_unknown_record_404(self):
        args = [self.db.pk, "demo", "farms", "nope", 7]
        self.assertEqual(self.client.post(reverse("kernel:record_delete", args=args)).status_code, 404)

    def test_page_lists_rows_with_menu(self):
        heads, rows = ["id", "name", "crop"], [[7, "الف", "ذرت"]]
        with mock.patch("kernel.pagekit.fetch_records", return_value=(heads, rows)), \
                mock.patch("kernel.pages_view.pagekit.render_block", return_value={"kind": "text", "paras": ["x"], "width": "full"}):
            r = self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "farms"]))
        self.assertContains(r, 'id="record-farms"')
        self.assertContains(r, "الف")
        self.assertContains(r, reverse("kernel:record_edit", args=self.args))
        self.assertContains(r, reverse("kernel:record_delete", args=self.args))
        self.assertContains(r, "data-confirm=")

    def test_list_uses_persian_labels_and_choice_names(self):
        heads, rows = ["id", "name", "crop"], [[7, "الف", "wheat"]]
        with mock.patch("kernel.pagekit.fetch_records", return_value=(heads, rows)), \
                mock.patch("kernel.pages_view.pagekit.render_block", return_value={"kind": "text", "paras": ["x"], "width": "full"}):
            r = self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "farms"]))
        self.assertContains(r, "<th>نام</th>")  # برچسب فارسی، نه نام ستون
        self.assertContains(r, "<th>محصول</th>")
        self.assertContains(r, "گندم")  # مقدار گزینه با برچسب
        self.assertNotContains(r, ">wheat<")
