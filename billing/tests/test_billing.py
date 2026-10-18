import io
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from billing import services
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


@override_settings(CANONICAL_URL="https://testserver",
                   MEDIA_ROOT="/tmp/claude-0/-home-claude/2234ec6a-5c11-59b3-8baf-aeb4326ca9f5/scratchpad/media-test")
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


class _GatewayBase:
    PROVIDER = ""

    def setUp(self):
        super().setUp()
        conf = SiteSettings.get()
        conf.pay_gateway_enabled = True
        conf.gateway_provider = self.PROVIDER
        conf.set_gateway_merchant(self.MERCHANT)
        conf.save()
        self.inv = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        self.calls = []
        self.paid = False
        self.verified = False
        self.paid_amount = None
        p = mock.patch("billing.gateways._post", self.fake_post)
        p.start()
        self.addCleanup(p.stop)

    def start(self):
        r = self.client.post(reverse("billing:pay_gateway", args=[self.inv.number]))
        self.inv.refresh_from_db()
        return r


class ZarinpalTests(_GatewayBase, BillingTests):
    PROVIDER = "zarinpal"
    MERCHANT = "11111111-2222-3333-4444-555555555555"

    def fake_post(self, url, payload):
        self.calls.append((url, payload))
        if url.endswith("/request.json"):
            return {"data": {"code": 100, "message": "Success", "authority": "A0000000000000000000000000000077",
                             "fee_type": "Merchant", "fee": 0}, "errors": []}
        if url.endswith("/verify.json"):
            if not self.paid:
                return {"data": [], "errors": {"code": -51, "message": "Session is not valid"}}
            if self.paid_amount is not None and payload["amount"] != self.paid_amount:
                return {"data": [], "errors": {"code": -50, "message": "amount mismatch"}}
            code = 101 if self.verified else 100
            self.verified = True
            return {"data": {"code": code, "ref_id": 201, "card_pan": "502229******5995"}, "errors": []}
        raise AssertionError(url)

    def test_callback_uses_canonical_domain(self):
        with self.settings(CANONICAL_URL="https://postgis.ir",
                           ALLOWED_HOSTS=["testserver", "secondary.postgis.ir"]):
            request = RequestFactory().get("/", HTTP_HOST="secondary.postgis.ir")
            callback = services._callback_url(self.inv, request)
        self.assertEqual(callback, f"https://postgis.ir/billing/callback/{self.inv.number}/")

    @override_settings(CANONICAL_URL="https://postgis.ir",
                       ALLOWED_HOSTS=["testserver", "secondary.postgis.ir"])
    def test_secondary_domain_must_not_start_gateway_payment(self):
        response = self.client.post(reverse("billing:pay_gateway", args=[self.inv.number]),
                                    HTTP_HOST="secondary.postgis.ir")
        expected = f"https://postgis.ir/billing/invoice/{self.inv.number}/"
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], expected)
        self.assertEqual(self.calls, [])

    def test_full_flow(self):
        r = self.start()
        self.assertEqual(r["Location"], "https://payment.zarinpal.com/pg/StartPay/A0000000000000000000000000000077")
        url, payload = self.calls[0]
        self.assertEqual(url, "https://payment.zarinpal.com/pg/v4/payment/request.json")
        self.assertEqual(payload["amount"], 1500000)
        self.assertEqual(payload["currency"], "IRR")
        self.assertEqual(payload["merchant_id"], self.MERCHANT)
        self.assertTrue(payload["callback_url"].endswith(f"/billing/callback/{self.inv.number}/"))
        cb = reverse("billing:callback", args=[self.inv.number])
        # لغو در درگاه
        self.client.get(cb, {"Authority": self.inv.provider_id, "Status": "NOK"})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "pending")
        # پرداخت موفق
        self.paid = True
        r = self.client.get(cb, {"Authority": self.inv.provider_id, "Status": "OK"})
        self.assertRedirects(r, reverse("billing:invoice", args=[self.inv.number]), fetch_redirect_response=False)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "paid")
        self.assertEqual(self.inv.gateway_ref, "201")
        self.assertEqual(self.inv.payer_card_last4, "5995")
        self.assertIsNotNone(self.inv.applied_at)
        # تکرار callback بی‌اثر است
        self.client.get(cb, {"Authority": self.inv.provider_id, "Status": "OK"})
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "paid")

    def test_forged_callback_cannot_mark_paid(self):
        self.start()
        cb = reverse("billing:callback", args=[self.inv.number])
        # Status=OK بدون پرداخت واقعی
        Client().get(cb, {"Authority": self.inv.provider_id, "Status": "OK"})
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "pending")
        # شناسه پرداخت یک فاکتور دیگر
        self.paid = True
        n = len(self.calls)
        Client().get(cb, {"Authority": "A-someone-else", "Status": "OK"})
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "pending")
        self.assertEqual(len(self.calls), n)  # اصلاً verify نشد

    def test_amount_mismatch_not_paid(self):
        self.start()
        self.paid, self.paid_amount = True, 1000000
        services.verify_gateway(Invoice.objects.get(pk=self.inv.pk))
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "pending")

    def test_anonymous_return_still_verifies(self):
        self.start()
        self.paid = True
        r = Client().get(reverse("billing:callback", args=[self.inv.number]),
                         {"Authority": self.inv.provider_id, "Status": "OK"})
        self.assertContains(r, "پرداخت تأیید شد")
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "paid")

    def test_maintenance_verifies_abandoned_payment(self):
        self.start()
        self.paid = True
        services.maintenance()
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "paid")

    def test_already_verified_counts_as_paid(self):
        self.start()
        self.paid, self.verified = True, True
        services.verify_gateway(Invoice.objects.get(pk=self.inv.pk))
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "paid")

    def test_request_error_message(self):
        with mock.patch("billing.gateways._post",
                        lambda url, p: {"data": [], "errors": {"code": -11, "message": "x"}}):
            r = self.client.post(reverse("billing:pay_gateway", args=[self.inv.number]), follow=True)
        self.assertContains(r, "مرچنت کد فعال نیست")

    def test_sandbox_urls(self):
        conf = SiteSettings.get()
        conf.gateway_sandbox = True
        conf.save()
        r = self.start()
        self.assertTrue(r["Location"].startswith("https://sandbox.zarinpal.com/pg/StartPay/"))
        self.assertTrue(self.calls[-1][0].startswith("https://sandbox.zarinpal.com/pg/v4/"))


