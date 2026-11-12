"""کانال‌های هشدار: پیوند حساب، ارسال، تکرار، سقف نرخ، ساعت سکوت، پشتیبان و امنیت توکن."""
import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from kernel import crypto, notify
from kernel.models import NotifyAddress, NotifyChannel, NotifyLog, NotifyPref

U = get_user_model()
TOKEN = "123:SECRET-TOKEN"
REAL_HTTP = notify._http


def ok(result=None):
    return {"ok": True, "result": result if result is not None else {}}


class NotifyTests(TestCase):
    def setUp(self):
        self.user = U.objects.create_user(username="u1", phone="09120000001", password="x")
        self.ch = notify.save_channel("bale", enabled=True, token=TOKEN, bot_username="geobot")
        self.calls = []

        def fake(url, payload):
            self.calls.append((url, payload))
            if url.endswith("/getUpdates"):
                return ok(self.updates)
            return ok()
        self.updates = []
        p = mock.patch.object(notify, "_http", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)

    def link(self, chat="777"):
        info = notify.begin_link(self.user, "bale")
        self.updates = [{"update_id": 5, "message": {"text": f"/start {info['code']}", "chat": {"id": chat, "type": "private"}}}]
        return info

    def test_token_encrypted_and_hidden(self):
        self.ch.refresh_from_db()
        self.assertNotIn("SECRET", self.ch.token_enc)
        self.assertEqual(crypto.decrypt(self.ch.token_enc), TOKEN)
        self.assertEqual(self.ch.token_hint, "OKEN")
        notify.save_channel("bale", enabled=True, token="", bot_username="geobot")  # خالی = بدون تغییر
        self.ch.refresh_from_db()
        self.assertEqual(crypto.decrypt(self.ch.token_enc), TOKEN)

    def test_enable_needs_token(self):
        self.assertFalse(notify.save_channel("telegram", enabled=True).enabled)

    def test_link_flow_and_one_time_code(self):
        info = self.link()
        self.assertIn("geobot", info["url"])
        a = NotifyAddress.objects.get(user=self.user)
        self.assertNotEqual(a.code_hash, info["code"])  # فقط هش
        self.assertEqual(notify.poll()["linked"], 1)
        a.refresh_from_db()
        self.assertEqual(a.chat_id, "777")
        self.assertEqual(a.code_hash, "")
        self.assertEqual(notify.poll()["linked"], 0)  # پیوندی در انتظار نیست؛ poll نمی‌کند

    def test_poll_skipped_without_pending(self):
        notify.poll()
        self.assertEqual(self.calls, [])

    def test_wrong_or_expired_code_and_groups(self):
        self.link()
        self.updates = [{"update_id": 1, "message": {"text": "/start ABCDEF12", "chat": {"id": 9, "type": "private"}}}]
        self.assertEqual(notify.poll()["linked"], 0)
        info = notify.begin_link(self.user, "bale")
        self.updates = [{"update_id": 2, "message": {"text": f"/start {info['code']}", "chat": {"id": 9, "type": "group"}}}]
        self.assertEqual(notify.poll()["linked"], 0)  # گروه پذیرفته نمی‌شود
        NotifyAddress.objects.update(code_expires=timezone.now() - datetime.timedelta(minutes=1))
        self.updates = [{"update_id": 3, "message": {"text": f"/start {info['code']}", "chat": {"id": 9, "type": "private"}}}]
        notify.poll()
        self.assertFalse(NotifyAddress.objects.exists())  # منقضی پاک شد

    def test_deliver_to_messenger_only(self):
        self.link()
        notify.poll()
        self.calls.clear()
        with mock.patch("kernel.workspace.notify_user") as sms:
            r = notify.deliver(self.user, "افت آب", "چاه ۳")
        self.assertEqual(r["sent"], ["bale"])
        self.assertFalse(r["fallback"])
        sms.assert_not_called()
        url, payload = self.calls[-1]
        self.assertIn("/sendMessage", url)
        self.assertEqual(payload["chat_id"], "777")
        self.assertNotIn("parse_mode", payload)

    def test_fallback_when_no_messenger(self):
        with mock.patch("kernel.workspace.notify_user") as sms:
            r = notify.deliver(self.user, "a", "b")
        self.assertTrue(r["fallback"])
        sms.assert_called_once()

    def test_fallback_off_by_pref_and_critical_both(self):
        NotifyPref.objects.create(user=self.user, fallback=False)
        with mock.patch("kernel.workspace.notify_user") as sms:
            notify.deliver(self.user, "a", "b")
            sms.assert_not_called()
        NotifyPref.objects.update(fallback=True)
        self.link()
        notify.poll()
        with mock.patch("kernel.workspace.notify_user") as sms:
            r = notify.deliver(self.user, "a", "b", severity="critical")
        self.assertEqual(r["sent"], ["bale"])
        sms.assert_called_once()

    def test_send_failure_falls_back_and_hides_token(self):
        self.link()
        notify.poll()
        self.calls.clear()
        with mock.patch.object(notify, "_http", side_effect=notify.NotifyError("اتصال")), mock.patch("kernel.workspace.notify_user") as sms:
            r = notify.deliver(self.user, "a", "b")
        self.assertTrue(r["fallback"])
        sms.assert_called_once()
        self.assertFalse(NotifyLog.objects.filter(ok=False, channel="bale").exclude(error="اتصال").exists())

    def test_http_error_never_leaks_token(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(f"x https://h/bot{TOKEN}/y")):
            with self.assertRaises(notify.NotifyError) as cm:
                REAL_HTTP(f"https://h/bot{TOKEN}/m", {})
        self.assertNotIn("SECRET", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)

    def test_dedupe_key_and_rate_limit(self):
        with mock.patch("kernel.workspace.notify_user"):
            self.assertEqual(notify.deliver(self.user, "a", "b", key="k1")["skipped"], "")
            self.assertEqual(notify.deliver(self.user, "a", "b", key="k1")["skipped"], "dup")
            for i in range(notify.RATE_PER_HOUR):
                NotifyLog.objects.create(user=self.user, channel="bale", key=f"x{i}")
            self.assertEqual(notify.deliver(self.user, "a", "b", key="new")["skipped"], "rate")
            self.assertEqual(notify.deliver(self.user, "a", "b", key="crit", severity="critical")["skipped"], "")

    def test_quiet_hours_silent_and_no_sms(self):
        self.link()
        notify.poll()
        self.calls.clear()
        now = timezone.now()
        h = timezone.localtime(now).hour
        NotifyPref.objects.create(user=self.user, quiet_from=h, quiet_to=(h + 2) % 24)
        with mock.patch("kernel.workspace.notify_user") as sms:
            notify.deliver(self.user, "a", "b", now=now)
            self.assertTrue(self.calls[-1][1]["disable_notification"])
            sms.assert_not_called()
            notify.deliver(self.user, "a", "b", severity="critical", now=now)
            self.assertFalse(self.calls[-1][1]["disable_notification"])

    def test_text_truncated(self):
        self.link()
        notify.poll()
        with mock.patch("kernel.workspace.notify_user"):
            notify.deliver(self.user, "s", "x" * 5000)
        self.assertLessEqual(len(self.calls[-1][1]["text"]), notify.MAX_TEXT)

    def test_relay_base_used_for_telegram(self):
        notify.save_channel("telegram", enabled=True, token="9:T", api_base="https://relay.example.org/tg")
        ch = NotifyChannel.objects.get(key="telegram")
        notify._call(ch, "getMe", {})
        self.assertTrue(self.calls[-1][0].startswith("https://relay.example.org/tg/bot9:T/"))

    def test_clean_base(self):
        for bad in ("ftp://x", "https://u:p@x", "https://x?a=1", "javascript:1"):
            with self.assertRaises(ValueError):
                notify.clean_base(bad)
        self.assertEqual(notify.clean_base("https://x.org/"), "https://x.org")

    def test_other_user_never_receives(self):
        other = U.objects.create_user(username="u2", phone="09120000002", password="x")
        self.link()
        notify.poll()
        self.calls.clear()
        with mock.patch("kernel.workspace.notify_user"):
            self.assertEqual(notify.deliver(other, "a", "b")["sent"], [])
        self.assertFalse([c for c in self.calls if "sendMessage" in c[0]])

    def test_tick_prunes_log(self):
        old = NotifyLog.objects.create(user=self.user, channel="bale")
        NotifyLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(days=40))
        notify.tick()
        self.assertFalse(NotifyLog.objects.exists())

    def test_alerts_use_notify_deliver(self):
        from kernel import alerts
        self.assertIn("notify", alerts.__dict__)


