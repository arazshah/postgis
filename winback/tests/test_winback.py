"""بازگشت کاربران: انتخاب، رضایت، سقف، کنترل، زمان بهینه، تأیید، ارسال، لینک، هدیه و اندازه‌گیری."""
import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import sms
from accounts.models import User
from analytics.models import Event, Visitor
from kernel import conf, entitlements
from winback import routes, services, timing
from winback.models import Batch, Message, Preference, Route

NOW = datetime.datetime(2026, 11, 14, 8, 0, tzinfo=datetime.UTC)  # شنبه ۱۱:۳۰ تهران


def mk_user(n, days_ago=5, **kw):
    u = User.objects.create_user(f"0912000{n:04d}", full_name="علی رضایی", **kw)
    User.objects.filter(pk=u.pk).update(phone_verified_at=NOW, date_joined=NOW - datetime.timedelta(days=days_ago))
    u.refresh_from_db()
    return u


class Base(TestCase):
    def setUp(self):
        conf.set_value("winback", "control_percent", 0)
        self.addCleanup(conf.clear, "winback", "control_percent")
        services.sync_routes()
        Route.objects.filter(key="no_database").update(enabled=True, template_id="123")


class TimingTests(Base):
    def test_default_is_eleven_and_never_friday_or_night(self):
        u = mk_user(1)
        t = timing.best_time(u, NOW)
        self.assertEqual(t.hour, 11)
        self.assertTrue(timing.in_window(t))
        fri = datetime.datetime(2026, 11, 13, 8, 0, tzinfo=datetime.UTC)  # جمعه
        self.assertNotEqual(timing.best_time(u, fri).astimezone(timing.TZ).weekday(), 4)
        self.assertFalse(timing.in_window(datetime.datetime(2026, 11, 14, 22, 0, tzinfo=datetime.UTC)))

    def test_learns_user_login_hour_within_window(self):
        u = mk_user(2)
        v = Visitor.objects.create(vid="v1", user=u)
        for d in range(4):  # ورود ساعت ۲۱ تهران؛ باید به ۱۹ کلمپ شود
            e = Event.objects.create(visitor=v, name=Event.LOGIN)
            Event.objects.filter(pk=e.pk).update(created_at=timezone.now().replace(hour=17, minute=30) - datetime.timedelta(days=d))
        self.assertEqual(timing.preferred_hour(u), (19, True))


class PlanTests(Base):
    def test_batch_for_users_without_database_and_caps(self):
        a = mk_user(1)
        mk_user(2, days_ago=1)  # خیلی تازه
        mk_user(3, days_ago=60)  # خیلی قدیمی
        Preference.objects.create(user=mk_user(4), marketing=False)  # لغو کرده
        made = services.plan_batches(NOW)
        self.assertEqual(len(made), 1)
        self.assertEqual(list(made[0].messages.values_list("user", flat=True)), [a.pk])
        self.assertEqual(services.plan_batches(NOW), [])  # در همان روز دوباره نمی‌سازد

    def test_needs_template_and_enabled(self):
        mk_user(1)
        Route.objects.update(template_id="")
        self.assertEqual(services.plan_batches(NOW), [])

    def test_control_group_gets_no_sms(self):
        conf.set_value("winback", "control_percent", 50)
        for i in range(1, 41):
            mk_user(i)
        b = services.plan_batches(NOW)[0]
        ctrl = b.messages.filter(status=Message.Status.CONTROL).count()
        self.assertTrue(5 < ctrl < 35)

    def test_weekly_cap(self):
        u = mk_user(1)
        b = Batch.objects.create(route=Route.objects.get(key="no_database"))
        Message.objects.create(batch=b, user=u, route_key="expired_plan", phone=u.phone, status="sent", sent_at=NOW - datetime.timedelta(days=3))
        self.assertEqual(services.plan_batches(NOW), [])