class ZibalTests(_GatewayBase, BillingTests):
    PROVIDER = "zibal"
    MERCHANT = "my-zibal-merchant"

    def fake_post(self, url, payload):
        self.calls.append((url, payload))
        if url.endswith("/request"):
            return {"result": 100, "trackId": 15966442233, "message": "success"}
        if url.endswith("/verify"):
            if not self.paid:
                return {"result": 202, "message": "unpaid"}
            if self.verified:
                return {"result": 201, "message": "already"}
            self.verified = True
            return {"result": 100, "amount": self.paid_amount or 1500000, "refNumber": 98765,
                    "cardNumber": "62741****44", "orderId": self.inv.number}
        if url.endswith("/inquiry"):
            return {"result": 100, "status": 1, "amount": 1500000}
        raise AssertionError(url)

    def test_full_flow(self):
        r = self.start()
        self.assertEqual(r["Location"], "https://gateway.zibal.ir/start/15966442233")
        url, payload = self.calls[0]
        self.assertEqual(url, "https://gateway.zibal.ir/v1/request")
        self.assertEqual((payload["merchant"], payload["amount"], payload["orderId"]),
                         (self.MERCHANT, 1500000, self.inv.number))
        self.paid = True
        self.client.get(reverse("billing:callback", args=[self.inv.number]),
                        {"trackId": "15966442233", "success": "1", "status": "2"})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "paid")
        self.assertEqual(self.inv.gateway_ref, "98765")
        self.assertEqual(self.calls[-1][1], {"merchant": self.MERCHANT, "trackId": 15966442233})

    def test_amount_mismatch(self):
        self.start()
        self.paid, self.paid_amount = True, 10000
        services.verify_gateway(Invoice.objects.get(pk=self.inv.pk))
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "pending")

    def test_already_verified_uses_inquiry_amount(self):
        self.start()
        self.paid, self.verified = True, True
        services.verify_gateway(Invoice.objects.get(pk=self.inv.pk))
        self.assertEqual(Invoice.objects.get(pk=self.inv.pk).status, "paid")
        self.assertTrue(self.calls[-1][0].endswith("/inquiry"))

    def test_sandbox_uses_zibal_merchant(self):
        conf = SiteSettings.get()
        conf.gateway_sandbox = True
        conf.save()
        self.start()
        self.assertEqual(self.calls[-1][1]["merchant"], "zibal")


class PaymentLinkTests(BillingTests):
    def test_link_only_manual_method(self):
        conf = SiteSettings.get()
        conf.pay_card_number = ""
        conf.pay_link_url = "https://zarinp.al/postgis"
        conf.save()
        inv = services.create_invoice(self.user, Invoice.Kind.UPGRADE, self.pro, self.db)
        r = self.client.get(reverse("billing:invoice", args=[inv.number]))
        self.assertContains(r, "https://zarinp.al/postgis")
        self.assertContains(r, inv.number)
