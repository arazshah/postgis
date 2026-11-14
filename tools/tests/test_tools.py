"""بخش ابزارها و تاریخچهٔ کارتی: کاتالوگ، گالری، فرم هر ابزار، تازه‌سازی تاریخچه (بدون PostgreSQL واقعی)."""
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from analysis.models import Question, ToolRun
from core.icons import ICONS
from databases import services
from databases.explorer import ExplorerError, TableRef
from databases.tests.test_services import BaseCase
from jobs.models import Job
from tools import catalog, engine

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def _t(name, gtype, schema="public"):
    return TableRef(schema, name, 1, "r", geometry=[{"type": gtype, "srid": 4326, "geography": False}])


class CatalogTests(BaseCase):
    def test_every_engine_tool_has_a_catalog_entry_with_known_icon_and_params(self):
        self.assertEqual({t.key for t in engine.TOOLS}, set(catalog.INFO))
        cats = {k for k, _t_, _h in catalog.CATEGORIES}
        for i in catalog.CATALOG:
            self.assertIn(i.category, cats, i.key)
            self.assertIn(i.icon, ICONS, i.key)
            self.assertTrue(i.title and i.description and i.example and i.columns, i.key)
            for p in i.params:
                self.assertIn(p.name, engine.PUBLIC_PARAMS, f"{i.key}.{p.name}")
                self.assertIn(p.kind, {"layer", "number", "text", "choice", "bool"})
            self.assertEqual(len({p.name for p in i.params}), len(i.params))

    def test_toolbox_has_fifty_tools_in_nine_categories_with_valid_metadata(self):
        from tools import sdk

        tools = sdk.all_tools()
        self.assertEqual(len(tools), 50)
        self.assertEqual(len(sdk.categories()), 9)
        levels = {k for k, _ in sdk.LEVELS}
        for t in tools:
            with self.subTest(tool=t.key):
                self.assertIn(t.level, levels)
                self.assertLessEqual(len(t.key), 20)
                self.assertTrue(t.title and t.description and t.example and t.columns)
                for p in t.params:
                    self.assertIn(p.group, ("", "input", "settings", "advanced"))
        for c in sdk.categories():
            self.assertIn(c.icon, ICONS, c.key)
            self.assertGreaterEqual(len([t for t in tools if t.category == c.key]), 4, c.key)
        self.assertGreaterEqual(len([t for t in tools if t.popular]), 8)

    def test_home_page_advertises_the_toolbox_from_registry(self):
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, 'id="toolbox"')
        self.assertContains(r, "۵۰ ابزار تخصصی")
        for c in catalog.category_groups():
            self.assertContains(r, c["title"])

    def test_groups_cover_all_tools_once(self):
        keys = [i.key for g in catalog.category_groups() for i in g["tools"]]
        self.assertEqual(sorted(keys), sorted(catalog.INFO))


