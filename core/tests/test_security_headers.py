import gzip

from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.middleware import SafeGZipMiddleware, SecurityHeadersMiddleware


class GzipTests(TestCase):
    def test_html_is_compressed_when_client_accepts_gzip(self):
        r = self.client.get("/", HTTP_ACCEPT_ENCODING="gzip, br")
        self.assertEqual(r["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", r["Vary"])
        self.assertIn("<html", gzip.decompress(r.content).decode())

    def test_no_compression_without_accept_encoding(self):
        r = self.client.get("/")
        self.assertNotIn("Content-Encoding", r)


class SafeGzipUnitTests(SimpleTestCase):
    def run_mw(self, response):
        req = RequestFactory().get("/", HTTP_ACCEPT_ENCODING="gzip")
        return SafeGZipMiddleware(lambda r: response)(req)

    def test_streaming_and_event_stream_are_left_alone(self):
        sse = StreamingHttpResponse(iter([b"data: x\n\n" * 50]), content_type="text/event-stream")
        self.assertNotIn("Content-Encoding", self.run_mw(sse))
        big = StreamingHttpResponse(iter([b"a" * 5000]), content_type="text/plain")
        self.assertNotIn("Content-Encoding", self.run_mw(big))

    def test_already_compressed_types_are_left_alone(self):
        for ctype in ("application/zip", "image/png", "application/pdf"):
            r = self.run_mw(HttpResponse(b"x" * 5000, content_type=ctype))
            self.assertNotIn("Content-Encoding", r, ctype)

    def test_text_json_and_vector_tiles_are_compressed(self):
        for ctype in ("application/json", "application/geo+json", "application/vnd.mapbox-vector-tile"):
            r = self.run_mw(HttpResponse(b"x" * 5000, content_type=ctype))
            self.assertEqual(r["Content-Encoding"], "gzip", ctype)


class SecurityHeadersTests(TestCase):
    def test_csp_is_report_only_by_default_and_reports_to_endpoint(self):
        r = self.client.get("/")
        self.assertNotIn("Content-Security-Policy", r)
        csp = r["Content-Security-Policy-Report-Only"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("report-uri /csp-report/", csp)
        self.assertIn("https://unpkg.com", csp)

    def test_permissions_policy_keeps_geolocation_for_field_forms(self):
        pp = self.client.get("/")["Permissions-Policy"]
        self.assertIn("geolocation=(self)", pp)
        self.assertIn("camera=()", pp)

    def test_enforce_and_off_modes(self):
        with override_settings(CSP_MODE="enforce"):
            r = SecurityHeadersMiddleware(lambda q: HttpResponse("x"))(RequestFactory().get("/"))
            self.assertIn("Content-Security-Policy", r)
            self.assertNotIn("Content-Security-Policy-Report-Only", r)
        with override_settings(CSP_MODE="off"):
            r = SecurityHeadersMiddleware(lambda q: HttpResponse("x"))(RequestFactory().get("/"))
            self.assertNotIn("Content-Security-Policy", r)
            self.assertNotIn("Content-Security-Policy-Report-Only", r)

    def test_view_can_set_its_own_csp(self):
        resp = HttpResponse("x")
        resp["Content-Security-Policy-Report-Only"] = "default-src 'none'"
        r = SecurityHeadersMiddleware(lambda q: resp)(RequestFactory().get("/"))
        self.assertEqual(r["Content-Security-Policy-Report-Only"], "default-src 'none'")

    def test_csp_report_endpoint(self):
        body = '{"csp-report": {"violated-directive": "script-src", "blocked-uri": "https://x.example/a.js"}}'
        with self.assertLogs("csp", level="WARNING") as cm:
            r = self.client.post("/csp-report/", body, content_type="application/csp-report")
        self.assertEqual(r.status_code, 204)
        self.assertIn("script-src", cm.output[0])
        self.assertEqual(self.client.get("/csp-report/").status_code, 405)
        self.assertEqual(self.client.post("/csp-report/", "not json", content_type="application/csp-report").status_code, 204)


class FramingTests(TestCase):
    def test_only_embed_views_may_be_framed(self):
        from unittest import mock

        from maps import views as map_views
        from publish import views as pub_views

        req = RequestFactory().get("/")
        for mod in (map_views, pub_views):
            with mock.patch.object(mod, "public_map", return_value=HttpResponse("x")):
                self.assertTrue(mod.embed_map(req, "s").xframe_options_exempt, mod.__name__)
        self.assertEqual(self.client.get("/")["X-Frame-Options"], "DENY")

    def test_framing_exempt_response_gets_no_xfo_header(self):
        from django.middleware.clickjacking import XFrameOptionsMiddleware

        resp = HttpResponse("x")
        resp.xframe_options_exempt = True
        self.assertNotIn("X-Frame-Options", XFrameOptionsMiddleware(lambda r: resp)(RequestFactory().get("/")))
