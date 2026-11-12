"""چیدمان قابل‌ویرایش گزارش: اعتبارسنجی، لوگو، تزریق، ویرایشگر (ذخیره، پیش‌نمایش، لوگو) و خروجی PDF/PNG."""
import io
import json
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from databases import services
from databases.tests.test_services import BaseCase
from kernel import entitlements, pagekit, reportlayout, reports
from kernel.models import ReportLayout
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES
from kernel.tests.test_reports import BLOCKS, PAGE, rep


def png(w=40, h=20, color=(200, 30, 30), fmt="PNG"):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, fmt)
    return b.getvalue()


def layout(**over):
    base = reportlayout.default_layout(rep(), 4)
    base.update(over)
    return base


class ValidateTests(SimpleTestCase):
    def test_default_layout_is_valid_and_roundtrips(self):
        d = reportlayout.default_layout(rep(), 4)
        self.assertEqual([e["type"] for e in d["elements"]], ["logo", "title", "meta", "divider", "block", "block", "block"])
        self.assertEqual([e["index"] for e in d["elements"] if e["type"] == "block"], [1, 2, 4])
        self.assertEqual(reportlayout.validate(d, 4)["elements"][1]["text"], "گزارش ماهانه")
        self.assertEqual(reportlayout.referenced_blocks(d), [1, 2, 4])

    def test_unknown_keys_are_dropped(self):
        d = reportlayout.default_layout(rep(), 4)
        d["elements"][1]["style"] = "x"
        d["elements"][1]["onclick"] = "alert(1)"
        d["evil"] = 1
        out = reportlayout.validate(d, 4)
        self.assertNotIn("style", out["elements"][1])
        self.assertNotIn("onclick", out["elements"][1])
        self.assertNotIn("evil", out)

    def test_rejections(self):
        good = reportlayout.default_layout(rep(), 4)

        def mod(i, **kw):
            d = json.loads(json.dumps(good))
            d["elements"][i].update(kw)
            return d
        bad = [mod(1, size="huge"), mod(1, color="#ff0000"), mod(1, color="red;}</style><script>"), mod(1, align="justify"), mod(1, text="x" * 300),
               mod(1, text=5), mod(4, index=0), mod(4, index=9), mod(4, height_mm=5000), mod(0, height_mm=True), mod(0, height_mm="9"),
               {**good, "elements": good["elements"] * 6}, {**good, "elements": [{"type": "iframe"}]}, {**good, "elements": "x"}, "x", None,
               {**good, "page": {**good["page"], "margin_mm": 99}}, {**good, "page": {**good["page"], "font_scale": 9}},
               {**good, "page": {**good["page"], "orientation": "tilted"}}, {**good, "page": {**good["page"], "page_numbers": "yes"}}]
        for d in bad:
            with self.subTest(d=str(d)[:80]), self.assertRaises(ValueError):
                reportlayout.validate(d, 4)

    def test_duplicate_and_bad_ids_are_renewed(self):
        d = {"page": {}, "elements": [{"id": "ab", "type": "divider"}, {"id": "ab", "type": "divider"}, {"id": "<x>", "type": "spacer"}]}
        ids = [e["id"] for e in reportlayout.validate(d, 1)["elements"]]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(re.fullmatch(r"[a-z0-9]{2,12}", i) for i in ids))

    def test_fill_placeholders_only_known(self):
        self.assertEqual(reportlayout.fill("{db} / {date} / {unknown} / {page}", {"db": "d", "date": "t", "page": "p"}), "d / t / {unknown} / p")


class LogoTests(SimpleTestCase):
    def test_png_and_jpeg_reencoded_and_shrunk(self):
        data, mime = reportlayout.process_logo(png(1200, 800))
        self.assertEqual(mime, "image/png")
        im = Image.open(io.BytesIO(data))
        self.assertLessEqual(max(im.size), reportlayout.LOGO_MAX_PX)
        data, mime = reportlayout.process_logo(png(100, 50, fmt="JPEG"))
        self.assertEqual(mime, "image/jpeg")

    def test_metadata_is_stripped(self):
        b = io.BytesIO()
        im = Image.new("RGB", (10, 10))
        from PIL.PngImagePlugin import PngInfo
        meta = PngInfo()
        meta.add_text("secret", "GPS-1234")
        im.save(b, "PNG", pnginfo=meta)
        self.assertNotIn(b"GPS-1234", reportlayout.process_logo(b.getvalue())[0])

    def test_rejects_non_images_svg_big_and_polyglots(self):
        for bad in (b"", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", b"GIF89a" + b"\0" * 20, b"not an image", b"\x89PNG\r\n\x1a\n" + b"x" * 30,
                    b"x" * (reportlayout.MAX_LOGO_BYTES + 1)):
            with self.subTest(bad=bad[:12]), self.assertRaises(ValueError):
                reportlayout.process_logo(bad)
        gif = io.BytesIO()
        Image.new("RGB", (4, 4)).save(gif, "GIF")
        with self.assertRaises(ValueError):
            reportlayout.process_logo(gif.getvalue())


