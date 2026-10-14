import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.help import GROUPS, GUIDES
from databases.models import DatabaseServer

STATIC = Path(settings.BASE_DIR) / "static"


def jsonld(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


@override_settings(ALLOWED_HOSTS=["testserver"])
class HelpCenterTests(TestCase):
    def test_index_lists_every_guide_with_poster(self):
        r = self.client.get("/help/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for g in GUIDES:
            self.assertIn(f'href="/help/{g.slug}/"', html)
            self.assertIn(f"/static/help/video/{g.slug}.jpg", html)
        self.assertIn("/static/help/video/intro.mp4", html)
        graph = jsonld(html)[-1]["@graph"]
        items = next(x for x in graph if x["@type"] == "ItemList")["itemListElement"]
        self.assertEqual(len(items), len(GUIDES))

    def test_guide_page_has_video_steps_and_howto(self):
        for i, g in enumerate(GUIDES):
            r = self.client.get(f"/help/{g.slug}/")
            self.assertEqual(r.status_code, 200, g.slug)
            html = r.content.decode()
            self.assertIn(f"<h1>{g.title}</h1>", html)
            self.assertIn(f"/static/help/video/{g.slug}.mp4", html)
            self.assertIn('aria-current="page"', html)
            howto = next(x for x in jsonld(html)[-1]["@graph"] if x["@type"] == "HowTo")
            self.assertEqual(len(howto["step"]), len(g.steps))
            self.assertEqual(howto["video"]["duration"], g.iso_duration)
            if i + 1 < len(GUIDES):
                self.assertIn(f'href="/help/{GUIDES[i + 1].slug}/"', html)

    def test_unknown_guide_404(self):
        self.assertEqual(self.client.get("/help/nope/").status_code, 404)

    def test_guides_are_grouped_and_have_media_files(self):
        self.assertEqual({g.group for g in GUIDES}, set(GROUPS))
        self.assertEqual(len({g.slug for g in GUIDES}), len(GUIDES))
        for name in [*(g.slug for g in GUIDES), "intro"]:
            for ext in ("mp4", "jpg"):
                self.assertTrue((STATIC / "help" / "video" / f"{name}.{ext}").is_file(), f"{name}.{ext}")
        for g in GUIDES:
            self.assertGreater(g.seconds, 20)
            self.assertGreaterEqual(len(g.steps), 4)

    def test_nav_footer_sitemap_and_home_video(self):
        html = self.client.get("/").content.decode()
        self.assertIn('href="/help/"', html)
        self.assertIn('id="intro"', html)
        self.assertIn("/static/help/video/intro.mp4", html)
        sitemap = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("https://postgis.ir/help/", sitemap)
        for g in GUIDES:
            self.assertIn(f"https://postgis.ir/help/{g.slug}/", sitemap)


@override_settings(ALLOWED_HOSTS=["testserver"])
class CreatePreviewPortTests(TestCase):
    def test_preview_shows_server_public_port(self):
        s = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", public_port=5434, is_default=True)
        s.set_admin_password("secret")
        s.save()
        user = get_user_model().objects.create_user("09120000009")
        self.client.force_login(user)
        html = self.client.get("/dashboard/new/").content.decode()
        self.assertIn("<dd>5434</dd>", html)
        self.assertNotIn("<dd>5432</dd>", html)
