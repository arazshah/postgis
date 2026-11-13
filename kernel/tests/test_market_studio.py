"""بازار و نسخه‌ها در استودیو (ADR-0010 مرحله‌ی ۸): آگهی، تصویر، دسترسی، یادداشت، مقایسه، بازگشت و انتشار."""
import io
import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from billing.models import PluginAddon
from kernel import blueprint, entitlements, media_view, platform, release_diff
from kernel.models import PluginDraft, PluginMedia, PluginRelease
from kernel.tests.test_publish import cleanup_loaded

PID = "fleet"
TABLE = {"name": "fleet_pts", "columns": [{"name": "device", "type": "text", "label": "دستگاه"}, {"name": "lat", "type": "double", "label": "عرض"},
                                          {"name": "lon", "type": "double", "label": "طول"}, {"name": "at", "type": "timestamptz", "auto_now": True}]}


def spec():
    s = {"intro": {"summary": "پایش ناوگان"}, "tables": [TABLE], "pages": [], "code": {}, "access": {"mode": "public_free"}}
    return blueprint.apply(s, PID, {"op": "page.add", "title": "پایش", "subtitle": "x", "refresh": 15,
                                    "blocks": [{"kind": "kpi", "title": "تعداد", "table": "fleet_pts"}, {"kind": "ingest", "title": "دستگاه", "table": "fleet_pts"}]})


def png(w=400, h=300, fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 120, 110)).save(buf, fmt)
    return buf.getvalue()


class ListingOpTests(SimpleTestCase):
    def test_listing_set(self):
        s = blueprint.apply(spec(), PID, {"op": "listing.set", "category": "monitoring", "features": ["نقشه‌ی زنده", " ", "هشدار"], "details": " توضیح "})
        self.assertEqual(s["listing"], {"category": "monitoring", "features": ["نقشه‌ی زنده", "هشدار"], "details": "توضیح"})
        for bad in ({"category": "x"}, {"features": "a"}, {"features": ["a"] * 7}, {"features": ["a" * 81]}, {"details": "a" * 4001}):
            with self.assertRaises(blueprint.BlueprintError):
                blueprint.apply(spec(), PID, {"op": "listing.set", **bad})


