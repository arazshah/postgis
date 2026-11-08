"""پایش خودکار: سهمیه، زمان‌بندی، ارسال به دروازه، مقایسه با تصویر قبلی و اعلان هشدار؛ و اجرای واقعی روی PostGIS."""
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases.models import Member
from notifications.models import Notification
from satellite import client, monitor_service, services
from satellite.models import SatAnalysis, SatMonitor
from satellite.tests.test_analysis import BBOX, FEATS, _Base


class DetectTests(TestCase):
    def test_drop_threshold_sorting_and_bad_values(self):
        pairs = [("A", 0.4, 0.5), ("B", 0.2, 0.5), ("C", 0.6, 0.5), ("D", None, 0.5), ("E", 0.1, 0.0), ("F", 0.1, -0.2)]
        out = monitor_service.detect_drops(pairs, 20)
        self.assertEqual([d["id"] for d in out], ["B", "A"])          # C بالا رفته، D خالی، E و F مبنای نامعتبر
        self.assertEqual(out[0]["drop"], 60)
        self.assertEqual(monitor_service.detect_drops(pairs, 50)[0]["id"], "B")
        self.assertEqual(len(monitor_service.detect_drops(pairs, 50)), 1)


class MonitorBase(_Base):
    DATA = dict(layer="parcels", id_column="id", index="ndvi", mission="sentinel2", every_days=7, drop_pct=20)

    def setUp(self):
        super().setUp()
        self.free.sat_monitors = 1
        self.free.save()


class CreateTests(MonitorBase):
    def test_create_ok_with_table_name(self):
        m = monitor_service.create(self.db, self.user, self.DATA)
        self.assertEqual((m.table_name, m.every_days, m.enabled), ("mon_ndvi_parcels", 7, True))
        self.assertIn("پایش", m.name)

    def test_limit_plan_without_service_and_duplicates(self):
        monitor_service.create(self.db, self.user, self.DATA)
        with self.assertRaises(services.SatError) as cm:
            monitor_service.create(self.db, self.user, {**self.DATA, "index": "ndwi"})
        self.assertEqual(cm.exception.code, "limit")
        self.assertIn("سقف", str(cm.exception))
        self.free.sat_monitors = 0
        self.free.save()
        with self.assertRaises(services.SatError) as cm:
            monitor_service.create(self.db, self.user, self.DATA)
        self.assertEqual(cm.exception.code, "no_service")

    def test_existing_table_and_bad_params_and_area(self):
        with mock.patch("satellite.zonal_service._exists", return_value=True), self.assertRaises(services.SatError) as cm:
            monitor_service.create(self.db, self.user, self.DATA)
        self.assertEqual(cm.exception.code, "exists")
        for bad in ({"index": "x"}, {"mission": "x"}, {"every_days": 3}, {"drop_pct": 1}, {"layer": ""}):
            with self.assertRaises(services.SatError, msg=str(bad)):
                monitor_service.create(self.db, self.user, {**self.DATA, **bad})
        with mock.patch("satellite.zonal_service.read_features", return_value=(FEATS, BBOX, 999.0)), \
                self.assertRaises(services.SatError) as cm:
            monitor_service.create(self.db, self.user, self.DATA)
        self.assertEqual(cm.exception.code, "area")


