"""فاز ۲ بازگشت: کد تخفیف روی فاکتور (kernel.pricing)، آزمون A/B، ارسال دستی."""
import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import sms
from accounts.models import User
from billing import services as billing
from billing.models import Invoice
from core.models import SiteSettings
from databases.models import Plan
from kernel import conf, pricing
from winback import routes, services
from winback.models import Batch, Coupon, Message, Route
from winback.tests.test_winback import NOW, Base, mk_user


class CouponTests(TestCase):
    def setUp(self):
        s = SiteSettings.get()
        s.pay_enabled, s.pay_manual_enabled, s.pay_card_number, s.pay_card_holder = True, True, "6037991234567890", "الف"
        s.save()
        self.plan = Plan.objects.create(name="حرفه‌ای", slug="pro", quota_mb=10240, max_connections=10, duration_days=30,
                                        price_toman=100000, is_free=False, is_renewable=True)
        self.user = User.objects.create_user("09121110000")

    def _coupon(self, pct=20, hours=72):
        return Coupon.objects.create(user=self.user, percent=pct, expires_at=timezone.now() + datetime.timedelta(hours=hours))

    def test_no_coupon_full_price(self):
        inv = billing.create_invoice(self.user, Invoice.Kind.NEW, self.plan)
        self.assertEqual(inv.amount_toman, 100000)

    def test_coupon_applies_once_and_binds(self):
        c = self._coupon(20)
        inv = billing.create_invoice(self.user, Invoice.Kind.NEW, self.plan)
        self.assertEqual(inv.amount_toman, 80000)
        self.assertIn("20", inv.note)
        c.refresh_from_db()
        self.assertEqual(c.invoice_id, inv.pk)
        inv.status = Invoice.Status.PAID
        inv.save()
        self.assertEqual(pricing.quote(self.user, 100000).amount, 100000)  # مصرف شد

    def test_expired_coupon_ignored_and_dead_invoice_frees_it(self):
        self._coupon(20, hours=-1)
        self.assertEqual(billing.create_invoice(self.user, Invoice.Kind.NEW, self.plan).amount_toman, 100000)
        Invoice.objects.all().delete()
        c = self._coupon(30)
        inv = billing.create_invoice(self.user, Invoice.Kind.NEW, self.plan)
        self.assertEqual(inv.amount_toman, 70000)
        inv.status = Invoice.Status.CANCELLED
        inv.save()
        self.assertEqual(pricing.quote(self.user, 100000).amount, 70000)  # آزاد شد
        c.refresh_from_db()

    def test_existing_open_invoice_gets_repriced_by_new_coupon(self):
        inv = billing.create_invoice(self.user, Invoice.Kind.NEW, self.plan)
        self.assertEqual(inv.amount_toman, 100000)
        self._coupon(25)
        again = billing.create_invoice(self.user, Invoice.Kind.NEW, self.plan)
        self.assertEqual((again.pk, again.amount_toman), (inv.pk, 75000))

    def test_best_of_two_and_never_zero(self):
        self._coupon(10)
        self._coupon(50)
        self.assertEqual(pricing.quote(self.user, 100000).amount, 50000)
        self.assertEqual(pricing.quote(self.user, 1).amount, 1)

    def test_broken_adjuster_does_not_break_invoice(self):
        with mock.patch.object(pricing, "load", side_effect=RuntimeError("x")):
            self.assertEqual(pricing.quote(self.user, 500).amount, 500)


class GiftCouponTests(Base):
    def test_click_grants_coupon_once_and_message_shows_it(self):
        Route.objects.filter(key="no_database").update(gift_kind="coupon", gift_percent=15)
        u = mk_user(1)
        m = services.plan_batches(NOW)[0].messages.get()
        m.status, m.send_at, m.sent_at = Message.Status.SENT, NOW, NOW
        m.save()
        for _ in range(2):
            self.client.get(reverse("winback:go", args=[m.code]))
        c = Coupon.objects.get(user=u)
        self.assertEqual(c.percent, 15)
        self.assertEqual(Coupon.objects.count(), 1)
        self.assertLess(c.expires_at, timezone.now() + datetime.timedelta(hours=73))


