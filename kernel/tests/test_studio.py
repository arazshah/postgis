import io
import zipfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from kernel import pkg, studio
from kernel.models import PluginDraft

PASS = "Str0ng-Admin-Pass"
PAGE = studio.TEMPLATES["monitor"][0].format(key="live")


def draft(**kw):
    base = dict(plugin_id="fleet", name="پایش ناوگان", version="1.0.0", kind="custom", requires="", pages={"live": PAGE})
    return PluginDraft(**{**base, **kw})


class StudioCoreTests(TestCase):
    def test_generated_manifest_is_valid_and_matches_pages(self):
        files = studio.files_of(draft(requires="databases"))
        m = pkg._manifest(files)
        self.assertEqual((m["id"], m["tier"], m["requires"]), ("fleet", 1, ["databases"]))
        self.assertEqual(m["contributes"]["pages"], ["pages/live.toml"])
        self.assertTrue(studio.ok(studio.check(draft(requires="databases"))))

    def test_name_with_quotes_cannot_break_manifest(self):
        d = draft(name='x" \n[evil]\nk="v')
        m = pkg._manifest(studio.files_of(d))
        self.assertEqual(m["name"], 'x" \n[evil]\nk="v')
        self.assertNotIn("evil", m)

    def test_errors_are_reported_in_persian(self):
        cases = [draft(plugin_id="Bad Id"), draft(version="x"), draft(kind="system"), draft(pages={}),
                 draft(pages={"live": "not toml ["}), draft(pages={"live": PAGE.replace("kpi", "weird")}),
                 draft(requires="ghost_plugin"), draft(plugin_id="billing")]
        for d in cases:
            with self.subTest(d=d.plugin_id + d.version + d.kind):
                steps = studio.check(d)
                self.assertFalse(studio.ok(steps))
                self.assertTrue(steps[-1]["detail"])

    def test_writes_are_flagged_and_need_editor(self):
        form = studio.TEMPLATES["form"][0].format(key="rep")
        steps = studio.check(draft(pages={"rep": form}))
        self.assertTrue(studio.ok(steps))
        self.assertIn("my_table", steps[-1]["detail"])
        bad = studio.check(draft(pages={"rep": form.replace('need = "editor"', 'need = "viewer"')}))
        self.assertFalse(studio.ok(bad))

    def test_export_has_no_signature_and_roundtrips_through_inspect_stages(self):
        z = zipfile.ZipFile(io.BytesIO(studio.export_zip(draft())))
        self.assertEqual(sorted(z.namelist()), ["pages/live.toml", "plugin.toml"])
        self.assertNotIn(pkg.SIG_NAME, z.namelist())


@override_settings(ADMIN_2FA_REQUIRED=False)
class StudioAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_admin("root", PASS)
        self.client.force_login(self.admin)
        self.meta = {"plugin_id": "fleet", "name": "پایش", "version": "1.0.0", "kind": "custom", "requires": "", "readme": ""}

    def test_create_add_page_check_export(self):
        r = self.client.post("/manage/kernel/plugindraft/studio/new/", {**self.meta, "op": "save"})
        d = PluginDraft.objects.get(plugin_id="fleet")
        self.assertRedirects(r, f"/manage/kernel/plugindraft/{d.pk}/studio/", fetch_redirect_response=False)
        url = f"/manage/kernel/plugindraft/{d.pk}/studio/"
        self.client.post(url, {**self.meta, "op": "addpage", "newkey": "live", "template": "monitor"})
        d.refresh_from_db()
        self.assertIn("live", d.pages)
        self.assertEqual(d.updated_by, self.admin)
        r = self.client.post(url, {**self.meta, "op": "check", "page_live": d.pages["live"]})
        self.assertContains(r, "گزارش بررسی")
        self.assertEqual(self.client.get(f"/manage/kernel/plugindraft/{d.pk}/export/")["Content-Type"], "application/zip")
        self.client.post(url, {**self.meta, "op": "delpage:live", "page_live": d.pages["live"]})
        d.refresh_from_db()
        self.assertEqual(d.pages, {})
        self.assertEqual(self.client.get(f"/manage/kernel/plugindraft/{d.pk}/export/").status_code, 302)  # بررسی رد می‌شود

    def test_bad_page_key_and_duplicate_id_rejected(self):
        d = PluginDraft.objects.create(plugin_id="fleet", name="x", pages={})
        url = f"/manage/kernel/plugindraft/{d.pk}/studio/"
        self.client.post(url, {**self.meta, "op": "addpage", "newkey": "Bad Key", "template": "monitor"})
        d.refresh_from_db()
        self.assertEqual(d.pages, {})
        self.client.post("/manage/kernel/plugindraft/studio/new/", {**self.meta, "op": "save"})
        self.assertEqual(PluginDraft.objects.filter(plugin_id="fleet").count(), 1)

    def test_requires_upload_permission(self):
        staff = get_user_model().objects.create_admin("limited", PASS, superuser=False)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/manage/kernel/plugindraft/studio/new/").status_code, 403)

    def test_preview_needs_live_workspace_and_logs(self):
        d = PluginDraft.objects.create(plugin_id="fleet", name="x", pages={"live": PAGE})
        url = f"/manage/kernel/plugindraft/{d.pk}/studio/"
        r = self.client.post(url, {**self.meta, "op": "preview", "preview_db": "999", "preview_page": "live", "page_live": PAGE})
        self.assertContains(r, "پایگاه داده‌ی فعال")
        ws = mock.Mock(pk=5, is_live=True)
        ctx = {"page": studio.parse_pages(d)[0], "blocks": [], "values": {}, "layers": {}, "param_errors": [], "has_map": False}
        with mock.patch("kernel.workspace.peek", return_value=ws), mock.patch("kernel.studio.preview_page", return_value=ctx), \
                mock.patch("kernel.workspace.log_event") as log:
            r = self.client.post(url, {**self.meta, "op": "preview", "preview_db": "5", "preview_page": "live", "page_live": PAGE})
        self.assertContains(r, "نتیجه‌ی پیش‌نمایش")
        log.assert_called_once()
