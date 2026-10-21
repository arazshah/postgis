from django.test import TestCase, override_settings

from accounts.models import User
from core.admin import SiteSettingsForm
from core.models import SiteSettings


def form_data(conf, **extra):
    """داده‌های اولیه فرم تنظیمات از روی مقدار فعلی؛ فقط فیلدهای ساده."""
    data = {}
    for name in SiteSettingsForm.base_fields:
        value = getattr(conf, name, None)
        if value is None or name in ("smsir_api_key", "bale_client_secret", "gateway_merchant"):
            continue
        if isinstance(value, bool):
            if value:
                data[name] = "on"
        else:
            data[name] = value
    data.update(extra)
    return data


class EnamadAdminFormTests(TestCase):
    def setUp(self):
        self.conf = SiteSettings.get()

    def form(self, **extra):
        return SiteSettingsForm(form_data(self.conf, **extra), instance=self.conf)

    def test_plain_value_and_full_meta_tag_both_accepted(self):
        f = self.form(enamad_meta_content="35683048")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["enamad_meta_content"], "35683048")
        f = self.form(enamad_meta_content='<meta name="enamad" content="35683048" />')
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["enamad_meta_content"], "35683048")

    def test_unsafe_meta_value_rejected(self):
        f = self.form(enamad_meta_content='x"><script>alert(1)</script>')
        self.assertFalse(f.is_valid())
        self.assertIn("enamad_meta_content", f.errors)

    def test_footer_links_validation(self):
        self.assertTrue(self.form(footer_links="حریم خصوصی | /terms/\nبلاگ | https://example.com/blog").is_valid())
        for bad in ("بدون جداکننده", "عنوان | javascript:alert(1)", "عنوان | //evil.example", " | /x/"):
            f = self.form(footer_links=bad)
            self.assertFalse(f.is_valid(), bad)
            self.assertIn("footer_links", f.errors)


@override_settings(ALLOWED_HOSTS=["testserver"])
class FooterAndHomeRenderTests(TestCase):
    def setUp(self):
        self.conf = SiteSettings.get()

    def test_defaults_render_without_enamad_or_badges(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn('name="enamad"', html)
        self.assertNotIn("foot-trust", html)
        self.assertIn("foot-grid", html)
        self.assertIn(self.conf.copyright_text, html)

    def test_enamad_meta_badge_and_footer_fields_render(self):
        self.conf.enamad_meta_content = "35683048"
        self.conf.enamad_badge_html = "<a href='https://trustseal.enamad.ir/?id=1&Code=x'><img alt='' src='https://trustseal.enamad.ir/logo.aspx?id=1&Code=x'></a>"
        self.conf.footer_badges_html = "<span id='other-badge'>نماد دیگر</span>"
        self.conf.footer_address = "تهران، خیابان نمونه"
        self.conf.footer_copyright = "© ۱۴۰۵ شرکت نمونه"
        self.conf.social_telegram = "https://t.me/example_channel"
        self.conf.footer_links = "حریم خصوصی | /terms/\nبد | javascript:alert(1)"
        self.conf.save()
        html = self.client.get("/").content.decode()
        head = html.split("</head>")[0]
        self.assertIn('<meta name="enamad" content="35683048">', head)
        self.assertIn("trustseal.enamad.ir/logo.aspx", html.split("<footer")[1])
        self.assertIn("other-badge", html)
        self.assertIn("تهران، خیابان نمونه", html)
        self.assertIn("© ۱۴۰۵ شرکت نمونه", html)
        self.assertIn('href="https://t.me/example_channel"', html)
        self.assertIn('href="/terms/">حریم خصوصی</a>', html)
        self.assertNotIn("javascript:alert", html)

    def test_meta_present_on_inner_pages_too(self):
        self.conf.enamad_meta_content = "35683048"
        self.conf.save()
        self.assertIn('<meta name="enamad" content="35683048">', self.client.get("/terms/").content.decode())

    def test_home_new_sections_and_assets(self):
        html = self.client.get("/").content.decode()
        for marker in ('id="demo-map"', 'id="features"', 'id="plans"', 'id="faq"', 'id="intro"',
                       "css/home.css", "js/home.js", "data-sticky-cta"):
            self.assertIn(marker, html)
        # h1 یکی و فقط یکی
        self.assertEqual(html.count("<h1"), 1)

    def test_home_for_logged_in_user_points_to_create(self):
        user = User.objects.create_user("09121234567", full_name="کاربر")
        self.client.force_login(user)
        html = self.client.get("/").content.decode()
        self.assertIn("ساخت پایگاه داده", html)
        self.assertNotIn("ساخت حساب رایگان", html.split('class="actions"')[1].split("</div>")[0])

    def test_admin_settings_page_shows_new_sections(self):
        User.objects.create_admin("admin", "Str0ng-Admin-Pass")
        self.client.login(username="admin", password="Str0ng-Admin-Pass")
        r = self.client.get("/manage/core/sitesettings/1/change/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "اینماد و نمادهای اعتماد")
        self.assertContains(r, "فوتر سایت")
        self.assertContains(r, "enamad_meta_content")


class EnamadSeedTests(TestCase):
    def test_model_helpers(self):
        conf = SiteSettings.get()
        conf.footer_links = "الف | /a/\nب | https://b.example\nج | javascript:x\nخراب"
        self.assertEqual(conf.footer_link_list, [("الف", "/a/"), ("ب", "https://b.example")])
        conf.social_github = "https://github.com/arazshah"
        self.assertEqual(conf.social_list, [("گیت‌هاب", "https://github.com/arazshah", "github")])
        self.assertTrue(conf.copyright_text.startswith("© "))
