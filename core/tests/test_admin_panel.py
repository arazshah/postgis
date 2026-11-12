import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from accounts.models import User
from core import admin_nav


class AdminPanelShellTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_admin("boss", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)

    def test_nav_groups_cover_every_registered_model(self):
        from django.contrib import admin

        req = self.client.get("/manage/").wsgi_request
        from kernel import nav

        shown = {i["label"] for g in admin_nav.build(req) for i in g["items"]}
        registered = {f"{m._meta.app_label}.{m._meta.model_name}" for m in admin.site._registry}
        # صفحه‌های اختصاصی (admin_link) مدل نیستند؛ مدل‌های برداشته‌شده (admin_hide) از راه صفحه‌ی «پلاگین‌ها» در دسترس‌اند
        self.assertEqual((shown - {"plugin_hub"}) | nav.admin_hidden(), registered, "هر بخش ثبت‌شده باید در منو یا صفحه‌ی اختصاصی باشد")

    def test_shell_has_sidebar_and_search(self):
        html = self.client.get("/manage/").content.decode()
        for needle in ('id="ap-side"', 'id="ap-pal"', 'id="ap-palette"', "مشتریان", "تنظیمات و امنیت"):
            self.assertIn(needle, html)

    def test_pages_render_inside_shell(self):
        for url in ("/manage/core/sitesettings/", "/manage/accounts/siteuser/", "/manage/billing/invoice/",
                    "/manage/databases/plan/add/"):
            r = self.client.get(url, follow=True)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, 'id="ap-side"')

    def test_search_requires_staff_and_finds_records(self):
        User.objects.create_user("09121234567", full_name="علی رضایی")
        r = self.client.get("/manage/_search/", {"q": "علی"})
        self.assertEqual([x["g"] for x in r.json()["rows"]], ["کاربر"])
        self.assertEqual(self.client.get("/manage/_search/", {"q": "ع"}).json()["rows"], [])
        self.client.logout()
        self.assertEqual(self.client.get("/manage/_search/", {"q": "علی"}).status_code, 302)

    def test_tokens_match_app_css(self):
        root = Path(settings.BASE_DIR) / "static" / "css"
        panel = (root / "admin-panel.css").read_text()
        theirs = (root / "app.css").read_text() + (root / "ds.css").read_text()
        for name in ("--paper", "--surface", "--ink", "--ink-2", "--line", "--teal", "--teal-dark", "--teal-soft",
                     "--ochre", "--red", "--green", "--card", "--line-2", "--ink-3", "--r-card", "--r-ctl"):
            mine = re.search(rf"{re.escape(name)}:\s*([^;]+);", panel)
            orig = re.search(rf"{re.escape(name)}:\s*([^;]+?)\s*[;}}]", theirs)
            self.assertTrue(mine and orig, name)
            self.assertEqual(mine.group(1).strip(), orig.group(1).strip(), name)


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_admin("boss", "Str0ng-Admin-Pass"))

    def test_empty_install_shows_attention_and_health(self):
        r = self.client.get("/manage/")
        self.assertContains(r, "نیاز به توجه")
        self.assertContains(r, "هنوز هیچ سرور دیتابیسی تعریف نشده")
        self.assertEqual(len(r.context["ap_health"]), 6)
        self.assertEqual(len(r.context["ap_kpis"]), 6)

    def test_pending_invoice_and_ticket_show_actions(self):
        from billing.models import Invoice
        from support.models import Ticket

        u = User.objects.create_user("09121234567", full_name="علی")
        Ticket.objects.create(user=u, subject="کمک")
        r = self.client.get("/manage/")
        texts = " ".join(a["text"] for a in r.context["ap_attention"])
        self.assertIn("تیکت منتظر پاسخ", texts)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertContains(r, "فعالیت اخیر")


class AdminNavActiveTests(TestCase):
    def test_only_current_section_is_active(self):
        self.client.force_login(User.objects.create_admin("boss", "Str0ng-Admin-Pass"))
        r = self.client.get("/manage/databases/userdatabase/")
        active = [i["label"] for g in admin_nav.build(r.wsgi_request) for i in g["items"] if i["on"]]
        self.assertEqual(active, ["databases.userdatabase"])
