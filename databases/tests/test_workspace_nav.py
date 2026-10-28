"""منوی کنار صفحه‌ی فضای کار، تعویض سریع پایگاه، داشبورد فشرده و جای دکمه‌ی دستیار (بدون PostgreSQL واقعی)."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.templatetags import ws
from databases import services
from databases.models import Member, UserDatabase
from databases.tests.test_services import BaseCase

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
ROOT = Path(__file__).resolve().parents[2]


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class WorkspaceNavTests(BaseCase):
    def _dbs(self, *names):
        return [services.create_database(self.user, n, "Abcdefgh123", ["postgis"]) for n in names]

    def test_menu_has_collapsible_groups_and_tools(self):
        (db,) = self._dbs("tehran")
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:backups", args=[db.pk]))
        self.assertContains(r, 'data-key="data"')
        self.assertContains(r, 'data-key="share"')
        self.assertContains(r, 'data-key="manage"')
        self.assertContains(r, "data-ws-collapse")
        self.assertContains(r, "ws-tabs")  # نوار تب پایین گوشی
        self.assertContains(r, "app-top")  # نوار بالای برنامه
        self.assertNotContains(r, "data-ws-wide")
        self.assertContains(r, "data-ws-jump")
        self.assertContains(r, 'data-gpa-slot="menu"')  # جای ثابت دکمه‌ی دستیار، نه شناور روی محتوا
        self.assertContains(r, 'data-gpa-slot="bar"')
        self.assertContains(r, "js/ws-nav.js")
        # بخش فعلی مشخص است و گروه «مدیریت» که بکاپ در آن است همان است
        self.assertContains(r, 'aria-current="page"')

    def test_single_database_has_no_switcher(self):
        (db,) = self._dbs("tehran")
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:backups", args=[db.pk]))
        self.assertNotContains(r, "data-ws-sw")

    def test_switcher_keeps_the_same_section(self):
        a, b = self._dbs("alpha", "beta")
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:backups", args=[a.pk]))
        self.assertContains(r, "data-ws-sw")
        self.assertContains(r, f'href="{reverse("databases:backups", args=[b.pk])}"')
        self.assertNotContains(r, f'href="{reverse("databases:backups", args=[a.pk])}">gp_alpha')

    def test_switcher_includes_shared_and_sends_inactive_to_overview(self):
        a, b = self._dbs("alpha", "beta")
        UserDatabase.objects.filter(pk=b.pk).update(status=UserDatabase.Status.SUSPENDED)
        other = User.objects.create_user("09120000002")
        c = services.create_database(other, "gamma", "Abcdefgh123", ["postgis"])
        Member.objects.create(database=c, phone=self.user.phone, user=self.user, role="viewer")
        data = ws.switch_targets(self.user, a, {"url": "databases:backups"})
        urls = {d["name"]: d["url"] for d in data}
        self.assertEqual(urls[b.db_name], reverse("databases:detail", args=[b.pk]))  # غیرفعال → نمای کلی
        self.assertEqual(urls[c.db_name], reverse("databases:backups", args=[c.pk]))
        self.assertNotIn(a.db_name, urls)
        self.assertFalse(next(d for d in data if d["name"] == c.db_name)["mine"])

    def test_jump_entries_cover_sections_and_databases(self):
        a, b = self._dbs("alpha", "beta")
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:backups", args=[a.pk]))
        html = r.content.decode()
        raw = html.split('id="ws-jump" type="application/json">')[1].split("</script>")[0]
        entries = json.loads(raw)
        kinds = {e["k"] for e in entries}
        self.assertEqual(kinds, {"s", "d"})
        self.assertIn(reverse("databases:backups", args=[a.pk]), {e["u"] for e in entries if e["k"] == "s"})
        self.assertIn(b.db_name, {e["t"] for e in entries if e["k"] == "d"})


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class DashboardListTests(BaseCase):
    def _dbs(self, n):
        return [services.create_database(self.user, f"db{i}", "Abcdefgh123", ["postgis"]) for i in range(n)]

    def test_single_database_shows_full_card_without_toolbar(self):
        self._dbs(1)
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertNotContains(r, "data-dash-bar")
        self.assertContains(r, "data-dash-list")  # کارت کامل برای کاربر تازه‌وارد

    def test_several_databases_get_compact_toolbar_and_row_menu(self):
        dbs = self._dbs(2)
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertContains(r, "data-dash-bar")
        self.assertContains(r, 'data-dash-view="compact"')
        self.assertNotContains(r, "data-dash-q")  # جست‌وجو فقط از چهار پایگاه به بالا
        for d in dbs:
            self.assertContains(r, f'id="dash-body-{d.pk}"')
            self.assertContains(r, 'class="dl-more dash-menu"')
            self.assertContains(r, reverse("databases:backups", args=[d.pk]))  # همه‌ی بخش‌ها در منوی «⋯»

    def test_many_databases_get_search_filter_and_sort(self):
        self._dbs(4)
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        for attr in ("data-dash-q", "data-dash-filter", "data-dash-sort"):
            self.assertContains(r, attr)
        self.assertContains(r, 'data-name="gp_db0"')

    def test_attention_level_marks_cards_for_filtering(self):
        a, b = self._dbs(2)
        UserDatabase.objects.filter(pk=b.pk).update(size_bytes=b.plan.quota_bytes, status=UserDatabase.Status.READONLY)
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        html = r.content.decode()
        self.assertIn('data-attn="2"', html)  # پر شده
        self.assertIn("sum-alert al-bad", html)

    def test_shared_databases_get_their_own_tab(self):
        self._dbs(1)
        other = User.objects.create_user("09120000002")
        c = services.create_database(other, "gamma", "Abcdefgh123", ["postgis"])
        Member.objects.create(database=c, phone=self.user.phone, user=self.user, role="viewer")
        self.client.force_login(self.user)
        r = self.client.get(reverse("databases:dashboard"))
        self.assertContains(r, 'data-dash-tab="shared"')
        self.assertContains(r, 'id="dash-shared"')
        self.assertContains(r, "js/dashboard.js")


class FrontendScriptTests(SimpleTestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_scripts_parse(self):
        for name in ("ws-nav.js", "dashboard.js", "assistant.js", "explore-nav.js"):
            r = subprocess.run(["node", "--check", str(ROOT / "static" / "js" / name)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"{name}\n{r.stderr}")

    def test_studios_reserve_a_slot_for_the_assistant(self):
        for rel in ("templates/maps/composer.html", "templates/survey/studio.html"):
            self.assertIn('data-gpa-slot="studio"', (ROOT / rel).read_text(encoding="utf-8"), rel)