class MediaTests(TestCase):
    def test_store_reencodes_and_limits(self):
        m = media_view.store(PID, png())
        self.assertEqual((m.content_type, m.width, m.height), ("image/webp", 400, 300))
        self.assertTrue(bytes(m.data).startswith(b"RIFF"))  # WebP بازرمزگذاری‌شده، نه بایت‌های ورودی
        big = media_view.store(PID, png(3000, 2000))
        self.assertLessEqual(big.width, 1280)
        media_view.store(PID, png(300, 200, "JPEG"))
        with self.assertRaises(media_view.MediaError):
            media_view.store(PID, png())  # سقف ۳ تصویر

    def test_rejections(self):
        for raw in (b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", png(100, 50), b"GIF89a" + b"\0" * 50, b"x" * (media_view.MAX_BYTES + 1)):
            with self.assertRaises(media_view.MediaError):
                media_view.store(PID, raw)
        self.assertEqual(PluginMedia.objects.count(), 0)

    def test_serve_is_public_and_hardened(self):
        m = media_view.store(PID, png())
        r = self.client.get(reverse("kernel:media", args=[m.token]))
        self.assertEqual((r.status_code, r["Content-Type"], r["X-Content-Type-Options"]), (200, "image/webp", "nosniff"))
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.assertEqual(self.client.get(reverse("kernel:media", args=["nope"])).status_code, 404)


class DiffTests(SimpleTestCase):
    def test_diff_lines(self):
        old = {"version": "1.0.0", "pages": {"p1": {"title": "پایش", "blocks": {"kpi": 1}, "parts": {"ingest": 1}}}, "tables": {"t_a": ["a", "b"]},
               "handlers": {"h": "aaa"}, "tests": {"h": 1}}
        new = {"version": "1.1.0", "pages": {"p1": {"title": "پایش", "blocks": {"kpi": 1, "map": 1}, "parts": {"ingest": 1, "forms": 1}}, "p2": {"title": "نو", "blocks": {"text": 1}, "parts": {}}},
               "tables": {"t_a": ["a", "c"], "t_b": ["x"]}, "handlers": {"h": "bbb", "g": "ccc"}, "tests": {"h": 2}}
        text = "\n".join(f"{x['kind']}:{x['text']}" for x in release_diff.diff(old, new))
        for frag in ("add:صفحه‌ی «نو»", "change:صفحه‌ی «پایش»: بلوک‌ها", "add:صفحه‌ی «پایش»: فرم از 0 به 1", "add:جدول «t_b»", "add:جدول «t_a»: ستون c", "remove:جدول «t_a»: ستون b",
                     "change:کد «h» تغییر کرد", "add:کد «g»", "change:آزمون‌های «h» از 1 به 2"):
            self.assertIn(frag, text)
        self.assertEqual(release_diff.diff(old, old), [])


@override_settings(ADMIN_2FA_REQUIRED=False)
class StudioMarketFlowTests(TestCase):
    def setUp(self):
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(cleanup_loaded)
        self.addCleanup(platform.invalidate)
        self.su = get_user_model().objects.create_superuser("mkroot", "Str0ng-Admin-Pass")
        self.client.force_login(self.su)
        self.d = PluginDraft.objects.create(plugin_id=PID, name="ناوگان", version="1.0.0", wizard=spec())

    def api(self, name, body=None, **kw):
        url = reverse(f"admin:kernel_plugindraft_api_{name}", args=[self.d.pk])
        if body is None:
            return self.client.get(url, kw)
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def paid(self):
        self.api("op", {"op": "listing.set", "category": "monitoring", "features": ["نقشه‌ی زنده", "هشدار توقف"], "details": "پایش لحظه‌ای"})
        r = self.api("access", {"access": {"mode": "public_paid", "price_toman": 90000, "duration_days": 30, "scope": "workspace", "trial_days": 7}})
        self.assertEqual(r.status_code, 200, r.content)

    def test_access_validation(self):
        for bad in ({}, {"mode": "public_paid", "price_toman": 0}, {"mode": "private", "targets": []}, {"mode": "private", "targets": [{"kind": "org", "subject": "999"}]}):
            self.assertEqual(self.api("access", {"access": bad}).status_code, 400, bad)
        self.paid()
        self.d.refresh_from_db()
        self.assertEqual(self.d.wizard["access"]["price_toman"], 90000)

    def test_media_endpoints(self):
        url = reverse("admin:kernel_plugindraft_api_media", args=[self.d.pk])
        r = self.client.post(url, {"file": SimpleUploadedFile("a.png", png(), content_type="image/png")}).json()
        self.assertEqual(len(r["media"]), 1)
        bad = self.client.post(url, {"file": SimpleUploadedFile("a.png", b"zzz", content_type="image/png")})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        r = self.api("media", {"delete": r["media"][0]["id"]}).json()
        self.assertEqual(r["media"], [])
        self.assertIn("media", self.api("state").json())

    def test_publish_carries_notes_spec_and_listing(self):
        self.paid()
        r = self.api("publish", {"notes": "نسخه‌ی نخست"}).json()
        self.assertTrue(r["active"], r)
        rel = PluginRelease.objects.get(plugin_id=PID)
        self.assertEqual((rel.version, rel.notes), ("1.0.0", "نسخه‌ی نخست"))
        self.assertEqual(rel.spec["listing"]["category"], "monitoring")
        addon = PluginAddon.objects.get(plugin_id=PID)
        self.assertEqual((addon.category, addon.features, addon.details, addon.price_toman), ("monitoring", ["نقشه‌ی زنده", "هشدار توقف"], "پایش لحظه‌ای", 90000))

    def test_publish_blocked_by_quality_blocker_and_by_stepup(self):
        self.d.wizard = {**spec(), "pages": []}
        self.d.save()
        r = self.api("publish", {"notes": ""})
        self.assertEqual(r.status_code, 400)
        self.assertIn("مانع انتشار", r.json()["error"])
        self.assertEqual(PluginRelease.objects.count(), 0)
        self.d.wizard = spec()
        self.d.save()
        from unittest import mock
        with mock.patch("kernel.studio_api.stepup.ok", return_value=False), mock.patch("kernel.studio_api.stepup.url", return_value="/s/"):
            r = self.api("publish", {})
        self.assertEqual((r.status_code, r.json()["stepup"]), (403, "/s/"))
        self.assertEqual(PluginRelease.objects.count(), 0)

    def test_versions_compare_rollback_restore(self):
        self.api("publish", {"notes": "اول"})
        self.api("op", {"op": "block.add", "page": "p1", "block": {"kind": "bars", "title": "هر دستگاه", "table": "fleet_pts", "label": "device"}})
        self.api("publish", {"notes": "دوم"})
        rels = self.api("releases").json()
        self.assertEqual([x["version"] for x in rels["releases"]], ["1.0.1", "1.0.0"])
        self.assertEqual([x["status"] for x in rels["releases"]], ["active", "retired"])
        self.assertEqual(rels["releases"][0]["notes"], "دوم")
        a, b = rels["releases"][1]["id"], rels["releases"][0]["id"]
        lines = self.api("compare", a=a, b=b).json()["lines"]
        self.assertTrue(any("بلوک‌ها" in x["text"] for x in lines))
        self.assertEqual(self.api("compare", a=b, b=b).json()["lines"], [])
        self.assertEqual(self.api("compare", a="x", b=b).status_code, 400)
        # پیش‌نویس فعلی نسبت به نسخه‌ی اول
        self.assertTrue(self.api("compare", a=a, b="draft").json()["lines"])
        # بازگشت به نسخه‌ی اول
        r = self.api("rollback", {"release": a}).json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(PluginRelease.objects.get(pk=a).status, "active")
        self.assertEqual(PluginRelease.objects.get(pk=b).status, "retired")
        # پیش‌نویس را به نقشه‌ی نسخه‌ی اول برگردان
        st = self.api("restore_release", {"release": a}).json()
        self.assertEqual(len(st["spec"]["pages"][0]["blocks"]), 2)
        self.assertEqual(self.api("restore_release", {"release": 99999}).status_code, 404)

    def test_restore_needs_spec_and_rollback_needs_permission(self):
        self.api("publish", {})
        rel = PluginRelease.objects.get(plugin_id=PID)
        PluginRelease.objects.filter(pk=rel.pk).update(spec={})
        self.assertEqual(self.api("restore_release", {"release": rel.pk}).status_code, 400)
        self.client.logout()
        u = get_user_model().objects.create_admin("mkstaff", "Str0ng-Admin-Pass", superuser=False)
        self.client.force_login(u)
        self.assertEqual(self.api("rollback", {"release": rel.pk}).status_code, 403)
