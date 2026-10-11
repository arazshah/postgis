import io
import json
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from billing import services
from billing.aban import AbanInvoice
from billing.models import Invoice, PlanVoucher
from core.models import SiteSettings
from databases import services as db_services
from databases.models import DatabaseServer, Plan, UserDatabase


def png():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, "PNG")
    return SimpleUploadedFile("r.png", buf.getvalue(), content_type="image/png")


class FakeProv:
    def __init__(self):
        self.calls = []

    def create_tenant(self, name, role, password, exts, limits):
        return list(exts)

    def database_sizes(self, names):
        return {n: 1000 for n in names}

    def __getattr__(self, item):
        return lambda *a, **k: self.calls.append((item, *a))


@override_settings(MEDIA_ROOT="/tmp/claude-0/-home-claude/2234ec6a-5c11-59b3-8baf-aeb4326ca9f5/scratchpad/media-test")
class BillingTests(TestCase):
    def setUp(self):
        self.prov = FakeProv()
        p = mock.patch.object(db_services, "provisioner_for", return_value=self.prov)
        p.start()
        self.addCleanup(p.stop)
        server = DatabaseServer(name="s", host="h", public_host="db.x", is_default=True)
        server.set_admin_password("x")
        server.save()
        conf = SiteSettings.get()
        conf.pay_enabled = True
        conf.pay_manual_enabled = True
        conf.pay_card_number = "6037991234567890"
        conf.pay_card_holder = "آراز"
        conf.save()
        self.pro = Plan.objects.create(name="حرفه‌ای", slug="pro", quota_mb=10240, max_connections=10,
                                       duration_days=30, price_toman=150000, is_free=False, is_renewable=False)
        self.user = User.objects.create_user("09121110000")
        self.db = db_services.create_database(self.user, "mydb", "Abcdefgh1234", [])
        self.client.force_login(self.user)

    def test_disabled(self):
        SiteSettings.objects.update(pay_enabled=False)
        with self.assertRaises(services.BillingError):
            services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)

    def test_free_plan_not_buyable_and_free_renew_blocked_for_paid(self):
        with self.assertRaises(services.BillingError):
            services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.db.plan, self.db)
        self.db.plan = self.pro
        self.db.save()
        with self.assertRaises(db_services.ServiceError):
            db_services.renew(self.db)

    def test_manual_flow_upgrade(self):
        r = self.client.post(reverse("billing:start"), {"plan": "pro", "target": str(self.db.pk)})
        inv = Invoice.objects.get()
        self.assertRedirects(r, reverse("billing:invoice", args=[inv.number]))
        self.assertEqual((inv.kind, inv.amount_toman, inv.amount_rial), ("upgrade", 150000, 1500000))
        page = self.client.get(reverse("billing:invoice", args=[inv.number]))
        self.assertContains(page, "6037-9912-3456-7890")
        r = self.client.post(reverse("billing:receipt", args=[inv.number]),
                             {"receipt": png(), "last4": "۱۲۳۴", "tracking": "998877"})
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.payer_card_last4, inv.method), ("review", "1234", "manual"))
        # فقط صاحب فاکتور و مدیر رسید را می‌بینند
        self.assertEqual(self.client.get(reverse("billing:receipt_file", args=[inv.number])).status_code, 200)
        other = User.objects.create_user("09121110001")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("billing:receipt_file", args=[inv.number])).status_code, 404)
        self.assertEqual(self.client.get(reverse("billing:invoice", args=[inv.number])).status_code, 404)
        # تأیید مدیر
        admin = User.objects.create_admin("boss", "Adm1n-Password!")
        self.client.force_login(admin)
        r = self.client.post("/manage/billing/invoice/", {"action": "approve", "_selected_action": [inv.pk]})
        self.assertEqual(r.status_code, 302)
        inv.refresh_from_db()
        self.db.refresh_from_db()
        self.assertEqual(inv.status, "paid")
        self.assertIsNotNone(inv.applied_at)
        self.assertEqual(self.db.plan, self.pro)
        self.assertTrue(any(c[0] == "apply_limits" for c in self.prov.calls))

    def test_mark_paid_idempotent(self):
        inv = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        services.mark_paid(inv)
        first = UserDatabase.objects.get(pk=self.db.pk).expires_at
        services.mark_paid(inv)
        services.apply_invoice(Invoice.objects.get(pk=inv.pk))
        self.assertEqual(UserDatabase.objects.get(pk=self.db.pk).expires_at, first)

    def test_reuses_open_invoice(self):
        a = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        b = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        self.assertEqual(a.pk, b.pk)

    def test_new_db_voucher_bypasses_limit(self):
        inv = services.create_invoice(self.user, Invoice.Kind.NEW, self.pro)
        services.mark_paid(inv)
        v = PlanVoucher.objects.get(user=self.user)
        r = self.client.post(reverse("databases:create") + f"?voucher={v.pk}",
                             {"label": "second", "password": "Abcdefgh1234", "voucher": v.pk})
        db2 = UserDatabase.objects.get(db_name="gp_second")
        self.assertRedirects(r, reverse("databases:detail", args=[db2.pk]), fetch_redirect_response=False)
        self.assertEqual(db2.plan, self.pro)
        v.refresh_from_db()
        self.assertEqual(v.used_by, db2)

    def test_expired_db_reactivated_on_paid_renewal(self):
        self.db.status = UserDatabase.Status.EXPIRED
        self.db.expires_at = timezone.now() - timedelta(days=1)
        self.db.save()
        inv = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        services.mark_paid(inv)
        self.db.refresh_from_db()
        self.assertEqual(self.db.status, "active")
        self.assertIn(("set_login", self.db.role_name, True), self.prov.calls)
        self.assertGreater(self.db.days_left, 25)