class ScheduleTests(MonitorBase):
    def mon(self, **kw):
        vals = dict(database=self.db, user=self.user, name="m", layer="parcels", id_column="id", table_name="mon_ndvi_parcels")
        vals.update(kw)
        return SatMonitor.objects.create(**vals)

    def test_due_rules(self):
        now = timezone.now()
        m = self.mon()
        self.assertTrue(monitor_service.due(m, now))                      # هرگز اجرا نشده
        m.last_run_at = now - timedelta(days=3)
        self.assertFalse(monitor_service.due(m, now))
        m.last_run_at = now - timedelta(days=8)
        self.assertTrue(monitor_service.due(m, now))
        m.enabled = False
        self.assertFalse(monitor_service.due(m, now))
        m.enabled = True
        self.free.sat_monitors = 0                                         # پلن بعداً پایین‌تر آمد
        self.free.save()
        m.database.plan.refresh_from_db()
        self.assertFalse(monitor_service.due(m, now))

    @mock.patch("satellite.client.call", return_value={})
    def test_start_run_window_and_no_credit(self, call):
        m = self.mon()
        an = monitor_service.start_run(m)
        body = call.call_args.args[2]
        today = timezone.localdate()
        self.assertEqual(body["end"], today.isoformat())
        self.assertEqual(body["start"], (today - timedelta(days=60)).isoformat())     # اولین اجرا: ۶۰ روز
        self.assertEqual((an.monitor_id, an.charged), (m.pk, False))
        self.assertTrue(body["mask"])
        # اجرای دوم از روز بعد از آخرین تصویر شروع می‌شود و تا پایان دور قبلی دوباره زمان‌بندی نمی‌شود
        SatAnalysis.objects.update(status=SatAnalysis.Status.READY)
        m.last_scene_date = today - timedelta(days=5)
        monitor_service.start_run(m)
        self.assertEqual(call.call_args.args[2]["start"], (today - timedelta(days=4)).isoformat())
        self.assertEqual(zonal_credits_used(self.db), 0)

    @mock.patch("satellite.client.call", side_effect=client.GatewayError("قطع"))
    def test_gateway_down_retries_in_hours_not_days(self, _):
        now = timezone.now()
        m = self.mon()
        monitor_service.start_run(m, now)
        m.refresh_from_db()
        self.assertIn("دروازه", m.last_message)
        self.assertFalse(monitor_service.due(m, now + timedelta(hours=1)))
        self.assertTrue(monitor_service.due(m, now + timedelta(hours=7)))

    @mock.patch("satellite.client.call", return_value={})
    def test_run_due_caps_starts_and_skips_running(self, _):
        for i in range(5):
            self.mon(name=f"m{i}", table_name=f"mon_t{i}")
        self.assertEqual(monitor_service.run_due(), monitor_service.MAX_STARTS_PER_TICK)
        self.assertEqual(monitor_service.run_due(), 2)                    # آن سه تا در جریان‌اند
        self.assertEqual(monitor_service.run_due(), 0)

    def test_failed_run_is_quiet(self):
        m = self.mon()
        an = SatAnalysis.objects.create(database=self.db, user=self.user, name=m.table_name, layer="parcels", id_column="id",
                                        monitor=m, charged=False)
        from satellite import zonal_service
        zonal_service._fail(an, "تصویری با این شرایط در بازه پیدا نشد.", refund=False)
        m.refresh_from_db()
        self.assertIn("پیدا نشد", m.last_message)
        self.assertEqual(Notification.objects.count(), 0)


def zonal_credits_used(db):
    from satellite import zonal_service
    return zonal_service.credits(db)["used"]


