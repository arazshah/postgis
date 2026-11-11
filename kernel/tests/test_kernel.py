"""هسته‌ی پلاگین: رجیستری، کشف، نوع کار، ناوبری و بررسی‌های سیستم."""
from django.apps import apps
from django.core.checks import run_checks
from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

from jobs.models import Job
from kernel import jobs, nav
from kernel.plugins import PluginError, Registry, registry


class RegistryTests(SimpleTestCase):
    def test_register_validates_id_kind_and_api(self):
        r = Registry()
        p = r.register("demo", "نمونه", requires=["databases"])
        self.assertEqual((p.kind, p.requires), ("feature", ("databases",)))
        for bad in ({"id": "Bad-Id"}, {"kind": "other"}, {"api": 99}):
            with self.assertRaises(PluginError):
                r.register(**{"id": "x1", "name": "x", **bad})
        r.register("demo", "نمونه", requires=["databases"])  # ثبت دوباره‌ی یکسان بی‌اثر است
        with self.assertRaises(PluginError):
            r.register("demo", "نام دیگر")

    def test_contributions_are_ordered_and_conflicts_are_rejected(self):
        r = Registry()
        r.add("p", "b", 2, plugin="one", order=20)
        r.add("p", "a", 1, plugin="one", order=10)
        r.add("p", "c", 3, plugin="two", order=20)
        self.assertEqual(r.values("p"), [1, 2, 3])
        self.assertEqual(r.get("p", "a"), 1)
        self.assertIsNone(r.get("p", "zz"))
        with self.assertRaises(PluginError):
            r.add("p", "a", 9, plugin="two")
        r.add("p", "a", 9, plugin="two", replace=True)
        self.assertEqual(r.get("p", "a"), 9)

    def test_missing_requirements(self):
        r = Registry()
        r.register("a1", "الف", requires=["nope"])
        self.assertEqual(r.missing_requirements(), [("a1", "nope")])


class InstalledPluginsTests(SimpleTestCase):
    def test_every_project_app_declares_a_plugin_and_loads_cleanly(self):
        self.assertEqual(registry.errors, {})
        mine = {c.name for c in apps.get_app_configs() if not c.name.startswith("django.")} - {"kernel"}
        self.assertEqual(mine, set(registry.plugins))
        self.assertEqual(registry.missing_requirements(), [])
        self.assertEqual([e for e in run_checks() if e.id.startswith("kernel.")], [])

    def test_every_job_kind_has_a_handler_and_a_reversible_destination(self):
        self.assertEqual({k.kind for k in jobs.kinds()}, set(Job.Kind.values))
        for k in jobs.kinds():
            self.assertTrue(callable(jobs.handler_for(k.kind)), k.kind)
            self.assertEqual(k.label, Job.Kind(k.kind).label)
            if k.destination:
                reverse(k.destination, args=[1])
        self.assertEqual(jobs.broken_handlers(), [])
        with self.assertRaises(LookupError):
            jobs.handler_for("nope")

    def test_nav_contributions_point_to_real_urls_and_known_groups(self):
        groups = {g.key for g, _ in nav.ws_groups()}
        for _g, items in nav.ws_groups():
            for s in items:
                self.assertIn(s.group, groups)
                self.assertIn(s.need, ("viewer", "editor", "owner"))
                self.assertIn(s.plugin, registry.plugins)
                reverse(s.url, args=[1])
        for _g, items in nav.home_groups():
            for a in items:
                reverse(a.url, args=[1])
        for q in nav.admin_quicks():
            try:
                reverse(q.url)
            except NoReverseMatch:
                self.fail(q.url)
        self.assertEqual(nav.broken_paths(), [])

    def test_ticks_isolate_failures(self):
        r = registry
        r.add(jobs.TICK, "zz_boom", "kernel.tests.test_kernel.boom", plugin="kernel", order=1)
        r.add(jobs.TICK, "zz_ok", "kernel.tests.test_kernel.fine", plugin="kernel", order=2)
        try:
            only = {c.key: c for c in r.contributions(jobs.TICK) if c.key.startswith("zz_")}
            saved = r._points[jobs.TICK]
            r._points[jobs.TICK] = only
            with self.assertLogs("kernel.jobs", "ERROR"):
                out = jobs.run_ticks()
        finally:
            r._points[jobs.TICK] = {k: v for k, v in saved.items() if not k.startswith("zz_")}
        self.assertEqual(out["zz_ok"], 7)
        self.assertIn("خطا", out["zz_boom"])


def boom(now=None):
    raise RuntimeError("x")


def fine(now=None):
    return 7
