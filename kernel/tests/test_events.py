"""گذرگاه رویداد: شنونده‌ها، جداسازی خطا و پاک‌سازی انتشار هنگام حذف پایگاه."""
from unittest import mock

from django.test import SimpleTestCase

from databases import services
from databases.tests.test_services import BaseCase
from kernel import events
from kernel.plugins import registry

CALLS = []


def good(**kw):
    CALLS.append(("good", kw))


def bad(**kw):
    raise RuntimeError("x")


class EmitTests(SimpleTestCase):
    def setUp(self):
        CALLS.clear()
        saved = dict(registry._points.get(events.POINT, {}))
        self.addCleanup(lambda: registry._points.__setitem__(events.POINT, saved))
        registry._points[events.POINT] = {}

    def test_listeners_run_in_order_and_failures_are_isolated(self):
        events.listen("t.event", "kernel.tests.test_events.bad", plugin="kernel", order=1)
        events.listen("t.event", "kernel.tests.test_events.good", plugin="kernel", order=2)
        events.listen("other.event", "kernel.tests.test_events.good", plugin="kernel")
        with self.assertLogs("kernel.events", "ERROR"):
            self.assertEqual(events.emit("t.event", a=1), 1)
        self.assertEqual(CALLS, [("good", {"a": 1})])
        self.assertEqual(events.emit("nobody.listens"), 0)

    def test_broken_listener_path_is_reported(self):
        events.listen("t.event", "no.such.module.fn", plugin="kernel")
        self.assertEqual(len(events.broken_paths()), 1)


class WorkspaceDeletedTests(BaseCase):
    def test_delete_emits_event_and_publish_cleans_its_files(self):
        from publish.models import Service

        db = services.create_database(self.user, "evdb", "Abcdefgh123", ["postgis"])
        svc = Service.objects.create(database=db, ows_password_encrypted="secret-token")
        with mock.patch("publish.ows.remove_service_files") as remove:
            services.delete_database(db, actor=self.user)
        remove.assert_called_once()
        svc.refresh_from_db()
        self.assertEqual(svc.ows_password_encrypted, "")

    def test_a_failing_listener_does_not_stop_the_delete(self):
        db = services.create_database(self.user, "evdb2", "Abcdefgh123", ["postgis"])
        with mock.patch("publish.events.workspace_deleted", side_effect=RuntimeError("x")), \
                self.assertLogs("kernel.events", "ERROR"):
            services.delete_database(db, actor=self.user)
        db.refresh_from_db()
        self.assertEqual(db.status, db.Status.DELETED)


class ReportSheetsTests(SimpleTestCase):
    def test_a_failing_sheet_does_not_stop_the_others(self):
        from kernel import admin as dash

        wrote = []
        registry.add(dash.SHEET, "kernel.tests.test_events.sheet_bad", "kernel.tests.test_events.sheet_bad", plugin="kernel", order=-2)
        registry.add(dash.SHEET, "kernel.tests.test_events.sheet_ok", "kernel.tests.test_events.sheet_ok", plugin="kernel", order=-1)
        SHEETS.append(wrote)
        try:
            with self.assertLogs("kernel.admin", "ERROR"):
                dash.run_sheets("book", None)
        finally:
            registry._points[dash.SHEET].pop("kernel.tests.test_events.sheet_bad")
            registry._points[dash.SHEET].pop("kernel.tests.test_events.sheet_ok")
            SHEETS.clear()
        self.assertEqual(wrote, ["book"])

    def test_installed_sheet_order_matches_the_old_workbook(self):
        from kernel import admin as dash

        order = [c.plugin for c in registry.contributions(dash.SHEET)]
        self.assertEqual(order, ["analysis", "maps", "publish", "billing", "support", "classroom", "survey"])
        self.assertEqual(dash.broken_paths(), [])


SHEETS: list = []


def sheet_bad(book, since):
    raise RuntimeError("x")


def sheet_ok(book, since):
    SHEETS[0].append(book)
