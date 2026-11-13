"""درون‌ریز پلاگین‌های قبلی (ADR-0010 مرحله‌ی ۹): راستی‌آزمایی بی‌اتلاف، بلوک خام، حفظ کلیدها، نقش handler و صفحه‌ی ورود."""
import copy
import tomllib

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from kernel import blueprint, entitlements, importer, pagekit, pkg, platform, samples, studio, wizard
from kernel.models import PluginDraft, PluginDraftRevision, PluginRelease
from kernel.tests.test_publish import cleanup_loaded

PID = "fleet"
TABLE = {"name": "fleet_pts", "columns": [
    {"name": "device", "type": "text", "required": True, "label": "دستگاه"}, {"name": "lat", "type": "double", "min": -90, "max": 90, "label": "عرض"},
    {"name": "lon", "type": "double", "min": -180, "max": 180, "label": "طول"}, {"name": "speed", "type": "double"},
    {"name": "at", "type": "timestamptz", "auto_now": True}]}
CASE = {"name": "عادی", "sql": [{"match": "select", "columns": ["v"], "rows": [[1.0], [3.0]]}], "expect": {"rows_count": 1}}
CODE = "def handle(ctx, params):\n    r = ctx.sql('select speed from fleet_pts')\n    return {'columns': ['میانگین'], 'rows': [[sum(x[0] for x in r['rows']) / len(r['rows'])]]}\n"


def designer_spec():
    s = {"intro": {"summary": "پایش"}, "tables": [copy.deepcopy(TABLE)], "pages": [], "code": {}, "access": {"mode": "public_free"}}
    s = blueprint.apply(s, PID, {"op": "code.new", "name": "avg_speed", "role": "block", "source": CODE, "tables": ["fleet_pts"], "cases": [CASE]})
    return blueprint.apply(s, PID, {"op": "page.add", "title": "پایش", "subtitle": "آخرین موقعیت", "refresh": 15, "need": "editor", "blocks": [
        {"kind": "kpi", "title": "تعداد", "table": "fleet_pts", "agg": "count", "since_col": "at", "since_minutes": 60, "unit": "ثبت"},
        {"kind": "bars", "title": "هر دستگاه", "table": "fleet_pts", "label": "device"},
        {"kind": "map", "title": "نقشه", "table": "fleet_pts", "lat": "lat", "lon": "lon", "latest_by": "device", "time_col": "at", "props": ["device"]},
        {"kind": "table", "title": "آخرین‌ها", "table": "fleet_pts", "columns": ["device", "speed"], "order_by": "at", "limit": 10},
        {"kind": "handler", "title": "میانگین", "handler": "avg_speed", "display": "table"},
        {"kind": "form", "title": "ثبت", "table": "fleet_pts", "fields": ["device", "lat", "lon"], "key": "manual", "submit": "ثبت دستی"},
        {"kind": "ingest", "title": "دریافت", "table": "fleet_pts", "fields": ["device", "lat", "lon", "speed"], "key": "gps", "max_rows": 50},
        {"kind": "records", "title": "ویرایش", "table": "fleet_pts", "key": "edit", "columns": ["device"]},
        {"kind": "report", "title": "گزارش", "key": "weekly", "blocks": [], "landscape": True}]})


def pages_of(spec, pid=PID):
    return {k: tomllib.loads(t) for k, t in wizard.compile_pages(pid, spec).items()}


def parsed(spec, pid=PID):
    return {k: pagekit.parse_page(pid, d) for k, d in pages_of(spec, pid).items()}


class SampleRoundTrip(SimpleTestCase):
    def test_samples_import_losslessly_without_raw_blocks(self):
        for pid, fn in ((samples.WEATHER_ID, samples.weather_page), (samples.ORCHARD_ID, samples.orchard_page)):
            d = fn()
            imp = importer.build(pid, pid, {d["key"]: d}, {}, {}, {})
            self.assertTrue(imp.report["lossless"], (pid, imp.report))
            self.assertEqual(imp.report["raw"], [], pid)
            self.assertEqual(parsed(imp.spec, pid)[d["key"]], pagekit.parse_page(pid, d))
            kinds = {b["kind"] for b in imp.spec["pages"][0]["blocks"]}
            self.assertTrue(kinds & {"source", "form", "records", "report", "ingest"}, kinds)

    def test_source_details_survive(self):
        d = samples.weather_page()
        orig = pagekit.parse_page(samples.WEATHER_ID, d).sources[0]
        new = parsed(importer.build(samples.WEATHER_ID, "w", {d["key"]: d}, {}, {}, {}).spec, samples.WEATHER_ID)[d["key"]].sources[0]
        self.assertEqual((new.key, new.mode, new.consts, new.optional, new.inputs), (orig.key, orig.mode, orig.consts, orig.optional, orig.inputs))


