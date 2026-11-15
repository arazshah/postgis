"""بازگشت کاربران با ایمیل (فاز ۴): کانال‌ها، رضایت مشترک، لغو یک‌کلیکی، A/B موضوع، پیامک پس از ایمیل و گزارش ماهانه."""
import datetime
from unittest import mock

from django.core import mail as djmail
from django.test import Client, TestCase
from django.urls import reverse

from accounts import sms
from accounts.models import User
from databases.models import UserDatabase
from kernel import conf, mail
from kernel.models import OutgoingEmail
from winback import routes, services
from winback.models import Message, Preference, Route
from winback.tests.test_winback import NOW

ADMIN_NOW = NOW + datetime.timedelta(minutes=1)


def mk(n, *, phone=True, email=True, days_ago=5, **kw):
    u = User.objects.create_user(f"0912111{n:04d}" if phone else None, email=f"u{n}@example.com" if email else None,
                                 full_name="علی رضایی", **kw)
    User.objects.filter(pk=u.pk).update(date_joined=NOW - datetime.timedelta(days=days_ago),
                                        phone_verified_at=NOW if phone else None, email_verified_at=NOW if email else None)
    u.refresh_from_db()
    return u


class Base(TestCase):
    def setUp(self):
        conf.set_value("winback", "control_percent", 0)
        conf.set_value("winback", "email_daily_cap", 100)
        self.addCleanup(conf.clear, "winback", "control_percent")
        self.addCleanup(conf.clear, "winback", "email_daily_cap")
        services.sync_routes()
        self.admin = User.objects.create_user("09129990000")

    def route(self, key="no_database", **kw):
        Route.objects.filter(key=key).update(enabled=True, **kw)
        return Route.objects.get(key=key)

    def run_batch(self, key="no_database", at=None):
        batch = services.plan_batches(NOW)[0]
        services.approve(batch, self.admin, NOW)
        last = max(batch.messages.exclude(send_at=None).values_list("send_at", flat=True))
        with mock.patch.object(sms, "send_template") as send, mock.patch.object(sms, "get_credit", return_value=None):
            out = services.send_due(at or last)
        return batch, out, send


class ChannelResolutionTests(TestCase):
    def test_matrix(self):
        both, s, e = mk(1), mk(2, email=False), mk(3, phone=False)
        self.assertEqual([routes.channel_for(u, "sms") for u in (both, s, e)], ["sms", "sms", None])
        self.assertEqual([routes.channel_for(u, "email") for u in (both, s, e)], ["email", None, "email"])
        self.assertEqual([routes.channel_for(u, "both") for u in (both, s, e)], ["both", "sms", "email"])
        self.assertEqual([routes.channel_for(u, "email_sms") for u in (both, s, e)], ["email_sms", "sms", "email"])


