from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["postgis.ir"])
class HealthTests(TestCase):
    def test_healthz_ignores_host(self):
        r = self.client.get("/healthz", HTTP_HOST="127.0.0.1:8000")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_other_pages_still_check_host(self):
        self.assertEqual(self.client.get("/", HTTP_HOST="evil.example").status_code, 400)
        self.assertEqual(self.client.get("/", HTTP_HOST="postgis.ir").status_code, 200)
