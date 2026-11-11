"""صفحه‌ی خانه از سهم پلاگین‌ها: ترتیب ردیف‌ها، گام‌ها، زمینه و جداسازی خطا."""
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from kernel import home
from kernel.plugins import registry

NOW = timezone.now()


def feed_a(user, dbs):
    return [{"when": NOW - timedelta(hours=1), "text": "a"}]


def feed_b(user, dbs):
    return [{"when": NOW, "text": "b"}, {"when": NOW - timedelta(hours=5), "text": "b2"}]


def feed_bad(user, dbs):
    raise RuntimeError("x")


def step_none(user, dbs, target):
    return None


def step_ok(user, dbs, target):
    return {"label": "گام", "done": True}


def ctx_a(request, dbs):
    return {"x": 1}


class HomeCollectTests(SimpleTestCase):
    def setUp(self):
        self.saved = {p: dict(registry._points.get(p, {})) for p in (home.FEED, home.STEP, home.CONTEXT)}
        for p in self.saved:
            registry._points[p] = {}
        self.addCleanup(lambda: [registry._points.__setitem__(p, v) for p, v in self.saved.items()])

    def test_feed_is_merged_sorted_newest_first_and_limited(self):
        for fn, o in (("feed_a", 1), ("feed_bad", 2), ("feed_b", 3)):
            home.feed(f"kernel.tests.test_home.{fn}", plugin="kernel", order=o)
        with self.assertLogs("kernel.home", "ERROR"):
            rows = home.collect_feed(None, [object()], limit=2)
        self.assertEqual([r["text"] for r in rows], ["b", "a"])

    def test_feed_is_skipped_without_workspaces(self):
        home.feed("kernel.tests.test_home.feed_a", plugin="kernel")
        self.assertEqual(home.collect_feed(None, []), [])

    def test_steps_skip_none_and_context_merges(self):
        home.step("kernel.tests.test_home.step_none", plugin="kernel", order=1)
        home.step("kernel.tests.test_home.step_ok", plugin="kernel", order=2)
        home.context("kernel.tests.test_home.ctx_a", plugin="kernel")
        self.assertEqual(home.collect_steps(None, [], None), [{"label": "گام", "done": True}])
        self.assertEqual(home.collect_context(SimpleNamespace(), []), {"x": 1})

    def test_broken_paths_reported(self):
        home.feed("no.such.fn", plugin="kernel")
        self.assertEqual(len(home.broken_paths()), 1)


class InstalledHomeTests(SimpleTestCase):
    def test_every_plugin_contribution_loads_and_steps_keep_the_old_order(self):
        self.assertEqual(home.broken_paths(), [])
        order = [c.value.rsplit(".", 1)[1] for c in registry.contributions(home.STEP)]
        self.assertEqual(order, ["step_profile", "step_create", "step_import", "step_map", "step_llm"])
        self.assertEqual({c.plugin for c in registry.contributions(home.FEED)}, {"analysis", "tools", "maps", "databases"})