class AfterRunTests(MonitorBase):
    def setUp(self):
        super().setUp()
        self.m = SatMonitor.objects.create(database=self.db, user=self.user, name="پایش باغ", layer="parcels", id_column="id",
                                           table_name="mon_ndvi_parcels", drop_pct=20)
        self.an = SatAnalysis.objects.create(database=self.db, user=self.user, name=self.m.table_name, layer="parcels",
                                             id_column="id", monitor=self.m, charged=False)
        self.rows = [{"feature": "A", "date": "2026-10-20"}]

    def test_alert_notifies_owner_once_with_link(self):
        with mock.patch("satellite.monitor_service._pairs", return_value=[("A", 0.3, 0.5), ("B", 0.5, 0.5)]) as pairs:
            monitor_service.after_run(self.an, self.rows)
        self.assertIsNone(pairs.call_args.args[1])                         # اولین بار: بدون محدودیت تاریخ
        n = Notification.objects.get()
        self.assertEqual((n.user, n.level), (self.user, Notification.Level.WARNING))
        self.assertIn("A", n.body)
        self.assertNotIn("B", n.body)
        self.assertTrue(n.url.endswith("/mon_ndvi_parcels/") or "mon_ndvi_parcels" in n.url)
        self.m.refresh_from_db()
        self.assertEqual(str(self.m.last_scene_date), "2026-10-20")
        self.assertIsNotNone(self.m.last_alert_at)
        # دور بعد فقط تصویرهای بعد از این تاریخ را برای هشدار می‌شمارد
        with mock.patch("satellite.monitor_service._pairs", return_value=[]) as pairs:
            monitor_service.after_run(self.an, [{"feature": "A", "date": "2026-10-27"}])
        self.assertEqual(str(pairs.call_args.args[1]), "2026-10-20")
        self.assertEqual(Notification.objects.count(), 1)
        self.m.refresh_from_db()
        self.assertIn("افت محسوسی نبود", self.m.last_message)

    def test_no_rows_no_alert_and_query_failure_never_blocks(self):
        monitor_service.after_run(self.an, [])
        self.m.refresh_from_db()
        self.assertIn("پیدا نشد", self.m.last_message)
        with mock.patch("satellite.monitor_service._pairs", side_effect=RuntimeError("db")):
            monitor_service.after_run(self.an, self.rows)
        self.m.refresh_from_db()
        self.assertEqual(str(self.m.last_scene_date), "2026-10-20")
        self.assertEqual(Notification.objects.count(), 0)


class MonitorViewTests(MonitorBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def u(self, name, *a):
        return reverse(f"satellite:{name}", args=[self.db.pk, *a])

    def test_create_endpoint_and_page_section(self):
        r = self.client.post(self.u("mon_create"), json.dumps(MonitorBase.DATA), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        r = self.client.post(self.u("mon_create"), json.dumps({**MonitorBase.DATA, "index": "ndwi"}), content_type="application/json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("سقف", r.json()["error"])
        html = self.client.get(self.u("index")).content.decode()
        for needle in ("پایش خودکار", "mon_ndvi_parcels", 'id="mon-dlg"', "satellite-monitor.js", "هفتگی"):
            self.assertIn(needle, html)

    def test_runs_hidden_from_analysis_list_and_actions(self):
        m = SatMonitor.objects.create(database=self.db, user=self.user, name="p", layer="parcels", id_column="id", table_name="mon_t1")
        SatAnalysis.objects.create(database=self.db, user=self.user, name="mon_t1", layer="parcels", id_column="id", monitor=m,
                                   charged=False, status=SatAnalysis.Status.READY)
        self.assertNotContains(self.client.get(self.u("an_cards")), "mon_t1")
        self.client.post(self.u("mon_action", m.pk, "toggle"))
        m.refresh_from_db()
        self.assertFalse(m.enabled)
        with mock.patch("satellite.client.call", return_value={}):
            self.client.post(self.u("mon_action", m.pk, "run"))
            self.client.post(self.u("mon_action", m.pk, "run"))               # دوم: در جریان است
        self.assertEqual(m.runs.filter(status=SatAnalysis.Status.PROCESSING).count(), 1)
        self.assertEqual(self.client.post(self.u("mon_action", m.pk, "bogus")).status_code, 404)
        self.client.post(self.u("mon_action", m.pk, "delete"))
        self.assertFalse(SatMonitor.objects.filter(pk=m.pk).exists())

    def test_viewer_and_stranger_cannot_change(self):
        m = SatMonitor.objects.create(database=self.db, user=self.user, name="p", layer="parcels", id_column="id", table_name="mon_t1")
        other = User.objects.create_user("09120000093")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.u("mon_action", m.pk, "delete")).status_code, 404)
        Member.objects.create(database=self.db, user=other, role=Member.Role.VIEWER)
        self.assertEqual(self.client.post(self.u("mon_action", m.pk, "delete")).status_code, 404)
        self.assertEqual(self.client.post(self.u("mon_create"), json.dumps(MonitorBase.DATA), content_type="application/json").status_code, 404)
        self.assertTrue(SatMonitor.objects.filter(pk=m.pk).exists())
