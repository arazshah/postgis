from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.admin import TeamMemberForm, sniff_logo
from core.models import ContactRequest, SiteSettings, TeamMember, TrustItem


class PublicPagesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.conf = SiteSettings.get()

    def test_pages_render_for_anonymous(self):
        for name in ("core:about", "core:trust", "core:contact", "core:privacy", "core:terms", "core:home"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)

    def test_seed_data_present(self):
        self.assertTrue(TeamMember.objects.filter(name="آراز شاه کرمی").exists())
        self.assertGreaterEqual(TrustItem.objects.count(), 8)
        m = TeamMember.objects.get(name="آراز شاه کرمی")
        r = self.client.get(m.photo_url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")

    def test_trust_page_is_dynamic_and_honest(self):
        r = self.client.get(reverse("core:trust"))
        self.assertContains(r, "دیتاسنتر پارس‌پک")
        # تا قابلیت فعال نشده، ادعایش دیده نمی‌شود
        self.assertNotContains(r, "نسخه‌ی دوم بکاپ در فضای ابری")
        self.assertNotContains(r, "دیسک سرورها رمزنگاری‌شده است")
        TrustItem.objects.filter(title__startswith="سرورها در ایران").update(title="عنوان ویرایش‌شده")
        self.assertContains(self.client.get(reverse("core:trust")), "عنوان ویرایش‌شده")
        self.conf.trust_disk_encrypted = True
        self.conf.offsite_enabled, self.conf.offsite_endpoint = True, "https://s3.example.ir"
        self.conf.set_offsite_keys("a", "b")
        self.conf.save()
        r = self.client.get(reverse("core:trust"))
        self.assertContains(r, "نسخه‌ی دوم بکاپ در فضای ابری")
        self.assertContains(r, "دیسک سرورها رمزنگاری‌شده است")

    def test_inactive_item_and_unsafe_link_hidden(self):
        TrustItem.objects.create(title="پنهان", body="x", is_active=False)
        TrustItem.objects.create(title="لینک بد", body="x", link_label="برو", link_url="javascript:alert(1)")
        r = self.client.get(reverse("core:trust"))
        self.assertNotContains(r, "پنهان")
        self.assertNotContains(r, "javascript:")

    def test_company_info_hidden_until_enabled(self):
        self.conf.company_name, self.conf.company_national_id = "شرکت آزمون", "1234567890"
        self.conf.save()
        self.assertNotContains(self.client.get(reverse("core:about")), "شرکت آزمون")
        self.conf.show_company_info = True
        self.conf.save()
        self.assertContains(self.client.get(reverse("core:about")), "شرکت آزمون")
        self.assertContains(self.client.get(reverse("core:about")), "1234567890")

    def test_location_line_shown_and_hidden(self):
        self.assertContains(self.client.get(reverse("core:home")), "سرور در دیتاسنتر پارس‌پک")
        self.conf.trust_location_line = ""
        self.conf.save()
        self.assertNotContains(self.client.get(reverse("core:home")), "سرور در دیتاسنتر پارس‌پک")

    def test_inactive_member_hidden_and_photo_404(self):
        m = TeamMember.objects.create(name="همکار آزمون", is_active=False)
        self.assertNotContains(self.client.get(reverse("core:about")), "همکار آزمون")
        self.assertEqual(self.client.get(reverse("core:team_photo", args=[m.pk])).status_code, 404)

    def test_member_unsafe_links_dropped(self):
        m = TeamMember(name="x", linkedin="https://linkedin.com/in/x", website="javascript:alert(1)")
        self.assertEqual([label for label, _ in m.links], ["لینکدین"])

    def test_whatsapp_url(self):
        self.conf.support_whatsapp = "۰۹۳۹۷۵۲۶۶۵۷"
        self.assertEqual(self.conf.whatsapp_url, "https://wa.me/989397526657")
        self.conf.support_whatsapp = ""
        self.assertEqual(self.conf.whatsapp_url, "")

    def test_sitemap_lists_new_pages(self):
        body = self.client.get(reverse("core:sitemap")).content.decode()
        for name in ("core:about", "core:trust", "core:contact"):
            self.assertIn(reverse(name), body)

    def test_photo_form_rejects_svg_and_garbage(self):
        with self.assertRaises(ValidationError):
            sniff_logo(b"not an image")
        from django.core.files.uploadedfile import SimpleUploadedFile

        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'
        f = TeamMemberForm({"name": "x", "order": 1, "is_active": "on"},
                           {"photo_file": SimpleUploadedFile("a.svg", svg, "image/svg+xml")})
        self.assertFalse(f.is_valid())
        self.assertIn("photo_file", f.errors)


class ContactFormTests(TestCase):
    def setUp(self):
        cache.clear()

    def data(self, **kw):
        d = {"topic": "demo", "name": "علی رضایی", "phone": "۰۹۱۲۳۴۵۶۷۸۹", "organization": "شهرداری", "email": "",
             "preferred_time": "یکشنبه", "message": "سلام", "website": ""}
        d.update(kw)
        return d

    def test_submit_creates_lead_and_redirects(self):
        r = self.client.post(reverse("core:contact"), self.data())
        self.assertRedirects(r, reverse("core:contact") + "?sent=1")
        lead = ContactRequest.objects.get()
        self.assertEqual(lead.phone, "09123456789")
        self.assertEqual(lead.status, ContactRequest.Status.NEW)
        self.assertContains(self.client.get(reverse("core:contact") + "?sent=1"), "درخواست شما ثبت شد")

    def test_invalid_phone_and_missing_name(self):
        r = self.client.post(reverse("core:contact"), self.data(phone="123", name=""))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_honeypot_blocks_bots(self):
        self.client.post(reverse("core:contact"), self.data(website="http://spam"))
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_throttle_per_phone_and_ip(self):
        for _ in range(3):
            self.client.post(reverse("core:contact"), self.data())
        self.assertEqual(ContactRequest.objects.count(), 3)
        self.client.post(reverse("core:contact"), self.data())
        self.assertEqual(ContactRequest.objects.count(), 3)
        cache.clear()
        for i in range(6):
            self.client.post(reverse("core:contact"), self.data(phone=f"0912000000{i}"))
        self.assertEqual(ContactRequest.objects.count(), 3 + 5)

    def test_topic_prefill_from_query(self):
        r = self.client.get(reverse("core:contact") + "?topic=onprem")
        self.assertRegex(r.content.decode(), r'value="onprem"[^>]*checked')

    def test_admin_is_notified(self):
        from unittest import mock

        with mock.patch("core.alerts.notify_admins") as notify:
            self.client.post(reverse("core:contact"), self.data())
        notify.assert_called_once()
        self.assertIn("علی رضایی", notify.call_args[0][1])


class AdminIntegrationTests(TestCase):
    def setUp(self):
        from accounts.models import User

        self.client.force_login(User.objects.create_admin("boss2", "Str0ng-Admin-Pass"))

    def test_admin_pages_render(self):
        ContactRequest.objects.create(name="س", phone="09120000001")
        for url in ("/manage/", "/manage/core/sitesettings/", "/manage/core/teammember/", "/manage/core/trustitem/",
                    "/manage/core/contactrequest/"):
            self.assertEqual(self.client.get(url, follow=True).status_code, 200, url)

    def test_dashboard_flags_new_lead_and_missing_offsite(self):
        ContactRequest.objects.create(name="س", phone="09120000001")
        html = self.client.get("/manage/").content.decode()
        self.assertIn("درخواست تماس یا جلسه منتظر پیگیری", html)
        self.assertIn("فضای ابری جداگانه فعال نیست", html)

    def test_settings_has_backup_tab(self):
        html = self.client.get("/manage/core/sitesettings/", follow=True).content.decode()
        self.assertIn("ap-tab-backup", html)


class HomeTrustSectionTests(TestCase):
    """بخش «داده‌ی شما مال شماست» صفحه‌ی اول از تنظیمات سایت خوانده می‌شود."""

    def setUp(self):
        cache.clear()
        self.conf = SiteSettings.get()

    def test_seeded_section_matches_previous_content(self):
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, "داده‌ی شما مال شماست")
        self.assertContains(r, "هر لحظه ببرید")
        self.assertContains(r, "سرور در دیتاسنتر پارس‌پک، ایران.")
        self.assertContains(r, 'class="btn" href="/contact/"')
        self.assertContains(r, 'class="btn ghost" href="/trust/"')

    def test_texts_cards_and_buttons_are_editable(self):
        from core.models import HomeTrustButton, HomeTrustCard

        self.conf.home_trust_title, self.conf.home_trust_subtitle = "عنوان تازه", ""
        self.conf.save()
        HomeTrustCard.objects.filter(title="هر لحظه ببرید").update(is_active=False)
        HomeTrustCard.objects.create(site=self.conf, icon="bolt", title="کارت جدید", body="متن کارت", order=1)
        HomeTrustButton.objects.create(site=self.conf, label="دکمه بد", url="javascript:alert(1)")
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, "عنوان تازه")
        self.assertContains(r, "کارت جدید")
        self.assertNotContains(r, "هر لحظه ببرید")
        self.assertNotContains(r, "javascript:")
        self.assertNotContains(r, "بی‌پرده بگوییم")

    def test_location_card_hidden_without_location_and_section_can_be_disabled(self):
        self.conf.trust_location_line = ""
        self.conf.save()
        r = self.client.get(reverse("core:home"))
        self.assertNotContains(r, "محل داده مشخص است")
        self.assertNotContains(r, "{محل}")
        self.conf.home_trust_enabled = False
        self.conf.save()
        self.assertNotContains(self.client.get(reverse("core:home")), 'id="trust"')

    def test_admin_tab_edits_cards(self):
        from django.contrib.auth import get_user_model

        from core.models import HomeTrustCard

        admin = get_user_model().objects.create_superuser("boss", password="Boss-Pass-99")
        self.client.force_login(admin)
        url = reverse("admin:core_sitesettings_change", args=[1])
        r = self.client.get(url)
        self.assertContains(r, "ap-tab-home")
        self.assertContains(r, "home_cards-TOTAL_FORMS")
        card = HomeTrustCard.objects.order_by("order").first()
        from django.forms.models import model_to_dict

        data = {k: v for k, v in model_to_dict(self.conf).items() if v is not None and v is not False}
        cards = list(HomeTrustCard.objects.order_by("order", "id"))
        data.update({"home_cards-TOTAL_FORMS": len(cards), "home_cards-INITIAL_FORMS": len(cards),
                     "home_buttons-TOTAL_FORMS": 0, "home_buttons-INITIAL_FORMS": 0})
        for i, c in enumerate(cards):
            data.update({f"home_cards-{i}-id": c.pk, f"home_cards-{i}-site": 1, f"home_cards-{i}-icon": c.icon,
                         f"home_cards-{i}-title": c.title, f"home_cards-{i}-body": c.body,
                         f"home_cards-{i}-order": c.order, f"home_cards-{i}-is_active": "on"})
        data["home_cards-0-title"] = "از پنل عوض شد"
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302)
        card.refresh_from_db()
        self.assertEqual(card.title, "از پنل عوض شد")