class ABTests(Base):
    def test_split_and_templates_per_variant(self):
        Route.objects.filter(key="no_database").update(template_id_b="456")
        for i in range(1, 41):
            mk_user(i)
        batch = services.plan_batches(NOW)[0]
        counts = {v: batch.messages.filter(variant=v).count() for v in "AB"}
        self.assertTrue(10 < counts["A"] < 30 and 10 < counts["B"] < 30, counts)
        admin = User.objects.create_user("09129999999")
        services.approve(batch, admin, NOW)
        last = max(batch.messages.values_list("send_at", flat=True).exclude(send_at=None))
        by_phone = dict(batch.messages.values_list("phone", "variant"))
        sent = {}
        with mock.patch.object(sms, "send_template") as send:
            for _ in range(3):  # هر tick حداکثر ۲۰ پیام
                services.send_due(last)
            for call in send.call_args_list:
                sent.setdefault(by_phone[call.args[0]], set()).add(call.args[1])
        self.assertEqual(sent, {"A": {"123"}, "B": {"456"}})

    def test_no_b_template_means_all_a(self):
        for i in range(1, 6):
            mk_user(i)
        self.assertEqual(set(services.plan_batches(NOW)[0].messages.values_list("variant", flat=True)), {"A"})

    def test_winner_needs_enough_samples_and_significance(self):
        b = Batch.objects.create(route=Route.objects.get(key="no_database"), status="approved")
        old = NOW - datetime.timedelta(days=10)
        for i in range(80):
            u = mk_user(i + 1)
            v = "A" if i < 40 else "B"
            returned = (i % 10 == 0) if v == "A" else (i % 2 == 0)  # A≈10٪، B≈50٪
            Message.objects.create(batch=b, user=u, route_key="no_database", phone=u.phone, status="sent", send_at=old,
                                   variant=v, returned_at=old if returned else None)
        r = services.ab_results("no_database", NOW)
        self.assertEqual(r["winner"], "B")
        Message.objects.filter(variant="B").delete()
        Message.objects.filter(variant="A").update(variant="B")  # فقط یک نسخه
        self.assertEqual(services.ab_results("no_database", NOW)["winner"], "")


