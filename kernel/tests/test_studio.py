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


# ---------------------------------------------------------------------- سطح ۲ در استودیو
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import override_settings as _override  # noqa: E402

BLOCK = studio.HANDLER_TEMPLATES["block"][0]
IMPORTER = studio.HANDLER_TEMPLATES["importer"][0]
EXPORTER = studio.HANDLER_TEMPLATES["exporter"][0]
ALERT = studio.HANDLER_TEMPLATES["alert"][0]
IO_PAGE = PAGE.replace('need = "viewer"', 'need = "editor"') + (
    '\n[[imports]]\nkey = "gps"\ntitle = "ورود"\nhandler = "parse"\nextensions = [".csv"]\n'
    '\n[[exports]]\nkey = "rep"\ntitle = "خروجی"\nhandler = "report"\nformat = "csv"\n')


def draft2(**kw):
    base = dict(plugin_id="fleet", name="پایش", version="1.0.0", kind="custom", requires="",
                pages={"live": IO_PAGE}, code={"parse": IMPORTER, "report": EXPORTER}, alerts={"parse": 15})
    return PluginDraft(**{**base, **kw})


class StudioTier2CoreTests(TestCase):
    def test_manifest_becomes_tier2_with_handlers_and_alerts(self):
        m = pkg._manifest(studio.files_of(draft2()))
        self.assertEqual((m["tier"], m["contributes"]["handlers"]), (2, ["parse", "report"]))
        self.assertEqual(m["contributes"]["alerts"], [{"handler": "parse", "every_minutes": 15}])
        self.assertTrue(studio.ok(studio.check(draft2())))
        self.assertEqual(pkg._manifest(studio.files_of(draft()))["tier"], 1)  # بدون کد همان سطح ۱

    def test_every_template_passes_the_real_check(self):
        for name, (src, _label) in studio.HANDLER_TEMPLATES.items():
            with self.subTest(template=name):
                d = draft2(code={"parse": src, "report": EXPORTER}, pages={"live": IO_PAGE})
                steps = studio.check(d)
                self.assertTrue(studio.ok(steps), steps)

    def test_dangerous_code_and_bad_alert_are_reported(self):
        steps = studio.check(draft2(code={"parse": "import os\ndef handle(c, p): return 1", "report": EXPORTER}))
        bad = next(s for s in steps if not s["ok"])
        self.assertIn("code/parse.py:", bad["detail"])
        steps = studio.check(draft2(alerts={"parse": 1}))
        self.assertIn("every_minutes", next(s for s in steps if not s["ok"])["detail"])
        steps = studio.check(draft2(pages={"live": IO_PAGE.replace('handler = "parse"', 'handler = "ghost"')}))
        self.assertIn("handler «ghost»", next(s for s in steps if not s["ok"])["detail"])

    def test_export_zip_contains_code_and_no_signature(self):
        names = zipfile.ZipFile(io.BytesIO(studio.export_zip(draft2()))).namelist()
        self.assertEqual(sorted(names), ["code/parse.py", "code/report.py", "pages/live.toml", "plugin.toml"])

    def test_roles_detect_import_export_block(self):
        d = draft2(pages={"live": IO_PAGE + '\n[[blocks]]\nkind = "table"\nhandler = "calc"\n'}, code={"parse": IMPORTER, "report": EXPORTER, "calc": BLOCK})
        self.assertEqual({k: v[0] for k, v in studio.roles(d).items()}, {"parse": "import", "report": "export", "calc": "block"})