class EmailRouteTests(Base):
    def test_email_route_needs_no_sms_template_and_skips_phone_only_users(self):
        self.route(channel="email")
        mk(1), mk(2, email=False), mk(3, phone=False)
        batch = services.plan_batches(NOW)[0]
        self.assertEqual(sorted(batch.messages.values_list("email", flat=True)), ["u1@example.com", "u3@example.com"])
        self.assertTrue(all(m.channel == "email" for m in batch.messages.all()))

    def test_sms_route_without_template_is_not_ready(self):
        route = self.route(channel="sms")
        self.assertFalse(services.ready(route))
        self.assertEqual(services.plan_batches(NOW), [])

    def test_email_goes_through_marketing_queue_with_one_click_unsubscribe(self):
        self.route(channel="email")
        u = mk(1)
        batch, out, send = self.run_batch()
        self.assertEqual(out["sent"], 1)
        send.assert_not_called()
        m = batch.messages.get()
        self.assertEqual((m.status, m.via), ("sent", "email"))
        row = OutgoingEmail.objects.get(to=u.email)
        self.assertEqual(row.category, "marketing")
        self.assertIn(f"/r/{m.code}/oneclick/", row.headers["List-Unsubscribe"])
        self.assertEqual(row.headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn(f"/r/{m.code}/?c=e", row.html)
        mail.tick()
        self.assertEqual(djmail.outbox[0].extra_headers["Precedence"], "bulk")

    def test_no_consent_no_email(self):
        self.route(channel="email")
        u = mk(1)
        batch = services.plan_batches(NOW)[0]
        services.approve(batch, self.admin, NOW)
        Preference.objects.create(user=u, marketing=False)
        send_at = batch.messages.get().send_at
        services.send_due(send_at)
        self.assertEqual(OutgoingEmail.objects.count(), 0)

    def test_both_sends_email_and_sms_and_counts_once_against_cap(self):
        self.route(channel="both", template_id="123")
        mk(1)
        batch, out, send = self.run_batch()
        self.assertEqual(out["sent"], 1)
        send.assert_called_once()
        m = batch.messages.get()
        self.assertEqual(m.via, "email+sms")
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_email_daily_cap_defers(self):
        conf.set_value("winback", "email_daily_cap", 1)
        self.route(channel="email")
        mk(1), mk(2)
        batch, out, _ = self.run_batch()
        self.assertEqual(out["sent"], 1)
        self.assertEqual(batch.messages.filter(status="scheduled").count(), 1)  # فردا دوباره

    def test_subject_ab_uses_email_variant_without_touching_sms_template(self):
        self.route(channel="email")
        for i in range(1, 41):
            mk(i)
        batch = services.plan_batches(NOW)[0]
        self.assertEqual({"A", "B"}, set(batch.messages.values_list("variant", flat=True)))
        services.approve(batch, self.admin, NOW)
        last = max(batch.messages.values_list("send_at", flat=True))
        for _ in range(3):
            services.send_due(last)
        subjects = set(OutgoingEmail.objects.values_list("subject", flat=True))
        self.assertIn("علی، پایگاه رایگانتان را بسازید", subjects)
        self.assertIn("پایگاه PostGIS رایگان شما فقط یک کلیک تا آماده‌شدن فاصله دارد", subjects)

    def test_admin_subject_override_and_hostile_values_cannot_inject_headers(self):
        self.route(channel="email", email_subject="سلام #NAME#")
        u = mk(1)
        User.objects.filter(pk=u.pk).update(full_name="علی\nBcc: evil@example.com")
        batch, out, _ = self.run_batch()
        row = OutgoingEmail.objects.get()
        self.assertNotIn("\n", row.subject)
        mail.tick()
        self.assertEqual(djmail.outbox[0].to, [u.email])

    def test_email_only_route_cannot_be_forced_to_sms(self):
        r = self.route("monthly_report", channel="sms")
        self.assertEqual(services.effective_channel(r, routes.DEFS["monthly_report"]), "email")


class FallbackTests(Base):
    def setUp(self):
        super().setUp()
        self.route(channel="email_sms", template_id="123")
        self.u = mk(1)
        self.batch, _, _ = self.run_batch()
        self.m = self.batch.messages.get()
        self.later = self.m.sent_at + datetime.timedelta(days=services.FALLBACK_DAYS, hours=2)

    def fallback(self, at=None):
        with mock.patch.object(sms, "send_template") as send, mock.patch.object(sms, "get_credit", return_value=None), \
                mock.patch("winback.timing.in_window", return_value=True):
            n = services.send_fallbacks(at or self.later)
        return n, send

    def test_email_first_then_sms_after_three_silent_days(self):
        self.assertEqual((self.m.via, self.m.channel), ("email", "email_sms"))
        self.assertIsNotNone(self.m.sms_fallback_at)
        early, send = self.fallback(self.m.sent_at + datetime.timedelta(days=1))
        self.assertEqual(early, 0)
        n, send = self.fallback()
        self.assertEqual(n, 1)
        send.assert_called_once()
        self.m.refresh_from_db()
        self.assertEqual(self.m.via, "email+sms")
        self.assertIsNone(self.m.sms_fallback_at)
        self.assertEqual(self.fallback()[0], 0)  # یک‌بار

    def test_click_cancels_sms(self):
        Message.objects.filter(pk=self.m.pk).update(clicked_at=self.later)
        n, send = self.fallback()
        self.assertEqual(n, 0)
        send.assert_not_called()
        self.m.refresh_from_db()
        self.assertIsNone(self.m.sms_fallback_at)

    def test_returning_user_cancels_sms(self):
        User.objects.filter(pk=self.u.pk).update(last_login=self.m.sent_at + datetime.timedelta(days=1))
        self.assertEqual(self.fallback()[0], 0)

    def test_unsubscribe_cancels_sms(self):
        services.set_pref(self.u, False)
        self.assertEqual(self.fallback()[0], 0)


class UnsubscribeAndClickTests(Base):
    def setUp(self):
        super().setUp()
        self.route(channel="email")
        self.u = mk(1, phone=False)
        self.batch, _, _ = self.run_batch()
        self.m = self.batch.messages.get()

    def test_oneclick_post_unsubscribes_without_csrf_and_get_does_not(self):
        c = Client(enforce_csrf_checks=True)
        url = reverse("winback:oneclick", args=[self.m.code])
        self.assertEqual(c.get(url).status_code, 302)
        self.assertTrue(services.wants(self.u))
        self.assertEqual(c.post(url).status_code, 200)
        self.assertFalse(services.wants(self.u))

    def test_unknown_code_404(self):
        self.assertEqual(Client().post(reverse("winback:oneclick", args=["nope"])).status_code, 404)

    def test_email_click_for_account_without_phone_goes_to_password_login(self):
        r = self.client.get(reverse("winback:go", args=[self.m.code]) + "?c=e")
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login_password"), r["Location"])
        self.assertIn("utm_source=email", r["Location"])
        self.m.refresh_from_db()
        self.assertIsNotNone(self.m.clicked_at)


class MonthlyReportTests(Base):
    def make_db(self, user, used_pct):
        from databases.models import DatabaseServer, Plan

        server = DatabaseServer.objects.first()
        if server is None:
            server = DatabaseServer(name="s", host="h", public_host="x", is_default=True)
            server.set_admin_password("x")
            server.save()
        plan = Plan.objects.get(slug="free")
        db = UserDatabase.objects.create(owner=user, server=server, plan=plan, label="db", db_name=f"d{user.pk}",
                                         role_name=f"r{user.pk}", status="active")
        UserDatabase.objects.filter(pk=db.pk).update(size_bytes=db.quota_bytes * used_pct // 100)
        return db

    def test_report_targets_inactive_with_db_and_builds_tip(self):
        self.route("monthly_report")
        u = mk(1, phone=False, days_ago=60)
        self.make_db(u, 90)
        quiet = mk(2, phone=False, days_ago=60)  # بی‌پایگاه
        fresh = mk(3, phone=False, days_ago=3)
        self.make_db(fresh, 10)
        batch = services.plan_batches(NOW)[0]
        self.assertEqual(list(batch.messages.values_list("user_id", flat=True)), [u.pk])
        p = batch.messages.get().params
        self.assertEqual(p["PCT"], "90")
        self.assertIn("ارتقا", p["TIP"])
        self.assertNotIn(quiet.pk, batch.messages.values_list("user_id", flat=True))

    def test_empty_db_tip(self):
        self.route("monthly_report")
        u = mk(1, phone=False, days_ago=30)
        self.make_db(u, 0)
        self.assertIn("خالی", services.plan_batches(NOW)[0].messages.get().params["TIP"])

    def test_report_email_renders_numbers(self):
        self.route("monthly_report")
        u = mk(1, phone=False, days_ago=30)
        self.make_db(u, 50)
        batch, out, _ = self.run_batch()
        self.assertEqual(out["sent"], 1)
        body = OutgoingEmail.objects.get().text
        self.assertIn("حجم مصرفی", body)
        self.assertIn("50٪", body)


class AdminTests(Base):
    def setUp(self):
        super().setUp()
        self.su = User.objects.create_superuser("boss", password="x")
        self.client.force_login(self.su)

    def form(self, key, **over):
        r = Route.objects.get(key=key)
        data = {"enabled": "on", "channel": "email", "email_subject": "", "email_subject_b": "", "template_id": "", "template_id_b": "",
                "gift_kind": "none", "gift_plugin": "", "gift_days": 7, "gift_percent": 20, **over}
        return self.client.post(reverse("admin:winback_route_change", args=[r.pk]), data)

    def test_email_route_can_be_enabled_without_sms_template(self):
        r = self.form("no_database")
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        route = Route.objects.get(key="no_database")
        self.assertEqual((route.enabled, route.channel), (True, "email"))

    def test_sms_route_still_needs_template(self):
        r = self.form("no_database", channel="both")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Route.objects.get(key="no_database").enabled)

    def test_monthly_report_offers_only_email(self):
        r = self.client.get(reverse("admin:winback_route_change", args=[Route.objects.get(key="monthly_report").pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c[0] for c in r.context["adminform"].form.fields["channel"].choices], ["email"])
        self.assertContains(r, "گزارش ماهانه")

    def test_manual_preview_counts_email_and_sms(self):
        self.route(channel="both", template_id="123")
        mk(1), mk(2, phone=False)
        r = self.client.post(reverse("admin:winback_manual"), {"route": "no_database", "limit": 50})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "2 ایمیل")
        self.assertContains(r, "1 پیامک")