class DesignerRoundTrip(SimpleTestCase):
    def test_designer_made_plugin_imports_losslessly_and_keeps_keys(self):
        spec = designer_spec()
        files = {"plugin.toml": b"", **{f"pages/{k}.toml": t.encode() for k, t in wizard.compile_pages(PID, spec).items()}}
        pages = {k: tomllib.loads(t.decode()) for k, t in ((n[6:-5], b) for n, b in files.items() if n.startswith("pages/"))}
        imp = importer.build(PID, "ناوگان", pages, {"avg_speed": CODE}, {"avg_speed": spec["code"]["avg_speed"]["test"]}, {})
        self.assertTrue(imp.report["lossless"], imp.report)
        self.assertEqual(imp.report["raw"], [])
        self.assertEqual(parsed(imp.spec), parsed(spec))
        blocks = imp.spec["pages"][0]["blocks"]
        self.assertEqual({b["key"] for b in blocks if b.get("key")}, {"manual", "gps", "edit", "weekly"})
        self.assertEqual({b["kind"] for b in blocks}, {"sql", "handler", "form", "ingest", "records", "report"})
        self.assertEqual(imp.spec["code"]["avg_speed"]["role"], "block")
        self.assertTrue(imp.spec["code"]["avg_speed"]["cases"])
        report = next(b for b in blocks if b["kind"] == "report")
        self.assertEqual(len(report["blocks"]), 0)

    def test_hand_written_old_studio_template_with_layer_param(self):
        text = studio.TEMPLATES["monitor"][0].format(key="mon")
        d = tomllib.loads(text)
        imp = importer.build("hand", "دستی", {"mon": d}, {}, {}, {})
        self.assertTrue(imp.report["lossless"], imp.report)
        self.assertEqual([p["kind"] for p in imp.spec["pages"][0]["params"]], ["layer"])
        self.assertEqual(parsed(imp.spec, "hand")["mon"], pagekit.parse_page("hand", d))
        self.assertEqual({b["kind"] for b in imp.spec["pages"][0]["blocks"]}, {"sql"})


class RawFallback(SimpleTestCase):
    def test_form_on_external_table_becomes_raw_and_still_equal(self):
        d = tomllib.loads('''key = "pg"
title = "ثبت"
need = "editor"
[[blocks]]
kind = "text"
text = "سلام"
[[forms]]
key = "inc"
title = "حادثه"
table = "incidents"
[[forms.fields]]
name = "title"
kind = "text"
label = "عنوان"
''')
        imp = importer.build("ext", "خارجی", {"pg": d}, {}, {}, {})
        self.assertEqual([(r["part"], r["key"]) for r in imp.report["raw"]], [("forms", "inc")])
        self.assertEqual(parsed(imp.spec, "ext")["pg"], pagekit.parse_page("ext", d))
        raw = next(b for b in imp.spec["pages"][0]["blocks"] if b["kind"] == "raw")
        self.assertEqual(raw["item"]["table"], "incidents")

    def test_unrepresentable_field_type_is_raw(self):
        d = tomllib.loads('''key = "pg"
title = "ص"
need = "editor"
[[blocks]]
kind = "text"
text = "x"
[[forms]]
key = "fm"
title = "ف"
table = "xx_t"
[[forms.fields]]
name = "when"
kind = "date"
label = "تاریخ"
[[tables]]
name = "xx_t"
columns = [{ name = "when", type = "jsonb" }]
''')
        imp = importer.build("xx", "xx", {"pg": d}, {}, {}, {})
        self.assertEqual([r["part"] for r in imp.report["raw"]], ["forms"])
        self.assertEqual(parsed(imp.spec, "xx")["pg"], pagekit.parse_page("xx", d))

    def test_raw_blocks_cannot_be_created_or_edited_from_the_browser(self):
        imp = importer.build("ext", "خارجی", {"pg": tomllib.loads('key = "pg"\ntitle = "ث"\nneed = "editor"\n[[blocks]]\nkind = "text"\ntext = "x"\n[[forms]]\nkey = "inc"\ntitle = "ح"\ntable = "incidents"\n[[forms.fields]]\nname = "t"\nkind = "text"\nlabel = "ع"\n')}, {}, {}, {})
        spec = imp.spec
        rid = next(b["id"] for b in spec["pages"][0]["blocks"] if b["kind"] == "raw")
        for op in ({"op": "block.add", "page": "pg", "block": {"kind": "raw", "part": "forms", "item": {}}},
                   {"op": "block.set", "id": rid, "fields": {"item": {"key": "inc", "title": "x", "table": "secrets"}}},
                   {"op": "block.set", "id": rid, "fields": {"title": "x"}}):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(spec, "ext", op)
        spec = blueprint.apply(spec, "ext", {"op": "block.move", "id": rid, "at": 0})  # جابه‌جایی و حذف مجازند
        spec = blueprint.apply(spec, "ext", {"op": "block.del", "id": rid})
        self.assertFalse(any(b["kind"] == "raw" for b in spec["pages"][0]["blocks"]))

    def test_tampered_raw_item_is_rejected_by_the_kit_checks(self):
        spec = {"tables": [], "pages": [{"key": "pg", "title": "ص", "blocks": [{"id": "b1", "kind": "text", "text": "x"},
                {"id": "b2", "kind": "raw", "part": "forms", "item": {"key": "fm", "title": "ف", "table": "DROP TABLE x", "fields": []}}]}]}
        self.assertTrue(any(i["scope"] == "block" for i in blueprint.analyze(spec, "pg")["issues"]))
        with self.assertRaises(wizard.WizardError):
            wizard.compile_pages("pg", spec)

    def test_invalid_input_fails_clearly(self):
        with self.assertRaises(importer.ImportFailed):
            importer.build("xx", "xx", {}, {}, {}, {})
        with self.assertRaises(importer.ImportFailed):
            importer.build("xx", "xx", {"pg": {"key": "pg", "title": "ص"}}, {}, {}, {})  # بلوک ندارد