class SendTests(Base):
    def _approved(self):
        u = mk_user(1)
        batch = services.plan_batches(NOW)[0]
        admin = User.objects.create_user("09129999999")
        services.approve(batch, admin, NOW)
        return u, batch, batch.messages.get()

    def test_nothing_sent_before_approval_or_before_time(self):
        mk_user(1)
        batch = services.plan_batches(NOW)[0]
        with mock.patch.object(sms, "send_template") as send:
            services.send_due(NOW + datetime.timedelta(days=3))
            send.assert_not_called()
        admin = User.objects.create_user("09129999999")
        services.approve(batch, admin, NOW)
        m = batch.messages.get()
        self.assertEqual(m.status, Message.Status.SCHEDULED)
        self.assertTrue(timing.in_window(m.send_at))
        with mock.patch.object(sms, "send_template") as send:
            services.send_due(m.send_at - datetime.timedelta(minutes=1))
            send.assert_not_called()
            services.send_due(m.send_at)
            send.assert_called_once()
            args = send.call_args.args
            self.assertEqual(args[1], "123")
            self.assertIn("LINK", args[2])
            self.assertEqual(set(args[2]), {"NAME", "LINK", "STOP"})
            self.assertEqual(args[2]["LINK"], m.code)  # فقط کدِ انتهای لینک؛ دامنه در متن قالب است
            self.assertEqual(args[2]["STOP"], m.code)
        m.refresh_from_db()
        self.assertEqual(m.status, Message.Status.SENT)

    def test_user_who_returned_or_opted_out_is_skipped(self):
        u, batch, m = self._approved()
        User.objects.filter(pk=u.pk).update(last_login=timezone.now() + datetime.timedelta(hours=1))  # بعد از ساخت دسته (ساعت واقعی)
        with mock.patch.object(sms, "send_template") as send:
            services.send_due(m.send_at)
            send.assert_not_called()
        m.refresh_from_db()
        self.assertEqual((m.status, m.reason), ("skipped", "کاربر خودش برگشت"))

    def test_opt_out_cancels_pending(self):
        u, batch, m = self._approved()
        services.set_pref(u, False)
        m.refresh_from_db()
        self.assertEqual(m.status, Message.Status.SKIPPED)

    def test_failure_is_recorded_not_raised(self):
        u, batch, m = self._approved()
        with mock.patch.object(sms, "send_template", side_effect=sms.SMSError("boom")):
            self.assertEqual(services.send_due(m.send_at)["failed"], 1)
        m.refresh_from_db()
        self.assertEqual(m.status, Message.Status.FAILED)

    def test_master_switch_off_sends_nothing(self):
        mk_user(1)
        conf.clear("winback", "enabled")
        self.assertIn("خاموش", services.tick(NOW))
        self.assertFalse(Batch.objects.exists())

    def test_preview_matches_template(self):
        u, batch, m = self._approved()
        text = services.preview(m)
        self.assertIn("علی", text)
        self.assertNotIn("#", text)


class LinkTests(Base):
    def _sent(self):
        u = mk_user(1)
        batch = services.plan_batches(NOW)[0]
        m = batch.messages.get()
        m.status, m.send_at, m.sent_at = Message.Status.SENT, NOW, NOW
        m.save()
        return u, m

    def test_click_prefills_phone_and_goes_to_login_with_next(self):
        u, m = self._sent()
        r = self.client.get(reverse("winback:go", args=[m.code]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])
        self.assertIn("utm_source=sms", r["Location"])
        self.assertEqual(self.client.session["otp_phone"], u.phone)
        m.refresh_from_db()
        self.assertIsNotNone(m.clicked_at)
        self.assertFalse("_auth_user_id" in self.client.session)  # ورود خودکار نداریم

    def test_control_and_unknown_codes_404(self):
        u, m = self._sent()
        Message.objects.filter(pk=m.pk).update(status=Message.Status.CONTROL)
        self.assertEqual(self.client.get(reverse("winback:go", args=[m.code])).status_code, 404)
        self.assertEqual(self.client.get("/r/nope/").status_code, 404)

    def test_stop_get_is_safe_post_opts_out(self):
        u, m = self._sent()
        url = reverse("winback:stop", args=[m.code])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(services.wants(u))
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertFalse(services.wants(u))

    def test_trial_gift_once_on_click(self):
        from kernel.plugins import registry

        pid = next(p.id for p in registry.plugins.values() if p.kind != "system")
        Route.objects.filter(key="no_database").update(gift_kind="trial", gift_plugin=pid, gift_days=7)
        u, m = self._sent()
        self.addCleanup(entitlements.invalidate)
        self.client.get(reverse("winback:go", args=[m.code]))
        self.client.get(reverse("winback:go", args=[m.code]))
        self.assertEqual(m.__class__.objects.get(pk=m.pk).gift_at is not None, True)
        from kernel.models import Entitlement

        self.assertEqual(Entitlement.objects.filter(kind="user", subject=str(u.pk), source="trial").count(), 1)