class StudioTrialTests(TestCase):
    def test_exporter_trial_validates_like_production(self):
        with mock.patch("kernel.pagekit.read_select", lambda ws, q, a=None: {"columns": ["n"], "rows": [[7]]}):
            out = studio.trial(draft2(), "report", {}, ws=mock.Mock(pk=1))
        self.assertTrue(out["ok"], out)
        self.assertIn("خروجی معتبر", out["verdict"][0])
        self.assertIn("report.csv", out["verdict"][0])

    def test_importer_trial_uses_uploaded_file_and_nothing_is_written(self):
        with mock.patch("kernel.pluginio.create_table") as create:
            out = studio.trial(draft2(), "parse", {}, b"a,1.5\nb,2\n")
        self.assertTrue(out["ok"], out)
        self.assertIn("2 ردیف", out["verdict"][0])
        create.assert_not_called()

    def test_bad_import_shape_and_missing_file_are_errors(self):
        d = draft2(code={"parse": "def handle(c, p):\n    return {'columns': [{'name': 'a', 'type': 'money'}], 'rows': []}", "report": EXPORTER})
        out = studio.trial(d, "parse", {}, b"x")
        self.assertFalse(out["ok"])
        self.assertIn("معتبر نیست", out["error"])
        self.assertIn("فایلی ندارد", studio.trial(draft2(), "parse", {})["error"])

    def test_without_database_sql_is_unavailable(self):
        out = studio.trial(draft2(), "report", {})
        self.assertIn("دسترسی ندارد", out["error"])

    def test_static_check_blocks_execution_and_off_mode_never_runs(self):
        bad = draft2(code={"parse": "import os\ndef handle(c, p): return 1", "report": EXPORTER})
        with mock.patch("kernel.runner.client.run_files") as run:
            out = studio.trial(bad, "parse", {})
            self.assertIn("بررسی ایستا", out["error"])
            run.assert_not_called()
        with _override(PLUGIN_RUNNER_MODE="off"):
            self.assertIn("فعال نیست", studio.trial(draft2(), "report", {})["error"])
        self.assertIn("در پیش‌نویس نیست", studio.trial(draft2(), "nope", {})["error"])

    def test_handler_failure_is_reported_and_logs_are_captured(self):
        d = draft2(code={"parse": "def handle(c, p):\n    c.log('hello')\n    return 1/0", "report": EXPORTER})
        out = studio.trial(d, "parse", {}, b"x")
        self.assertIn("ZeroDivisionError", out["error"])
        d = draft2(code={"parse": "def handle(c, p):\n    c.log('hello')\n    return {'columns': [{'name': 'a', 'type': 'text'}], 'rows': [['x']]}", "report": EXPORTER})
        self.assertEqual(studio.trial(d, "parse", {}, b"x")["logs"], ["hello"])


@_override(ADMIN_2FA_REQUIRED=False)
class StudioTier2AdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_admin("root", PASS)
        self.client.force_login(self.admin)
        self.d = PluginDraft.objects.create(plugin_id="fleet", name="پایش", pages={"live": IO_PAGE}, code={"parse": IMPORTER, "report": EXPORTER})
        self.url = f"/manage/kernel/plugindraft/{self.d.pk}/studio/"
        self.meta = {"plugin_id": "fleet", "name": "پایش", "version": "1.0.0", "kind": "custom", "requires": "", "readme": ""}

    def post(self, op, **extra):
        data = {**self.meta, "op": op, "page_live": IO_PAGE, "code_parse": IMPORTER, "code_report": EXPORTER, **extra}
        return self.client.post(self.url, data)

    def test_add_and_delete_handler_and_alert_minutes_saved(self):
        self.post("addhandler", newhandler="calc", htemplate="block")
        self.d.refresh_from_db()
        self.assertEqual(sorted(self.d.code), ["calc", "parse", "report"])
        self.client.post(self.url, {**self.meta, "op": "save", "page_live": IO_PAGE, "code_parse": IMPORTER, "code_report": EXPORTER,
                                    "code_calc": BLOCK, "alert_calc": "30"})
        self.d.refresh_from_db()
        self.assertEqual(self.d.alerts, {"calc": 30})
        self.client.post(self.url, {**self.meta, "op": "delhandler:calc", "page_live": IO_PAGE, "code_parse": IMPORTER, "code_report": EXPORTER,
                                    "code_calc": BLOCK, "alert_calc": "30"})
        self.d.refresh_from_db()
        self.assertEqual((sorted(self.d.code), self.d.alerts), (["parse", "report"], {}))

    def test_bad_handler_name_rejected(self):
        self.post("addhandler", newhandler="Bad Name", htemplate="block")
        self.d.refresh_from_db()
        self.assertEqual(sorted(self.d.code), ["parse", "report"])

    def test_trial_runs_through_client_and_shows_verdict(self):
        r = self.post("trial:parse", trial_params="{}", trial_file=SimpleUploadedFile("a.csv", b"a,1\nb,2\n"))
        self.assertContains(r, "ورود معتبر است")

    def test_trial_input_validation_and_stepup(self):
        self.assertContains(self.post("trial:parse", trial_params="[1]"), "شیء JSON")
        self.assertContains(self.post("trial:parse", trial_params="{}", trial_db="999"), "پایگاه داده‌ی فعال")
        with _override(ADMIN_2FA_REQUIRED=True):
            r = self.post("trial:parse", trial_params="{}")
            self.assertEqual(r.status_code, 302)  # بدون تأیید تازه اجرا نمی‌شود

    def test_trial_with_database_logs_activity(self):
        ws = mock.Mock(pk=5, is_live=True)
        with mock.patch("kernel.workspace.peek", return_value=ws), mock.patch("kernel.workspace.log_event") as log, \
                mock.patch("kernel.pagekit.read_select", return_value={"columns": ["n"], "rows": [[3]]}):
            r = self.post("trial:report", trial_params="{}", trial_db="5")
        self.assertContains(r, "خروجی معتبر است")
        log.assert_called_once()

    def test_page_renders_code_sections(self):
        r = self.client.get(self.url)
        self.assertContains(r, "code_parse")
        self.assertContains(r, "اجرای آزمایشی")
        self.assertContains(r, "ورود فایل")
