"""هشدار دوره‌ای handler سطح ۲: بسته، زمان‌بندی، ارسال، جلوگیری از تکرار و خطا."""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from kernel import alerts, entitlements, handlers
from kernel.models import Entitlement, PluginAlertState, PluginState
from kernel.plugins import registry
from kernel.tests.test_tier2 import MANIFEST, build, failed, files  # noqa: F401

CODE = '''def handle(ctx, p):
    r = ctx.sql("select count(*) from t")
    if r["rows"][0][0] > 5:
        return {"alerts": [{"title": "تعداد زیاد", "body": "بیش از ۵ مورد"}]}
    return {"alerts": []}
'''
ALERT_MANIFEST = MANIFEST + '[[contributes.alerts]]\nhandler = "stats"\nevery_minutes = 15\n'


class AlertPackageTests(TestCase):
    def test_valid_alert_is_parsed(self):
        ins, bad = failed(build(files(**{"plugin.toml": ALERT_MANIFEST})))
        self.assertIsNone(bad, ins.report())
        self.assertEqual(ins.alerts, [("stats", 15)])

    def test_alert_rules(self):
        cases = {"handler = \"ghost\"\nevery_minutes = 15": "ghost", "handler = \"stats\"\nevery_minutes = 1": "every_minutes",
                 "handler = \"stats\"\nevery_minutes = 99999": "every_minutes", "handler = \"stats\"\nevery_minutes = \"15\"": "every_minutes"}
        for body, needle in cases.items():
            with self.subTest(body=body):
                _i, bad = failed(build(files(**{"plugin.toml": MANIFEST + "[[contributes.alerts]]\n" + body + "\n"})))
                self.assertEqual(bad.stage, "هشدارهای دوره‌ای")
                self.assertIn(needle, bad.detail)
        dup = ALERT_MANIFEST + '[[contributes.alerts]]\nhandler = "stats"\nevery_minutes = 20\n'
        self.assertIn("تکراری", failed(build(files(**{"plugin.toml": dup})))[1].detail)


class AlertTickTests(TestCase):
    def setUp(self):
        registry.register("compute", "محاسبه", kind="custom")
        self.addCleanup(registry.remove_plugin, "compute")
        self.addCleanup(entitlements.invalidate)
        handlers.register("compute", "stats", CODE)
        alerts.register("compute", "stats", 15)
        st = PluginState.objects.create(plugin_id="compute", access="restricted")
        Entitlement.objects.create(state=st, kind="workspace", subject="7")
        Entitlement.objects.create(state=st, kind="workspace", subject="8", expires_at=timezone.now() - datetime.timedelta(days=1))
        Entitlement.objects.create(state=st, kind="user", subject="1")  # کاربر/همه شمرده نمی‌شود
        entitlements.invalidate()
        self.owner = mock.Mock()
        self.ws = mock.Mock(pk=7, is_live=True, owner=self.owner)
        self.rows = [[9]]
        for target, val in (("kernel.workspace.peek", lambda pk: self.ws if pk == 7 else None),
                            ("kernel.pagekit.read_select", lambda ws, q, a=None: {"columns": ["n"], "rows": self.rows})):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        n = mock.patch("kernel.workspace.notify_user")
        self.notify = n.start()
        self.addCleanup(n.stop)

    def now(self, minutes=0):
        return timezone.now() + datetime.timedelta(minutes=minutes)

    def test_only_valid_workspace_grants_run_and_owner_is_notified(self):
        out = alerts.tick(self.now())
        self.assertEqual(out, {"ran": 1, "sent": 1})
        self.notify.assert_called_once_with(self.owner, "تعداد زیاد", "بیش از ۵ مورد")
        self.assertEqual(list(PluginAlertState.objects.values_list("workspace_id", flat=True)), [7])

    def test_interval_and_resend_suppression(self):
        t = self.now()
        alerts.tick(t)
        self.assertEqual(alerts.tick(t + datetime.timedelta(minutes=5))["ran"], 0)  # هنوز زود است
        self.assertEqual(alerts.tick(t + datetime.timedelta(minutes=16)), {"ran": 1, "sent": 0})  # همان نتیجه
        self.assertEqual(self.notify.call_count, 1)
        self.assertEqual(alerts.tick(t + datetime.timedelta(hours=25))["sent"], 1)  # پس از ۲۴ ساعت دوباره

    def test_recovery_resets_so_next_problem_is_sent(self):
        t = self.now()
        alerts.tick(t)
        self.rows = [[1]]
        alerts.tick(t + datetime.timedelta(minutes=16))
        self.rows = [[9]]
        self.assertEqual(alerts.tick(t + datetime.timedelta(minutes=40))["sent"], 1)
        self.assertEqual(self.notify.call_count, 2)

    def test_errors_are_recorded_and_isolated(self):
        handlers.register("compute", "stats", "def handle(c, p):\n    return 1/0")
        out = alerts.tick(self.now())
        self.assertEqual(out, {"ran": 1, "sent": 0})
        self.assertIn("ZeroDivisionError", PluginAlertState.objects.get().last_error)
        self.notify.assert_not_called()

    def test_disabled_plugin_and_dead_workspace_skip(self):
        PluginState.objects.filter(plugin_id="compute").update(enabled=False)
        entitlements.invalidate()
        self.assertEqual(alerts.tick(self.now())["ran"], 0)
        PluginState.objects.filter(plugin_id="compute").update(enabled=True)
        entitlements.invalidate()
        self.ws.is_live = False
        self.assertEqual(alerts.tick(self.now())["ran"], 0)

    def test_per_tick_cap_and_alert_cleaning(self):
        with mock.patch.object(alerts, "MAX_RUNS_PER_TICK", 0):
            self.assertTrue(alerts.tick(self.now())["capped"])
        self.assertEqual(alerts._clean([{"title": "a"}, {"title": " "}, "x", {"title": "b", "body": "c" * 999}, {"title": "c"}, {"title": "d"}])[1][1], "c" * 400)
        self.assertEqual(len(alerts._clean([{"title": str(i)} for i in range(9)])), 3)
        self.assertEqual(alerts._clean("bad"), [])

    def test_tick_is_registered_with_the_worker(self):
        from kernel import jobs

        self.assertEqual(registry.get(jobs.TICK, "plugin_alerts"), "kernel.alerts.tick")