@override_settings(STORAGES=STORAGES)
class ToolsPagesTests(BaseCase):
    TABLES = [_t("schools", "POINT"), _t("parks", "MULTIPOLYGON"), _t("zones", "POLYGON")]

    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "toolsdb", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.tables = list(self.TABLES)
        patcher = mock.patch("kernel.tenantdb.catalog")
        self.explorer = patcher.start().return_value
        self.explorer.tables.side_effect = lambda: self.tables
        self.addCleanup(patcher.stop)
        self.index = reverse("tools:page", args=[self.db.pk])

    def test_gallery_lists_tools_by_category_with_icons_and_reasons(self):
        r = self.client.get(self.index)
        for i in catalog.CATALOG:
            self.assertContains(r, i.title)
            self.assertContains(r, reverse("tools:detail", args=[self.db.pk, i.key]))
        for _k, title, _h in catalog.CATEGORIES:
            self.assertContains(r, title)
        self.assertContains(r, "به شبکه معابر نیاز دارد")  # حوزه دسترسی بدون شبکهٔ مسیریابی
        self.assertContains(r, "js/tools.js")
        self.assertContains(r, "ابزارها")  # ریل کناری

    def test_gallery_disables_tools_without_matching_layers(self):
        self.tables = [_t("parks", "POLYGON")]
        r = self.client.get(self.index)
        self.assertContains(r, "لایه نقطه‌ای ندارید")
        self.tables = []
        self.assertContains(self.client.get(self.index), "لایه مکانی ندارید")

    def test_routing_enables_isochrone(self):
        self.tables.append(TableRef("routing", "ways", 1, "r", geometry=[{"type": "LINESTRING", "srid": 4326}]))
        self.assertNotContains(self.client.get(self.index), "به شبکه معابر نیاز دارد")

    def test_detail_form_is_built_from_catalog_and_filters_layer_types(self):
        r = self.client.get(reverse("tools:detail", args=[self.db.pk, "count"]))
        self.assertContains(r, "لایه چندضلعی")
        html = r.content.decode()
        poly = html.split('name="layer"')[1].split("</select>")[0]
        self.assertIn("parks", poly)
        self.assertIn("zones", poly)
        self.assertNotIn("schools", poly)  # فقط چندضلعی
        point = html.split('name="other"')[1].split("</select>")[0]
        self.assertIn("schools", point)
        self.assertNotIn("parks", point)
        self.assertContains(r, 'name="agg"')  # انتخاب با چیپ
        self.assertContains(r, "point_count")  # ستون‌های خروجی در راهنما
        self.assertContains(r, 'value="count_result"')

    def test_buffer_form_has_dissolve_checkbox_and_isochrone_form_is_disabled_without_routing(self):
        self.assertContains(self.client.get(reverse("tools:detail", args=[self.db.pk, "buffer"])), 'name="dissolve"')
        r = self.client.get(reverse("tools:detail", args=[self.db.pk, "isochrone"]))
        self.assertContains(r, "به شبکه معابر نیاز دارد")
        self.assertContains(r, "disabled")

    def test_unknown_tool_is_404(self):
        self.assertEqual(self.client.get(reverse("tools:detail", args=[self.db.pk, "nope"])).status_code, 404)

    def test_other_users_cannot_open(self):
        from accounts.models import User

        self.client.force_login(User.objects.create_user("09120000099"))
        self.assertEqual(self.client.get(self.index).status_code, 404)

    def test_post_queues_job_and_blocks_second_while_busy(self):
        url = reverse("tools:detail", args=[self.db.pk, "buffer"])
        post = {"layer": "public.parks", "distance": "100", "output": "park_100"}
        with mock.patch.object(engine, "validate", return_value="park_100"), \
                mock.patch.object(engine, "summarize", return_value="حریم ۱۰۰ متر"):
            r = self.client.post(url, post)
            self.assertRedirects(r, url + "#history", fetch_redirect_response=False)
            run = ToolRun.objects.get()
            self.assertEqual((run.tool, run.output_table, run.job.kind, run.job.status), ("buffer", "park_100", "tool", "queued"))
            r = self.client.post(url, {**post, "output": "park_200"})
            self.assertEqual(r.status_code, 200)  # صفحه با پیام دوباره می‌آید
            self.assertContains(r, "یک تحلیل در حال اجراست")
            self.assertEqual(ToolRun.objects.count(), 1)

    def test_post_validation_error_keeps_form_values_and_flags_the_modal(self):
        url = reverse("tools:detail", args=[self.db.pk, "buffer"])
        with mock.patch.object(engine, "validate", side_effect=engine.ToolError("نام جدول خروجی نامعتبر است")):
            r = self.client.post(url, {"layer": "public.parks", "distance": "777", "output": "Bad name"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ToolRun.objects.count(), 0)
        self.assertContains(r, "نام جدول خروجی نامعتبر است")
        self.assertContains(r, 'value="777"')  # ورودی‌های کاربر حفظ می‌شود
        self.assertContains(r, 'data-flash hidden')  # پیام برای مودال خطا علامت‌گذاری شده

    def test_explorer_error_is_reported_not_crashed(self):
        self.explorer.tables.side_effect = ExplorerError("اتصال برقرار نشد")
        r = self.client.get(self.index)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "اتصال برقرار نشد")