class NotifyAdminAndAlertTests(TestCase):
    def setUp(self):
        self.admin = U.objects.create_superuser(username="adm", phone="09120000100", password="x")
        self.client.force_login(self.admin)

    def test_panel_saves_encrypted_token_and_tests_connection(self):
        from django.urls import reverse
        with mock.patch.object(notify, "_http", return_value=ok({"username": "geobot"})):
            r = self.client.post(reverse("admin:kernel_notifychannel_add"), {
                "key": "bale", "enabled": "on", "bot_username": "", "api_base": "", "new_token": TOKEN})
            self.assertEqual(r.status_code, 302, getattr(r, "context_data", {}) and r.context_data["adminform"].form.errors)
            ch = NotifyChannel.objects.get(key="bale")
            self.assertTrue(ch.enabled)
            self.assertNotIn("SECRET", ch.token_enc)
            page = self.client.get(reverse("admin:kernel_notifychannel_changelist"))
            self.assertNotContains(page, "SECRET")
            self.assertEqual(notify.test_channel("bale")[0], True)
            ch.refresh_from_db()
            self.assertEqual(ch.bot_username, "geobot")

    def test_panel_rejects_bad_base(self):
        from django.urls import reverse
        r = self.client.post(reverse("admin:kernel_notifychannel_add"), {"key": "telegram", "enabled": "on", "api_base": "ftp://x", "new_token": "1:t"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(NotifyChannel.objects.exists())

    def test_alert_reaches_messenger_end_to_end(self):
        from kernel import alerts
        notify.save_channel("bale", enabled=True, token=TOKEN, bot_username="b")
        NotifyAddress.objects.create(user=self.admin, channel="bale", chat_id="55")
        sent = []
        with mock.patch.object(notify, "_http", side_effect=lambda url, p: sent.append((url, p)) or ok()), \
                mock.patch("kernel.workspace.notify_user") as sms:
            ws = mock.Mock(pk=1, owner=self.admin)
            state = mock.Mock(last_hash="", last_sent=None)
            with mock.patch.object(alerts, "_clean", return_value=[("آب کم", "چاه ۳")]), \
                    mock.patch("kernel.runner.client.execute", return_value={"alerts": []}), \
                    mock.patch("kernel.metering.record"):
                alerts.run_one(alerts.Alert("p", "h", 15), ws, state, timezone.now())
        self.assertEqual(sent[-1][1]["chat_id"], "55")
        self.assertIn("آب کم", sent[-1][1]["text"])
        sms.assert_not_called()