class HandlersAndAlerts(SimpleTestCase):
    def test_roles_alerts_and_tests(self):
        alert = "def handle(ctx, params):\n    return {'alerts': []}\n"
        imp_src = "def handle(ctx, params):\n    return {'columns': [{'name': 'a', 'type': 'text'}], 'rows': [['x']]}\n"
        d = tomllib.loads('''key = "pg"
title = "ص"
need = "editor"
[[blocks]]
kind = "text"
text = "x"
[[imports]]
key = "inc"
title = "ورود"
handler = "load"
extensions = [".csv"]
''')
        tests = {"watch": '[[cases]]\nname = "a"\n[cases.expect]\nalerts_count = 0\n', "load": '[[cases]]\nname = "a"\nfile = "x"\n[cases.expect]\nrows_count = 1\n',
                 "multi": '[[cases]]\nname = "m"\n[cases.expect]\nrows_count = 1\ntext_contains = "x"\n'}
        imp = importer.build("zz", "zz", {"pg": d}, {"load": imp_src, "watch": alert, "multi": imp_src}, tests, {"watch": 30})
        c = imp.spec["code"]
        self.assertEqual((c["load"]["role"], c["watch"]["role"], c["watch"]["every"], c["multi"]["role"]), ("importer", "alert", 30, "block"))
        self.assertTrue(c["watch"]["cases"] and c["load"]["cases"])
        self.assertEqual(c["multi"]["cases"], [])  # دو انتظار: در قالب دیداری نمی‌گنجد
        self.assertIn("text_contains", c["multi"]["test"])  # ولی متن آزمون حفظ می‌شود
        self.assertEqual(imp.report["raw"], [])