@override_settings(STORAGES=STORAGES)
class HistoryCardsTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "histdb", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        patcher = mock.patch("kernel.tenantdb.catalog")
        self.explorer = patcher.start().return_value
        self.explorer.tables.return_value = [_t("parks", "POLYGON")]
        self.addCleanup(patcher.stop)

    def _run(self, status, tool="buffer", table="out_1", rows=0, message="", progress=0):
        job = Job.objects.create(kind=Job.Kind.TOOL, database=self.db, user=self.user, status=status,
                                 message=message, progress=progress)
        return ToolRun.objects.create(database=self.db, user=self.user, tool=tool, output_table=table, rows=rows,
                                      job=job, summary="s", params={"layer": "public.parks"})

    def test_cards_show_state_and_details_live_in_a_dialog(self):
        self._run("done", table="ok_t", rows=7)
        self._run("failed", table="bad_t", message="جدول bad_t از قبل وجود دارد")
        self._run("running", table="run_t", progress=40)
        r = self.client.get(reverse("tools:page", args=[self.db.pk]))
        self.assertContains(r, 'class="hc-grid"')
        self.assertContains(r, "hc-done")
        self.assertContains(r, "hc-failed")
        self.assertContains(r, "hc-running")
        self.assertContains(r, 'role="progressbar"')
        self.assertContains(r, 'class="dlg dlg-xl"', count=3)  # جزئیات هر کارت در مودال
        self.assertContains(r, "جدول bad_t از قبل وجود دارد")  # علت خطا در مودال
        self.assertContains(r, "?tab=map")  # دکمهٔ اصلی نقشه
        self.assertContains(r, 'data-hf="failed"')  # فیلتر وضعیت
        self.assertContains(r, "data-active=\"1\"")

    def test_empty_state_is_designed(self):
        r = self.client.get(reverse("tools:page", args=[self.db.pk]))
        self.assertContains(r, "هنوز اجرایی ندارید")
        self.assertNotContains(r, "hc-grid")

    def test_fragment_returns_only_history_and_filters_by_tool(self):
        self._run("done", tool="buffer", table="b_t", rows=1)
        self._run("done", tool="hexbin", table="h_t", rows=1)
        url = reverse("analysis:history", args=[self.db.pk])
        r = self.client.get(url, {"k": "tool", "tool": "buffer"})
        self.assertContains(r, "b_t")
        self.assertNotContains(r, "h_t")
        self.assertNotContains(r, "<html")
        self.assertNotContains(r, "analysis.js")  # اسکریپت فقط در صفحهٔ کامل
        self.assertContains(self.client.get(url, {"k": "tool"}), "h_t")

    def test_analysis_page_shows_only_questions_and_links_to_tools(self):
        self._run("done", table="tool_only_t", rows=1)
        job = Job.objects.create(kind=Job.Kind.ASK, database=self.db, user=self.user, status="done")
        Question.objects.create(database=self.db, user=self.user, text="پرسش نمونه برای کارت", output_table="q_t",
                                job=job, result_kind="layer", rows=3)
        r = self.client.get(reverse("analysis:page", args=[self.db.pk]))
        self.assertContains(r, "پرسش نمونه برای کارت")
        self.assertNotContains(r, "tool_only_t")
        self.assertContains(r, reverse("tools:page", args=[self.db.pk]))
        self.assertNotContains(r, "tool-tabs")

    def test_plan_card_has_approve_actions_in_dialog(self):
        job = Job.objects.create(kind=Job.Kind.ASK, database=self.db, user=self.user, status="done")
        q = Question.objects.create(database=self.db, user=self.user, text="برنامه‌دار", output_table="q_t", job=job,
                                    result_kind="plan", plan_text=["گام یک"])
        r = self.client.get(reverse("analysis:page", args=[self.db.pk]))
        self.assertContains(r, "درست است؛ اجرا کن")
        self.assertContains(r, "برنامهٔ پیشنهادی")
        self.assertContains(r, f'name="q" value="{q.pk}"')
        self.assertContains(r, "hc-plan")

    def test_legacy_tool_link_redirects(self):
        a = reverse("analysis:page", args=[self.db.pk])
        self.assertRedirects(self.client.get(a + "?tool=hexbin"), reverse("tools:detail", args=[self.db.pk, "hexbin"]),
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get(a + "?tool=zzz"), reverse("tools:page", args=[self.db.pk]),
                             fetch_redirect_response=False)
