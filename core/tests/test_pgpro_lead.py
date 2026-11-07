from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.models import ContactRequest

ORIGIN = "https://pgpro.ir"


class PgproLeadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("core:pgpro_lead")

    def data(self, **kw):
        d = {"name": "علی رضایی", "phone": "09123456789", "organization": "شهرداری نمونه",
             "interest": "quote", "quantity": "3", "usage": "شهرداری", "message": "برای سه شعبه"}
        d.update(kw)
        return d

    def test_creates_lead_with_cors(self):
        r = self.client.post(self.url, self.data(), HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r["Access-Control-Allow-Origin"], ORIGIN)
        lead = ContactRequest.objects.get()
        self.assertEqual(lead.topic, "pgpro")
        self.assertIn("پیش‌فاکتور", lead.message)
        self.assertIn("تعداد دستگاه: 3", lead.message)

    def test_preflight(self):
        r = self.client.options(self.url, HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r["Access-Control-Allow-Origin"], ORIGIN)

    def test_foreign_origin_rejected(self):
        r = self.client.post(self.url, self.data(), HTTP_ORIGIN="https://evil.example")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ContactRequest.objects.exists())

    def test_validation_errors(self):
        r = self.client.post(self.url, self.data(phone="12"), HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 400)
        self.assertIn("phone", r.json()["errors"])

    def test_honeypot(self):
        r = self.client.post(self.url, self.data(website="http://spam"), HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ContactRequest.objects.exists())

    def test_throttle(self):
        for i in range(5):
            self.client.post(self.url, self.data(phone=f"0912345678{i}"), HTTP_ORIGIN=ORIGIN)
        r = self.client.post(self.url, self.data(phone="09129999999"), HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 429)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
