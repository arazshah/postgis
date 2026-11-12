"""ثبت مسیر توسط پلاگین (kernel.routes) و جدا بودن بخش‌های databases (ADR-0006)."""
from django.http import Http404, HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from kernel import gate, routes
from kernel.plugins import registry


def good_view(request, pk):
    return HttpResponse(f"ok {pk}")


class RoutesTests(SimpleTestCase):
    def setUp(self):
        registry.register("rt_demo", "نمونه", kind="feature")
        self.addCleanup(registry.remove_plugin, "rt_demo")

    def test_patterns_follow_registration_order_and_names(self):
        routes.add("rt_group", "<int:pk>/b/", "kernel.tests.test_routes.good_view", "b", plugin="rt_demo", order=20)
        routes.add("rt_group", "<int:pk>/a/", "kernel.tests.test_routes.good_view", "a", plugin="rt_demo", order=10)
        pats = routes.patterns("rt_group")
        self.assertEqual([p.name for p in pats], ["a", "b"])
        self.assertEqual(pats[0].callback(RequestFactory().get("/"), 3).content, b"ok 3")
        self.assertEqual(routes.patterns("another_group"), [])

    def test_broken_view_mounts_a_404_and_is_reported_not_fatal(self):
        routes.add("rt_group", "<int:pk>/x/", "kernel.tests.test_routes.nope", "x", plugin="rt_demo")
        (pat,) = routes.patterns("rt_group")
        self.assertEqual(pat.name, "x")
        with self.assertRaises(Http404):
            pat.callback(RequestFactory().get("/"), 1)
        self.assertIn("rt_demo", registry.errors)
        self.assertEqual([(p, n) for p, n, _e in routes.broken()], [("rt_demo", "rt_group:x")])
        self.assertIsNone(gate.owner_plugin(pat.callback))  # صاحبش هسته است؛ دروازه‌ی مجوز دخالت نمی‌کند

    def test_duplicate_route_from_another_plugin_is_refused(self):
        registry.register("rt_other", "دیگر", kind="feature")
        self.addCleanup(registry.remove_plugin, "rt_other")
        routes.add("rt_group", "<int:pk>/a/", "kernel.tests.test_routes.good_view", "a", plugin="rt_demo")
        from kernel.plugins import PluginError

        with self.assertRaises(PluginError):
            routes.add("rt_group", "<int:pk>/z/", "kernel.tests.test_routes.good_view", "a", plugin="rt_other")


class DatabasesSectionsTests(SimpleTestCase):
    SECTIONS = {"dbtables": 15, "dbsql": 3, "dbfind": 7, "dbimport": 2, "dbhealth": 1, "dbbackup": 4, "dbusage": 1, "dbteam": 1}

    def test_every_section_is_a_feature_plugin_with_its_routes(self):
        for pid, n in self.SECTIONS.items():
            with self.subTest(plugin=pid):
                self.assertEqual(registry.plugins[pid].kind, "feature")
                self.assertEqual(len([r for r in routes.routes("databases") if r.plugin == pid]), n)
        self.assertEqual(sum(self.SECTIONS.values()), len(routes.routes("databases")))

    def test_urls_and_names_are_unchanged(self):
        self.assertEqual(reverse("databases:explore", args=[7]), "/dashboard/7/explore/")
        self.assertEqual(reverse("databases:explore_table", args=[7, "public", "t"]), "/dashboard/7/explore/t/public/t/")
        self.assertEqual(reverse("databases:import_review", args=[7, 3]), "/dashboard/7/import/3/")
        self.assertEqual(reverse("databases:backup_restore", args=[7, 3]), "/dashboard/7/backups/3/restore/")
        self.assertEqual(reverse("databases:find_save_status", args=[7]), "/dashboard/7/find/save/status/")
        self.assertEqual(reverse("databases:team", args=[7]), "/dashboard/7/team/")

    def test_views_belong_to_their_plugin_so_the_permission_gate_applies(self):
        from dbfind import views as find_views
        from dbtables import views as table_views

        self.assertEqual(gate.owner_plugin(table_views.explore), "dbtables")
        self.assertEqual(gate.owner_plugin(find_views.find), "dbfind")

    def test_no_route_is_unavailable_in_a_healthy_install(self):
        self.assertEqual(routes.broken(), [])


class RouteOnTests(TestCase):
    """پیوند بین‌بخشی نباید به بخش خاموش یا محدودشده برود (ADR-0006)."""

    def setUp(self):
        from kernel import entitlements

        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)

    def test_unregistered_route_is_always_on_and_registered_follows_the_plugin_state(self):
        from unittest import mock

        from kernel import entitlements

        self.assertTrue(routes.on("databases:dashboard"))  # مسیر میزبان ثبت‌نشده در routes
        self.assertTrue(routes.on("databases:import"))
        with mock.patch.object(entitlements, "allowed", return_value=False) as allowed:
            self.assertFalse(routes.on("databases:import", user="u", ws="w"))
            allowed.assert_called_once_with("dbimport", user="u", ws="w")
            self.assertTrue(routes.on("databases:dashboard"))

    def test_template_tag_uses_the_request_user(self):
        from types import SimpleNamespace
        from unittest import mock

        from kernel.templatetags.pk import route_on

        ctx = {"request": SimpleNamespace(user="alice")}
        with mock.patch("kernel.routes.on", return_value=False) as on:
            self.assertFalse(route_on(ctx, "databases:import", "ws"))
            on.assert_called_once_with("databases:import", user="alice", ws="ws")
        self.assertTrue(route_on({}, "nope:none"))