@override_settings(ADMIN_2FA_REQUIRED=False)
class ImportFlowTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(cleanup_loaded)
        self.addCleanup(platform.invalidate)
        self.su = get_user_model().objects.create_superuser("imroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)

    def toml_draft(self):
        return samples.ensure_draft(self.su, samples.WEATHER_ID)

    def test_toml_draft_converts_in_place(self):
        d = self.toml_draft()
        self.assertFalse(d.wizard)
        url = reverse("admin:kernel_plugindraft_import") + f"?draft={d.pk}"
        page = self.client.get(url)
        self.assertContains(page, "بدون تفاوت")
        r = self.client.post(url, {"draft": d.pk})
        self.assertRedirects(r, reverse("admin:kernel_plugindraft_designer", args=[d.pk]), fetch_redirect_response=False)
        d.refresh_from_db()
        self.assertTrue(d.wizard["pages"] and d.wizard["tables"])
        self.assertTrue(PluginDraftRevision.objects.filter(draft=d, label__startswith="ورود").exists())
        st = self.client.get(reverse("admin:kernel_plugindraft_api_state", args=[d.pk])).json()
        self.assertTrue(st["analysis"]["ok"], st["analysis"])
        # دوباره باز کردن: دیگر ورود لازم نیست
        self.assertContains(self.client.get(url), "باز کردن در استودیوی دیداری")

    def test_released_plugin_without_draft_can_be_edited_and_republished(self):
        d = PluginDraft.objects.create(plugin_id=PID, name="ناوگان", version="1.0.0", wizard=designer_spec())
        r = self.client.post(reverse("admin:kernel_plugindraft_api_publish", args=[d.pk]), "{}", content_type="application/json")
        self.assertTrue(r.json()["active"], r.json())
        rel = PluginRelease.objects.get(plugin_id=PID)
        d.delete()  # پیش‌نویس از دست رفته: فقط بسته‌ی نصب‌شده مانده
        url = reverse("admin:kernel_plugindraft_import") + f"?release={rel.pk}"
        self.assertContains(self.client.get(url), "ناوگان")
        self.client.post(url, {"release": rel.pk})
        d2 = PluginDraft.objects.get(plugin_id=PID)
        self.assertEqual((d2.version, bool(d2.wizard["pages"])), ("1.0.0", True))
        self.assertEqual(d2.wizard["access"]["mode"], "public_free")  # دسترسی نسخه‌ی منتشرشده برگشت
        st = self.client.get(reverse("admin:kernel_plugindraft_api_state", args=[d2.pk])).json()
        self.assertTrue(st["analysis"]["ok"], st["analysis"])
        r = self.client.post(reverse("admin:kernel_plugindraft_api_publish", args=[d2.pk]), '{"notes": "ویرایش شد"}', content_type="application/json").json()
        self.assertTrue(r["active"], r)
        self.assertEqual(sorted(PluginRelease.objects.filter(plugin_id=PID).values_list("version", flat=True)), ["1.0.0", "1.0.1"])
        # صفحه‌ی منتشرشده‌ی جدید همان صفحه‌های قبلی است (کلیدها حفظ شده‌اند)
        old, new = (pkg.read_archive(bytes(x.blob)) for x in PluginRelease.objects.filter(plugin_id=PID).order_by("version"))
        self.assertEqual(tomllib.loads(old["pages/p1.toml"].decode()).get("forms"), tomllib.loads(new["pages/p1.toml"].decode()).get("forms"))

    def test_release_with_toml_draft_is_blocked_and_permissions(self):
        d = self.toml_draft()
        rel = PluginRelease.objects.create(plugin_id=samples.WEATHER_ID, version="1.0.0", sha256="a" * 64, blob=b"", status="active")
        r = self.client.get(reverse("admin:kernel_plugindraft_import") + f"?release={rel.pk}")
        self.assertEqual(r.status_code, 302)  # بسته‌ی خالی/نامعتبر: پیام و بازگشت
        self.client.logout()
        u = get_user_model().objects.create_admin("imstaff", "Str0ng-Admin-Pass", superuser=False)
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("admin:kernel_plugindraft_import") + f"?draft={d.pk}").status_code, 403)

    def test_raw_only_import_needs_no_confirmation(self):
        d = PluginDraft.objects.create(plugin_id="ext", name="خارجی", version="1.0.0", pages={"pg": 'key = "pg"\ntitle = "ث"\nneed = "editor"\n[[blocks]]\nkind = "text"\ntext = "x"\n[[forms]]\nkey = "inc"\ntitle = "ح"\ntable = "incidents"\n[[forms.fields]]\nname = "t"\nkind = "text"\nlabel = "ع"\n'})
        url = reverse("admin:kernel_plugindraft_import") + f"?draft={d.pk}"
        self.assertContains(self.client.get(url), "بلوک‌های خام")
        r = self.client.post(url, {"draft": d.pk})
        self.assertEqual(r.status_code, 302)
        d.refresh_from_db()
        self.assertEqual([b["kind"] for b in d.wizard["pages"][0]["blocks"]], ["text", "raw"])

    def test_confirm_required_when_report_has_differences(self):
        a = 'key = "aa"\ntitle = "الف"\n[[blocks]]\nkind = "text"\ntext = "x"\n[[tables]]\nname = "dd_t"\ncolumns = [{ name = "a", type = "text" }]\n'
        b = 'key = "bb"\ntitle = "ب"\n[[blocks]]\nkind = "text"\ntext = "y"\n[[tables]]\nname = "dd_t"\ncolumns = [{ name = "a", type = "text" }, { name = "b", type = "text" }]\n'
        d = PluginDraft.objects.create(plugin_id="dd", name="دو", version="1.0.0", pages={"aa": a, "bb": b})
        url = reverse("admin:kernel_plugindraft_import") + f"?draft={d.pk}"
        self.assertContains(self.client.get(url), "تفاوت یا خطا دارد")
        r = self.client.post(url, {"draft": d.pk})
        self.assertEqual(r.status_code, 200)  # بدون تأیید صریح ورود نمی‌شود
        d.refresh_from_db()
        self.assertFalse(d.wizard)
        r = self.client.post(url, {"draft": d.pk, "confirm": "1"})
        self.assertEqual(r.status_code, 302)
        d.refresh_from_db()
        self.assertTrue(d.wizard["pages"])