@override_settings(MEDIA_ROOT="/tmp/claude-0/-home-claude/2234ec6a-5c11-59b3-8baf-aeb4326ca9f5/scratchpad/media-test")
class AbanTests(BillingTests):
    def setUp(self):
        super().setUp()
        conf = SiteSettings.get()
        conf.pay_aban_enabled = True
        conf.aban_api_base = "https://api.example-aban.ir/v1"
        conf.set_aban_api_key("KEY123")
        conf.save()
        self.inv = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        self.requests = []
        self.status = "pending"
        self.paid_rial = None

        def fake_request(client, method, path, payload=None):
            self.requests.append((method, path, payload, client.key))
            if method == "POST":
                return {"data": {"id": "AB-77", "pay_url": "https://pay.example-aban.ir/AB-77", "status": "pending"}}
            return {"id": "AB-77", "status": self.status, "paid_amount_rial": self.paid_rial}

        p = mock.patch("billing.aban.AbanClient._request", fake_request)
        p.start()
        self.addCleanup(p.stop)

    def test_redirect_and_callback_paid(self):
        r = self.client.post(reverse("billing:pay_aban", args=[self.inv.number]))
        self.assertEqual(r["Location"], "https://pay.example-aban.ir/AB-77")
        method, path, payload, key = self.requests[0]
        self.assertEqual((method, path, key), ("POST", "/invoices", "KEY123"))
        self.assertEqual(payload["amount_rial"], 1500000)
        self.assertEqual(payload["order_id"], self.inv.number)
        self.assertTrue(payload["callback_url"].endswith(f"/billing/callback/{self.inv.number}/"))
        # برگشت بدون پرداخت
        self.client.get(reverse("billing:callback", args=[self.inv.number]))
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "pending")
        # پرداخت شد
        self.status = "paid"
        self.client.get(reverse("billing:callback", args=[self.inv.number]))
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "paid")
        self.assertIsNotNone(self.inv.applied_at)
        self.assertEqual(self.requests[-1][1], "/invoices/AB-77")

    def test_webhook_cannot_fake_payment(self):
        self.client.post(reverse("billing:pay_aban", args=[self.inv.number]))
        r = self.client.post(reverse("billing:aban_webhook"), data=json.dumps(
            {"order_id": self.inv.number, "status": "paid"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "pending")  # API هنوز pending است
        self.status = "paid"
        self.client.post(reverse("billing:aban_webhook"), data=json.dumps({"data": {"id": "AB-77"}}),
                         content_type="application/json")
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "paid")

    def test_underpayment_goes_to_review(self):
        self.client.post(reverse("billing:pay_aban", args=[self.inv.number]))
        self.status, self.paid_rial = "paid", 1000000
        services.check_aban(Invoice.objects.get(pk=self.inv.pk))
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "review")
        self.assertIsNone(self.inv.applied_at)

    def test_parse_variants(self):
        from billing.aban import _parse

        self.assertEqual(_parse({"invoice": {"uuid": "x", "payment_url": "https://p/x", "state": "PAID"}}),
                         AbanInvoice(id="x", pay_url="https://p/x", status="paid", paid_rial=None))
