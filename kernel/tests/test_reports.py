"""گزارش PDF `[[reports]]`: مشخصات، نقشه‌ی SVG، escape، بستن واکشی، PDF واقعی و نمای دانلود."""
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, pagekit, reports
from kernel.models import PluginUsage
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PAGE = {"key": "rep", "title": "مانیتورینگ", "blocks": [
    {"kind": "kpi", "title": "تعداد", "sql": "select 1"}, {"kind": "table", "title": "جدول", "sql": "select 1"},
    {"kind": "bars", "title": "نمودار", "sql": "select 1"}, {"kind": "map", "title": "نقشه", "sql": "select 1"}],
    "reports": [{"key": "monthly", "title": "گزارش ماهانه", "subtitle": "زیرعنوان", "blocks": [1, 2, 4], "button": "دریافت PDF"}]}
POLY = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[[51, 35], [51.2, 35], [51.2, 35.2], [51, 35.2], [51, 35]]]}}
LINE = {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[51, 35], [51.3, 35.3]]}}
PT = {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [51.4, 35.7]}}
FC = {"type": "FeatureCollection", "features": [POLY, LINE, PT]}
BLOCKS = [{"kind": "kpi", "title": "تعداد", "value": "12", "unit": "ردیف", "error": "", "width": "third"},
          {"kind": "table", "title": "جدول", "headers": ["نام", "مقدار"], "rows": [["a<script>", 3.5], ["b", None]], "truncated": False, "error": ""},
          {"kind": "bars", "title": "نمودار", "bars": [{"label": "x", "value": "5", "pct": 100}], "error": ""},
          {"kind": "map", "title": "نقشه", "geojson": FC, "count": 3, "error": ""}]


def rep(**kw):
    return pagekit.parse_page("demo", {**PAGE, "reports": [{**PAGE["reports"][0], **kw}]}).reports[0]


class SpecTests(SimpleTestCase):
    def test_valid(self):
        r = pagekit.parse_page("demo", PAGE).reports[0]
        self.assertEqual((r.key, r.blocks, r.landscape, r.button), ("monthly", (1, 2, 4), False, "دریافت PDF"))
        self.assertTrue(rep(orientation="landscape").landscape)
        self.assertEqual(rep(blocks=[]).blocks, ())

    def test_rejections(self):
        for over in ({"blocks": [0]}, {"blocks": [9]}, {"blocks": [1, 1]}, {"blocks": ["a"]}, {"blocks": [True]}, {"orientation": "tilt"}, {"key": "Bad Key"}):
            with self.subTest(over=over), self.assertRaises(pagekit.SpecError):
                rep(**over)
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "reports": [PAGE["reports"][0]] * 2})


class SvgMapTests(SimpleTestCase):
    def test_draws_all_geometry_kinds_with_furniture(self):
        svg = reports.svg_map(FC)
        for part in ("<path", "<polyline", "<circle", "ش", "کیلومتر", "<line"):
            self.assertIn(part, svg)
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        nums = [float(x) for x in re.findall(r'(?:cx|cy|x1|x2)="(-?[\d.]+)"', svg)]
        self.assertTrue(all(-5 <= n <= reports.MAP_W + 5 for n in nums))  # داخل کادر

    def test_scale_label_is_clean(self):
        label = re.search(r'y="-7"[^>]*>([^<]*)<', reports.svg_map(FC)).group(1)
        self.assertRegex(label, r"^[۰-۹٫]+ (کیلومتر|متر)$")
        self.assertNotIn("٫۰ ", label)

    def test_single_point_and_degenerate_extent(self):
        self.assertIn("<circle", reports.svg_map({"features": [PT]}))

    def test_empty_and_garbage_return_empty(self):
        for fc in ({}, {"features": []}, {"features": [{"geometry": None}]}, {"features": [{"geometry": {"type": "Point", "coordinates": ["x", 1]}}]}):
            self.assertEqual(reports.svg_map(fc), "", fc)

    def test_multi_types_and_collection(self):
        fc = {"features": [{"geometry": {"type": "MultiPolygon", "coordinates": [POLY["geometry"]["coordinates"]]}},
                           {"geometry": {"type": "MultiPoint", "coordinates": [[51, 35], [52, 36]]}},
                           {"geometry": {"type": "GeometryCollection", "geometries": [LINE["geometry"]]}}]}
        svg = reports.svg_map(fc)
        self.assertEqual((svg.count("<path"), svg.count("<circle"), svg.count("<polyline")), (1 + 1, 2, 1))  # +۱ مسیر فلش شمال

    def test_vertex_budget_caps_output(self):
        big = {"features": [{"geometry": {"type": "LineString", "coordinates": [[51 + i * 1e-6, 35] for i in range(reports.MAX_VERTICES + 500)]}}]}
        self.assertLess(len(reports.svg_map(big)), 2_000_000)