class ManualTests(Base):
    def setUp(self):
        super().setUp()
        Route.objects.filter(key="announce").update(enabled=True, template_id="789")
        self.staff = User.objects.create_superuser(username="adm", password="x")
        self.client.force_login(self.staff)

    def test_announce_is_not_in_nightly_plan(self):
        mk_user(1)
        Route.objects.update(enabled=True, template_id="1")
        keys = {b.route.key for b in services.plan_batches(NOW)}
        self.assertNotIn("announce", keys)

    def test_estimate_and_send_respect_rules(self):
        from databases.models import DatabaseServer, UserDatabase
        from databases.models import Plan as P

        server = DatabaseServer(name="s", host="h", public_host="x", is_default=True)
        server.set_admin_password("x")
        server.save()
        plan = P.objects.get(slug="free")
        a, b = mk_user(1, days_ago=5), mk_user(2, days_ago=5)
        for u in (a, b):
            User.objects.filter(pk=u.pk).update(last_login=timezone.now())
            UserDatabase.objects.create(owner=u, server=server, plan=plan, label="db", db_name=f"d{u.pk}", role_name=f"r{u.pk}", status="active")
        services.set_pref(b, False)  # لغو کرده
        route = Route.objects.get(key="announce")
        est = services.manual_estimate(route, {"FEATURE": "نقشه‌ی حرارتی"}, 100)
        self.assertEqual((est["count"], est["control"], est["real"]), (1, 0, 1))
        self.assertIn("نقشه‌ی حرارتی", est["sample"])
        batch, n = services.manual_send(route, {"FEATURE": "نقشه‌ی حرارتی"}, 100, self.staff)
        self.assertEqual(n, 1)
        m = batch.messages.get()
        self.assertEqual(m.status, "scheduled")
        self.assertIn("نقشه‌ی حرارتی", services.preview(m))
        self.assertEqual(services.manual_estimate(route, {"FEATURE": "x"}, 100)["count"], 0)  # کول‌داون

    def test_manual_page_preview_and_send_needs_stepup(self):
        url = reverse("admin:winback_manual")
        r = self.client.post(url, {"route": "announce", "extra": "نقشه", "limit": 50, "do": "preview"})
        self.assertContains(r, "پیش‌نمایش")
        with mock.patch("winback.admin.stepup.ok", return_value=False), mock.patch("winback.admin.stepup.url", return_value="/su/"):
            r = self.client.post(url, {"route": "announce", "extra": "نقشه", "limit": 50, "do": "send"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/su/")
        self.assertEqual(self.client.get(url).status_code, 200)


class DefTests(TestCase):
    def test_variant_b_uses_same_params_and_stop(self):
        import re

        for d in routes.DEFS.values():
            if d.variant_b:
                used = set(re.findall(r"#([A-Z_]+)#", d.variant_b))
                self.assertTrue(used <= set(d.params) and {"LINK", "STOP"} <= used, d.key)


class SendNowTests(Base):
    def _scheduled(self):
        mk_user(1)
        batch = services.plan_batches(NOW)[0]
        services.approve(batch, User.objects.create_user("09129999999"), NOW)
        return batch

    def test_sends_future_message_now_inside_window(self):
        batch = self._scheduled()
        m = batch.messages.get()
        self.assertGreater(m.send_at, NOW)
        with mock.patch.object(sms, "send_template") as send:
            r = services.send_now(Message.objects.filter(batch=batch), NOW)
        send.assert_called_once()
        self.assertEqual((r["picked"], r["sent"], r["deferred"], r["stuck"]), (1, 1, 0, 0))
        m.refresh_from_db()
        self.assertEqual(m.status, "sent")

    def test_outside_window_is_deferred_not_sent(self):
        batch = self._scheduled()
        night = datetime.datetime(2026, 11, 14, 22, 0, tzinfo=datetime.UTC)  # ۰۱:۳۰ بامداد تهران
        with mock.patch.object(sms, "send_template") as send:
            r = services.send_now(Message.objects.filter(batch=batch), night)
        send.assert_not_called()
        self.assertEqual((r["sent"], r["deferred"]), (0, 1))
        m = batch.messages.get()
        self.assertEqual(m.status, "scheduled")
        self.assertTrue(services.timing.in_window(m.send_at))

    def test_opted_out_user_still_skipped(self):
        batch = self._scheduled()
        m = batch.messages.get()
        Message.objects.filter(pk=m.pk).update(status="scheduled")
        from winback.models import Preference

        Preference.objects.create(user=m.user, marketing=False)
        with mock.patch.object(sms, "send_template") as send:
            r = services.send_now(Message.objects.filter(batch=batch), NOW)
        send.assert_not_called()
        self.assertEqual(r["skipped"], 1)

    def test_admin_action_needs_switch_and_stepup(self):
        from django.urls import reverse as rev

        batch = self._scheduled()
        staff = User.objects.create_superuser(username="adm", password="x")
        self.client.force_login(staff)
        url = rev("admin:winback_batch_changelist")
        data = {"action": "send_now_batches", "_selected_action": [batch.pk]}
        r = self.client.post(url, data, follow=True)
        self.assertContains(r, "خاموش")  # سوئیچ کلی خاموش
        conf.set_value("winback", "enabled", True)
        self.addCleanup(conf.clear, "winback", "enabled")
        with mock.patch("winback.admin.stepup.ok", return_value=False), mock.patch("winback.admin.stepup.url", return_value="/su/"):
            r = self.client.post(url, data)
        self.assertEqual((r.status_code, r["Location"]), (302, "/su/"))
        self.assertEqual(batch.messages.get().status, "scheduled")