class MeasureTests(Base):
    def test_return_and_uplift_against_control(self):
        b = Batch.objects.create(route=Route.objects.get(key="no_database"), status="approved")
        sent_at = NOW - datetime.timedelta(days=10)
        for i in range(1, 5):
            u = mk_user(i)
            returned = i <= 2  # ۲ از ۴ پیام‌گرفته برگشتند
            Message.objects.create(batch=b, user=u, route_key="no_database", phone=u.phone, status="sent", send_at=sent_at)
            if returned:
                User.objects.filter(pk=u.pk).update(last_login=sent_at + datetime.timedelta(days=1))
        for i in range(5, 9):
            u = mk_user(i)
            Message.objects.create(batch=b, user=u, route_key="no_database", phone=u.phone, status="control", send_at=sent_at)
            if i == 5:  # ۱ از ۴ کنترل برگشت
                User.objects.filter(pk=u.pk).update(last_login=sent_at + datetime.timedelta(days=2))
        services.measure(sent_at + datetime.timedelta(days=3))
        r = services.results("no_database", NOW)
        self.assertEqual((r["mature_sent"], r["mature_control"]), (4, 4))
        self.assertAlmostEqual(r["uplift"], 0.25)


class RouteDefTests(TestCase):
    def test_templates_use_only_declared_params_and_stop_link(self):
        for d in routes.DEFS.values():
            used = set(__import__("re").findall(r"#([A-Z_]+)#", d.template))
            self.assertEqual(used, set(d.params), d.key)
            self.assertIn("#STOP#", d.template)


class SettingsReachableTests(TestCase):
    def test_system_plugin_options_page_is_reachable_from_hub(self):
        from kernel import hub
        from kernel.admin import sync_states
        from kernel.models import PluginState

        sync_states()
        st = PluginState.objects.get(plugin_id="winback")
        card = next(c for c in hub.cards() if c["id"] == "winback")
        self.assertTrue(card["options"])
        admin = User.objects.create_superuser(username="adm", password="x")
        self.client.force_login(admin)
        r = self.client.get(reverse("admin:kernel_pluginstate_options", args=[st.pk]))
        self.assertContains(r, "ساخت فهرست و ارسال پیام بازگشت")
        r = self.client.post(reverse("admin:kernel_pluginstate_options", args=[st.pk]), {"enabled": "on", "control_percent": 10, "max_batch": 300,
                                                                                         "coupon_hours": 72, "ref_kind": "trial", "ref_days": 14,
                                                                                         "ref_percent": 20, "ref_cap": 10})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(services.switch_on())
        self.addCleanup(conf.clear, "winback", "enabled")


class SmsIrLinkRuleTests(TestCase):
    """sms.ir: دامنه‌ی لینک ثابت در متن قالب، فقط انتهای آن متغیر."""

    def test_domain_fixed_and_only_tail_variable(self):
        import re

        for d in routes.DEFS.values():
            for v in ("A", "B"):
                text = d.text(v)
                for name in ("LINK", "STOP"):
                    if f"#{name}#" in text:
                        self.assertRegex(text, rf"{re.escape(routes.site())}/r/(stop/)?#{name}#", d.key)
                        self.assertNotRegex(text, rf"#{name}#\S", d.key)  # بعد از متغیر چیزی نچسبد
                self.assertNotIn("{SITE}", text)
                self.assertNotIn("http", text)

    def test_codes_are_alnum_and_short_stop_route_works(self):
        from winback.models import new_code

        for _ in range(50):
            self.assertRegex(new_code(), r"^[A-Za-z0-9]{8}$")
        mk = mk_user(1)
        Route.objects.get_or_create(key="no_database")
        from winback.models import Batch, Message

        b = Batch.objects.create(route=Route.objects.get(key="no_database"))
        m = Message.objects.create(batch=b, user=mk, route_key="no_database", phone=mk.phone, status="sent")
        self.assertEqual(self.client.get(f"/r/stop/{m.code}/").status_code, 200)
        self.assertEqual(self.client.post(f"/r/stop/{m.code}/").status_code, 200)
        self.assertFalse(services.wants(mk))
        self.assertEqual(self.client.get(f"/r/{m.code}/stop/").status_code, 200)  # مسیر قدیمی هم کار می‌کند
