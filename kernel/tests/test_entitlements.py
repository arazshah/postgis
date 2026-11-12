"""موتور مجوز، دروازه‌ی آدرس و پنل مدیریت پلاگین‌ها."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, gate
from kernel.models import Entitlement, Organization, OrgMember, PluginState

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def grant(plugin, kind, subject="", **kw):
    st, _ = PluginState.objects.get_or_create(plugin_id=plugin)
    return Entitlement.objects.create(state=st, kind=kind, subject=str(subject), **kw)


class EngineTests(BaseCase):
    def setUp(self):
        super().setUp()
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)  # بازگشت تراکنش آزمون سیگنال نمی‌فرستد؛ حافظه نباید به آزمون بعدی نشت کند
        self.db = services.create_database(self.user, "entdb", "Abcdefgh123", ["postgis"])
        self.other = User.objects.create_user("09120000002")

    def restrict(self, plugin="tools"):
        PluginState.objects.update_or_create(plugin_id=plugin, defaults={"access": PluginState.Access.RESTRICTED})

    def test_defaults_open_unknown_closed_and_system_always_allowed(self):
        self.assertTrue(entitlements.allowed("tools", user=self.user))  # ردیفی نیست = باز
        self.assertFalse(entitlements.allowed("not_installed", user=self.user))
        PluginState.objects.create(plugin_id="databases", enabled=False, access="restricted")
        self.assertTrue(entitlements.allowed("databases", user=self.user))
        self.assertTrue(entitlements.is_enabled("databases"))

    def test_off_hides_for_everyone_even_with_a_grant(self):
        PluginState.objects.create(plugin_id="tools", enabled=False)
        grant("tools", "all")
        self.assertFalse(entitlements.allowed("tools", user=self.user))
        self.assertFalse(entitlements.is_enabled("tools"))

    def test_restricted_needs_a_matching_valid_grant(self):
        self.restrict()
        self.assertFalse(entitlements.allowed("tools", user=self.user))
        self.assertFalse(entitlements.allowed("tools", user=None))
        grant("tools", "user", self.user.pk)
        self.assertTrue(entitlements.allowed("tools", user=self.user))
        self.assertFalse(entitlements.allowed("tools", user=self.other))

    def test_each_subject_kind(self):
        self.restrict()
        e = grant("tools", "workspace", self.db.pk)
        self.assertTrue(entitlements.allowed("tools", ws=self.db))
        self.assertFalse(entitlements.allowed("tools", user=self.other))
        e.delete()
        grant("tools", "plan", self.db.plan.slug)
        self.assertTrue(entitlements.allowed("tools", ws=self.db))
        self.assertFalse(entitlements.allowed("tools", user=self.user))  # مجوز پلن بدون فضای کار برای کاربر معنا ندارد
        Entitlement.objects.all().delete()
        # مجوز مالک برای اعضای همان فضای کار هم برقرار است
        grant("tools", "user", self.user.pk)
        self.assertTrue(entitlements.allowed("tools", user=self.other, ws=self.db))
        Entitlement.objects.all().delete()
        org = Organization.objects.create(name="شرکت", slug="co")
        OrgMember.objects.create(org=org, user=self.user)
        grant("tools", "org", org.pk)
        self.assertTrue(entitlements.allowed("tools", user=self.user))
        self.assertTrue(entitlements.allowed("tools", user=self.other, ws=self.db))  # مالک عضو سازمان است
        self.assertFalse(entitlements.allowed("tools", user=self.other))
        Entitlement.objects.all().delete()
        grant("tools", "all")
        self.assertTrue(entitlements.allowed("tools", user=self.other))

    def test_expiry_and_limits(self):
        self.restrict()
        grant("tools", "user", self.user.pk, expires_at=timezone.now() - timedelta(minutes=1), limits={"devices": 5})
        self.assertFalse(entitlements.allowed("tools", user=self.user))
        grant("tools", "all", limits={"devices": 50, "label": "x"})
        grant("tools", "workspace", self.db.pk, limits={"devices": 80})
        self.assertEqual(entitlements.limits("tools", user=self.user, ws=self.db), {"devices": 80, "label": "x"})

    def test_changes_are_visible_immediately_in_this_process(self):
        self.restrict()
        self.assertFalse(entitlements.allowed("tools", user=self.user))
        e = grant("tools", "user", self.user.pk)
        self.assertTrue(entitlements.allowed("tools", user=self.user))
        e.delete()
        self.assertFalse(entitlements.allowed("tools", user=self.user))

    def test_workspace_grants_are_removed_when_the_workspace_is_deleted(self):
        self.restrict()
        grant("tools", "workspace", self.db.pk)
        keep = grant("tools", "user", self.user.pk)
        services.delete_database(self.db, actor=self.user)
        self.assertEqual(list(Entitlement.objects.all()), [keep])


class GateTests(BaseCase):
    def setUp(self):
        super().setUp()
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)  # بازگشت تراکنش آزمون سیگنال نمی‌فرستد؛ حافظه نباید به آزمون بعدی نشت کند
        self.db = services.create_database(self.user, "gatedb", "Abcdefgh123", ["postgis"])
        self.mw = gate.PluginGateMiddleware(lambda r: None)
        self.rf = RequestFactory()

    def call(self, view, user, route="dashboard/<int:pk>/tools/", **kw):
        req = self.rf.get("/x/")
        req.user = user
        req.resolver_match = SimpleNamespace(route=route)
        return self.mw.process_view(req, view, (), kw)

    def test_owner_plugin_comes_from_the_view_module(self):
        from databases import views as dviews
        from tools import views as tviews

        self.assertEqual(gate.owner_plugin(tviews.index), "tools")
        self.assertEqual(gate.owner_plugin(dviews.dashboard), "databases")
        self.assertIsNone(gate.owner_plugin(lambda r: None))

    def test_open_and_system_pass_restricted_is_404_until_granted(self):
        from databases import views as dviews
        from tools import views as tviews

        self.assertIsNone(self.call(tviews.index, self.user, pk=self.db.pk))
        PluginState.objects.create(plugin_id="databases", enabled=False)
        self.assertIsNone(self.call(dviews.dashboard, self.user, route="dashboard/"))
        PluginState.objects.create(plugin_id="tools", access="restricted")
        with self.assertRaises(Http404):
            self.call(tviews.index, self.user, pk=self.db.pk)
        with self.assertRaises(Http404):
            self.call(tviews.index, None, pk=self.db.pk)
        grant("tools", "workspace", self.db.pk)
        self.assertIsNone(self.call(tviews.index, self.user, pk=self.db.pk))

    def test_off_is_404_and_public_marker_only_skips_the_restriction(self):
        from tools import views as tviews

        PluginState.objects.create(plugin_id="tools", access="restricted")

        def pub(request):
            return None

        pub.__module__ = "tools.views"
        gate.public(pub)
        self.assertIsNone(self.call(pub, None, route="hook/"))
        st = PluginState.objects.get(plugin_id="tools")
        st.enabled = False
        st.save()
        with self.assertRaises(Http404):
            self.call(pub, None, route="hook/")
        with self.assertRaises(Http404):
            self.call(tviews.index, self.user, pk=self.db.pk)


@override_settings(STORAGES=STORAGES)
class EndToEndTests(BaseCase):
    def setUp(self):
        super().setUp()
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)  # بازگشت تراکنش آزمون سیگنال نمی‌فرستد؛ حافظه نباید به آزمون بعدی نشت کند
        self.db = services.create_database(self.user, "e2edb", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        p = mock.patch("kernel.tenantdb.catalog")
        self.catalog = p.start().return_value
        self.catalog.tables.return_value = []
        self.addCleanup(p.stop)
        self.url = reverse("tools:page", args=[self.db.pk])
        self.dashboard = reverse("databases:detail", args=[self.db.pk])

    def test_restricted_plugin_disappears_from_menu_and_urls_then_returns_with_a_grant(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.client.get(self.dashboard), reverse("tools:page", args=[self.db.pk]))
        PluginState.objects.create(plugin_id="tools", access="restricted")
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertNotContains(self.client.get(self.dashboard), self.url)
        grant("tools", "user", self.user.pk)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.client.get(self.dashboard), self.url)

    def test_off_plugin_is_gone_for_its_owner_too(self):
        PluginState.objects.create(plugin_id="tools", enabled=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertNotContains(self.client.get(self.dashboard), self.url)


class ProfileSectionGateTests(BaseCase):
    def test_profile_tab_follows_plugin_state(self):
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)  # بازگشت تراکنش آزمون سیگنال نمی‌فرستد؛ حافظه نباید به آزمون بعدی نشت کند
        self.client.force_login(self.user)
        url = reverse("accounts:profile")
        with override_settings(STORAGES=STORAGES):
            self.assertContains(self.client.get(url), 'id="t-ai"')
            PluginState.objects.create(plugin_id="analysis", access="restricted")
            self.assertNotContains(self.client.get(url), 'id="t-ai"')


class PluginAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_admin("boss2", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)  # بازگشت تراکنش آزمون سیگنال نمی‌فرستد؛ حافظه نباید به آزمون بعدی نشت کند

    def test_changelist_syncs_rows_for_non_system_plugins_only(self):
        r = self.client.get(reverse("admin:kernel_pluginstate_changelist"))
        self.assertEqual(r.status_code, 200)
        ids = set(PluginState.objects.values_list("plugin_id", flat=True))
        self.assertIn("tools", ids)
        self.assertIn("maps", ids)
        self.assertNotIn("databases", ids)
        self.assertNotIn("accounts", ids)
        self.assertContains(r, "ابزارهای تحلیل")

    def test_actions_flip_state_and_take_effect(self):
        self.client.get(reverse("admin:kernel_pluginstate_changelist"))
        pk = PluginState.objects.get(plugin_id="tools").pk
        url = reverse("admin:kernel_pluginstate_changelist")
        self.client.post(url, {"action": "make_restricted", "_selected_action": [pk]})
        self.assertEqual(PluginState.objects.get(pk=pk).access, "restricted")
        self.assertFalse(entitlements.allowed("tools", user=self.admin))
        self.client.post(url, {"action": "turn_off", "_selected_action": [pk]})
        self.assertFalse(PluginState.objects.get(pk=pk).enabled)

    def test_entitlement_form_validates_subjects(self):
        from kernel.admin import EntitlementForm

        def form(kind, subject):
            return EntitlementForm({"kind": kind, "subject": subject, "source": "manual", "limits": "{}"})

        everyone = form("all", "ignored")
        self.assertTrue(everyone.is_valid())
        self.assertEqual(everyone.cleaned_data["subject"], "")
        self.assertFalse(form("plan", "").is_valid())
        self.assertTrue(form("plan", "free").is_valid())
        self.assertFalse(form("user", "abc").is_valid())
        self.assertFalse(form("user", "999999").is_valid())
        self.assertTrue(form("user", str(self.admin.pk)).is_valid())
        self.assertFalse(form("org", "999999").is_valid())
        self.assertFalse(form("workspace", "999999").is_valid())

    def test_platform_group_is_in_the_admin_menu(self):
        html = self.client.get("/manage/").content.decode()
        self.assertIn("پلاگین‌ها و مشتریان سازمانی", html)
        self.assertIn(reverse("plugin_hub"), html)  # یک ورودی «پلاگین‌ها»؛ بقیه زیر زبانه‌هاست (ADR-0008)
        self.assertIn("سازمان", html)

    def test_organization_admin_pages_render(self):
        org = Organization.objects.create(name="شرکت نمونه", slug="sample")
        self.assertEqual(self.client.get(reverse("admin:kernel_organization_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:kernel_organization_change", args=[org.pk])).status_code, 200)