class RenderTests(SimpleTestCase):
    def html(self, lay, **kw):
        args = dict(layout=lay, doc_title="t", page_title="صفحه", blocks=dict(enumerate(BLOCKS, 1)), site_name="ژئو", db_label="tehran", filters=[], now=timezone.now())
        return reports.build_html(**{**args, **kw})

    def test_custom_text_title_and_placeholders(self):
        lay = layout()
        lay["elements"].insert(2, {"id": "aa11", "type": "text", "text": "پایگاه {db} در {date}\n\nبند دوم", "align": "center", "size": "lg", "color": "accent", "bold": True})
        lay["elements"][1]["text"] = "عنوان من {site}"
        h = self.html(reportlayout.validate(lay, 4))
        for part in ("عنوان من ژئو", "پایگاه tehran در", "بند دوم", "text-align:center", "font-weight:700", "#B7791F"):
            self.assertIn(part, h)

    def test_element_order_and_removal(self):
        lay = reportlayout.validate(layout(), 4)
        lay["elements"] = [e for e in lay["elements"] if e["type"] != "meta"]
        lay["elements"].reverse()
        h = self.html(lay)
        self.assertNotIn('class="meta"', h)
        self.assertLess(h.index("نقشه"), h.index("جدول"))  # ترتیب برعکس

    def test_orientation_margin_scale_footer_and_page_numbers(self):
        lay = reportlayout.validate(layout(page={"orientation": "landscape", "margin_mm": 20, "font_scale": 1.2, "footer": "محرمانه {db}", "page_numbers": False}), 4)
        h = self.html(lay)
        for part in ("A4 landscape", "margin: 20mm", "font-size: 12pt", '"محرمانه tehran"'):
            self.assertIn(part, h)
        self.assertNotIn("counter(page", h)

    def test_footer_cannot_break_out_of_style(self):
        lay = reportlayout.validate(layout(page={"footer": '"}</style><script>alert(1)</script>{db}', "page_numbers": True}), 4)
        h = self.html(lay, db_label='x"}</style><img src=x>')
        self.assertEqual(h.count("</style>"), 1)
        self.assertNotIn("<script>", h)
        self.assertNotIn("<img", h)

    def test_text_html_is_escaped(self):
        lay = layout()
        lay["elements"].append({"id": "bb22", "type": "text", "text": "<img src=x onerror=alert(1)><b>x</b>", "align": "right", "size": "md", "color": "ink", "bold": False})
        h = self.html(reportlayout.validate(lay, 4))
        self.assertNotIn("<img", h)
        self.assertIn("&lt;img", h)

    def test_logo_only_when_available_and_pagebreak_spacer_divider(self):
        lay = reportlayout.validate(layout(), 4)
        lay["elements"] += [{"id": "cc33", "type": "pagebreak"}, {"id": "dd44", "type": "spacer", "height_mm": 12}]
        self.assertNotIn("<img", self.html(lay))
        h = self.html(lay, logo_src=reports.LOGO_URL)
        self.assertIn(f'src="{reports.LOGO_URL}"', h)
        self.assertIn('class="pb"', h)
        self.assertIn("height:12mm", h)
        self.assertIn("<hr", h)

    def test_preview_mode_adds_sheet_css(self):
        self.assertIn("box-shadow", self.html(reportlayout.validate(layout(), 4), preview=True))
        self.assertNotIn("box-shadow", self.html(reportlayout.validate(layout(), 4)))

    def test_real_pdf_with_logo_and_png_export(self):
        logo, mime = reportlayout.process_logo(png(120, 60))
        pdf = reports.to_pdf(self.html(reportlayout.validate(layout(), 4), logo_src=reports.LOGO_URL), logo=logo, logo_mime=mime)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        img = reports.pdf_to_png(pdf, 1)
        self.assertTrue(img.startswith(b"\x89PNG"))
        im = Image.open(io.BytesIO(img))
        self.assertGreater(im.width, 400)
        with self.assertRaises(reports.ReportError):
            reports.pdf_to_png(pdf, 99)
        self.assertGreaterEqual(reports.page_count(pdf), 1)


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class EditorViewTests(BaseCase):
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
        self.a = [self.db.pk, "demo", "rep", "monthly"]

    def u(self, name):
        return reverse(f"kernel:{name}", args=self.a)

    def post_json(self, name, body):
        return self.client.post(self.u(name), data=json.dumps(body), content_type="application/json")

    def test_editor_page_loads_with_layout_and_blocks(self):
        r = self.client.get(self.u("report_editor"))
        self.assertContains(r, 're-layout')
        self.assertContains(r, "re-list")
        self.assertContains(r, "report-editor.js")
        self.assertContains(r, self.u("report_save"))

    def test_save_then_export_uses_saved_layout(self):
        lay = layout()
        lay["elements"][1]["text"] = "عنوان اختصاصی کاربر"
        lay["elements"][1]["color"] = "accent"
        lay = reportlayout.validate(lay, 4)
        d = self.post_json("report_save", {"layout": lay}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(ReportLayout.objects.get().layout["elements"][1]["text"], "عنوان اختصاصی کاربر")
        with mock.patch.object(reports, "to_pdf", wraps=reports.to_pdf) as tp:
            r = self.client.get(self.u("report"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("عنوان اختصاصی کاربر", tp.call_args.args[0])

    def test_save_rejects_invalid_and_reset(self):
        r = self.post_json("report_save", {"layout": {"page": {}, "elements": [{"type": "iframe"}]}})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ReportLayout.objects.exists())
        self.assertEqual(self.client.post(self.u("report_save"), data="not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(self.u("report_save"), data="x" * 200_000, content_type="application/json").status_code, 400)
        self.post_json("report_save", {"layout": layout()})
        d = self.post_json("report_save", {"reset": True}).json()
        self.assertEqual(d["layout"]["elements"][1]["text"], "گزارش ماهانه")

    def test_preview_renders_unsaved_layout_with_strict_csp(self):
        lay = layout()
        lay["elements"][1]["text"] = "پیش‌نمایش آزمایشی"
        r = self.client.post(self.u("report_preview"), {"layout_json": json.dumps(reportlayout.validate(lay, 4))})
        self.assertContains(r, "پیش‌نمایش آزمایشی")
        self.assertIn("default-src 'none'", r["Content-Security-Policy"])
        self.assertNotIn("script-src", r["Content-Security-Policy"].replace("default-src 'none'", ""))
        self.assertFalse(ReportLayout.objects.exists())  # ذخیره نشد
        bad = self.client.post(self.u("report_preview"), {"layout_json": json.dumps({"elements": [{"type": "x"}]})})
        self.assertEqual(bad.status_code, 400)

    def test_logo_upload_validate_use_and_delete(self):
        ok = self.client.post(self.u("report_logo"), {"logo": SimpleUploadedFile("l.png", png(300, 100), "image/png")})
        self.assertTrue(ok.json()["has_logo"])
        row = ReportLayout.objects.get()
        self.assertTrue(bytes(row.logo).startswith(b"\x89PNG"))
        pv = self.client.post(self.u("report_preview"), {"layout_json": json.dumps(layout())})
        self.assertContains(pv, "data:image/png;base64,")
        with mock.patch.object(reports, "to_pdf", wraps=reports.to_pdf) as tp:
            self.client.get(self.u("report"))
        self.assertEqual(tp.call_args.kwargs["logo"], bytes(row.logo))
        for bad in (SimpleUploadedFile("x.svg", b"<svg onload=alert(1)/>", "image/svg+xml"), SimpleUploadedFile("x.png", b"not an image", "image/png")):
            self.assertEqual(self.client.post(self.u("report_logo"), {"logo": bad}).status_code, 400)
        self.assertEqual(self.client.post(self.u("report_logo"), {}).status_code, 400)
        self.assertFalse(self.client.post(self.u("report_logo"), {"do": "delete"}).json()["has_logo"])
        row.refresh_from_db()
        self.assertFalse(row.logo)

    def test_png_export_and_page_param(self):
        r = self.client.get(self.u("report_png"))
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/png"))
        self.assertTrue(r.content.startswith(b"\x89PNG"))
        self.assertIn(".png", r["Content-Disposition"])
        r = self.client.get(self.u("report_png") + "?page=99", follow=True)
        self.assertContains(r, "صفحه دارد")

    def test_other_user_cannot_edit_or_upload(self):
        other = get_user_model().objects.create_user(username="x8", phone="09120000888", password="x")
        self.client.force_login(other)
        for name in ("report_editor", "report_save", "report_preview", "report_logo"):
            r = self.client.post(self.u(name), data="{}", content_type="application/json")
            self.assertIn(r.status_code, (403, 404), name)
        self.assertFalse(ReportLayout.objects.exists())

    def test_preview_rate_limited(self):
        for _ in range(40):
            self.client.post(self.u("report_preview"), {"layout_json": json.dumps(layout())})
        self.assertEqual(self.client.post(self.u("report_preview"), {"layout_json": json.dumps(layout())}).status_code, 429)

    def test_workspace_delete_cleans_layout_and_logo(self):
        ReportLayout.objects.create(workspace_id=self.db.pk, plugin_id="demo", page="rep", key="monthly", layout={}, logo=b"x")
        entitlements.workspace_deleted(ws=self.db)
        self.assertFalse(ReportLayout.objects.exists())