class HtmlAndPdfTests(SimpleTestCase):
    def html(self, **kw):
        args = dict(report=rep(), page_title="صفحه", blocks=BLOCKS, site_name="ژئو", db_label="tehran", filters=["شهر: تهران"], now=timezone.now())
        return reports.build_html(**{**args, **kw})

    def test_content_jalali_persian_digits_and_escape(self):
        h = self.html()
        for part in ("گزارش ماهانه", "زیرعنوان", "۱۲", "tehran", "فیلترها: شهر: تهران", "<svg", "thead", "ش"):
            self.assertIn(part, h)
        self.assertNotIn("<script>", h)
        self.assertIn("a&lt;script&gt;", h)
        self.assertRegex(h, r"تاریخ گزارش: ۱[۳۴]\d\d/")  # تاریخ شمسی با رقم فارسی

    def test_hostile_titles_are_escaped(self):
        blocks = [{**BLOCKS[1], "title": '"><img src=x onerror=1>'}]
        h = self.html(blocks=blocks, db_label="<b>x</b>")
        self.assertNotIn("<img", h)
        self.assertNotIn("<b>x</b>", h)

    def test_error_block_shows_short_message(self):
        h = self.html(blocks=[{"kind": "table", "title": "t", "error": "خواندن داده ممکن نشد.", "width": "full"}])
        self.assertIn("خواندن داده ممکن نشد.", h)

    def test_fetcher_allows_only_bundled_fonts(self):
        f = reports.make_fetcher()
        for url in ("https://example.com/x.css", "file:///etc/passwd", "http://127.0.0.1/", "data:text/plain,hi", "https://fonts.report.invalid/other.ttf"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                f.fetch(url) if hasattr(f, "fetch") else f(url)
        r = f.fetch(reports.FONT_URL.format(w=400)) if hasattr(f, "fetch") else f(reports.FONT_URL.format(w=400))
        self.assertIsNotNone(r)
        self.assertGreater(len(reports._font(400)), 1000)

    def test_real_pdf_is_valid_with_persian_font(self):
        pdf = reports.to_pdf(self.html())
        self.assertTrue(pdf.startswith(b"%PDF-"))
        import shutil
        import subprocess
        import tempfile
        if shutil.which("pdffonts"):  # فونت فارسی جاسازی شد (نه DejaVu)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(pdf)
                f.flush()
                fonts = subprocess.run(["pdffonts", f.name], capture_output=True, text=True, check=True).stdout
            self.assertIn("Vazirmatn", fonts)
        self.assertGreater(len(pdf), 5000)

    def test_external_resources_in_html_are_not_fetched(self):
        evil = '<!doctype html><html><body><img src="https://attacker.invalid/x.png"><link rel="stylesheet" href="file:///etc/passwd"></body></html>'
        with mock.patch("urllib.request.urlopen") as net, mock.patch("socket.create_connection") as sock:
            self.assertTrue(reports.to_pdf(evil).startswith(b"%PDF-"))
        net.assert_not_called()
        sock.assert_not_called()

    def test_page_cap(self):
        many = "<p style='break-after:page'>x</p>" * (reports.MAX_PAGES + 2)
        with self.assertRaises(reports.ReportError) as cm:
            reports.to_pdf(f"<html><body>{many}</body></html>")
        self.assertIn("صفحه", str(cm.exception))

    def test_library_missing_is_generic_error(self):
        with mock.patch.dict("sys.modules", {"weasyprint": None}), self.assertRaises(reports.ReportError):
            reports.to_pdf("<p>x</p>")


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class ViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        self.page = pagekit.parse_page("demo", PAGE)
        for target, val in (("kernel.pagekit.get", lambda a, b: self.page if (a, b) == ("demo", "rep") else None),
                            ("kernel.pagekit.render_block", lambda ws, page, b, v: {**BLOCKS[[x.kind for x in page.blocks].index(b.kind)]})):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.url = reverse("kernel:report", args=[self.db.pk, "demo", "rep", "monthly"])

    def test_download_pdf_and_metering(self):
        r = self.client.get(self.url)
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(r.content.startswith(b"%PDF-"))
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertRegex(r["Content-Disposition"], r'filename="report-monthly-\d{8}\.pdf"')
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(PluginUsage.objects.get(metric="report_pdfs").count, 1)

    def test_only_selected_blocks_in_report(self):
        with mock.patch.object(reports, "build_html", wraps=reports.build_html) as bh:
            self.client.get(self.url)
        self.assertEqual([b["kind"] for b in bh.call_args.kwargs["blocks"]], ["kpi", "table", "map"])  # بلوک ۳ (نمودار) نیست

    def test_filters_are_passed_to_blocks(self):
        page = pagekit.parse_page("demo", {**PAGE, "params": [{"name": "city", "kind": "choice", "label": "شهر", "choices": [["a", "الف"], ["b", "ب"]]}]})
        with mock.patch("kernel.pagekit.get", lambda a, b: page), mock.patch.object(reports, "build_html", wraps=reports.build_html) as bh:
            self.client.get(self.url + "?city=b")
        self.assertEqual(bh.call_args.kwargs["filters"], ["شهر: b"])

    def test_rate_limit_and_cap(self):
        for _ in range(6):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(self.url).status_code, 302)  # سقف نرخ ← بازگشت با پیام
        cache.clear()
        with mock.patch("kernel.metering.check", return_value=(False, 5, 5)):
            self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_other_user_and_unknown_report_denied(self):
        self.assertEqual(self.client.get(reverse("kernel:report", args=[self.db.pk, "demo", "rep", "nope"])).status_code, 404)
        other = get_user_model().objects.create_user(username="x7", phone="09120000777", password="x")
        self.client.force_login(other)
        self.assertIn(self.client.get(self.url).status_code, (403, 404))

    def test_pdf_failure_redirects_with_message(self):
        with mock.patch.object(reports, "to_pdf", side_effect=reports.ReportError("ساخت PDF انجام نشد.")):
            r = self.client.get(self.url, follow=True)
        self.assertContains(r, "ساخت PDF انجام نشد.")

    def test_page_shows_report_button_with_filters(self):
        r = self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "rep"]) + "?x=1")
        self.assertContains(r, "دریافت PDF")
        self.assertContains(r, self.url + "?x=1")
