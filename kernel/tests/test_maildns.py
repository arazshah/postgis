"""بررسی SPF/DKIM/DMARC/MX: منطق قضاوت، خطای شبکه = «نامعلوم» (نه «رکورد نیست»)، ذخیره‌ی نتیجه، کارت داشبورد و اقدام پنل."""
import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from kernel import admin_cards, mail, maildns
from kernel.models import MailConfig

D = "postgis.ir"
GOOD = {
    D: ["v=spf1 mx include:_spf.chabokan.net ~all"],
    f"default._domainkey.{D}": ["v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEB"],
    f"_dmarc.{D}": ["v=DMARC1; p=quarantine; rua=mailto:d@postgis.ir"],
}


def fake(records, mx=("mail.postgis.ir",), exists=True):
    def txt(name):
        if isinstance(records.get(name), Exception):
            raise records[name]
        return records.get(name, [])
    return mock.patch.multiple(maildns, _txt=txt, _mx=lambda n: list(mx), _exists=lambda d: exists)


class JudgementTests(TestCase):
    def test_all_good(self):
        with fake(GOOD):
            checks = maildns.run(D)
        self.assertEqual([c.status for c in checks], ["ok"] * 4)
        self.assertEqual(maildns.overall(checks), "ok")

    def test_nothing_published_is_bad_with_fix_text(self):
        with fake({}, mx=()):
            checks = {c.key: c for c in maildns.run(D)}
        self.assertEqual((checks["spf"].status, checks["dmarc"].status, checks["mx"].status), ("bad", "bad", "warn"))
        self.assertEqual(checks["dkim"].status, "warn")  # selector نامعلوم
        self.assertIn("v=spf1", checks["spf"].fix)
        self.assertIn(f"_dmarc.{D}", checks["dmarc"].fix)
        self.assertEqual(maildns.overall(list(checks.values())), "bad")

    def test_nxdomain_reports_once_instead_of_everything_missing(self):
        with fake({}, exists=False):
            checks = maildns.run(D)
        self.assertEqual([(c.key, c.status) for c in checks], [("domain", "bad")])
        self.assertIn("NXDOMAIN", checks[0].detail)

    def test_spf_variants(self):
        cases = {
            "v=spf1 +all": "bad", "v=spf1 all": "bad", "v=spf1 ?all": "bad", "v=spf1 mx": "warn",
            "v=spf1 mx -all": "ok", "v=spf1 mx ~all": "ok",
        }
        for rec, want in cases.items():
            with fake({D: [rec]}):
                self.assertEqual(maildns.check_spf(D).status, want, rec)
        with fake({D: ["v=spf1 mx ~all", "v=spf1 a ~all"]}):
            self.assertEqual(maildns.check_spf(D).status, "bad")  # دو رکورد
        many = "v=spf1 " + " ".join(f"include:s{i}.example.com" for i in range(11)) + " ~all"
        with fake({D: [many]}):
            self.assertEqual(maildns.check_spf(D).status, "warn")

    def test_dkim_selector_given_vs_guessed(self):
        with fake(GOOD):
            self.assertEqual(maildns.check_dkim(D).status, "ok")
            self.assertEqual(maildns.check_dkim(D, "default").status, "ok")
            self.assertEqual(maildns.check_dkim(D, "other").status, "bad")  # selector مشخص ولی نیست
        with fake({f"s1._domainkey.{D}": ["v=DKIM1; p="]}):
            self.assertEqual(maildns.check_dkim(D, "s1").status, "bad")  # کلید باطل

    def test_dmarc_policy_levels(self):
        for rec, want in {"v=DMARC1; p=none": "warn", "v=DMARC1; p=reject": "ok", "v=DMARC1; rua=mailto:x@y.z": "bad"}.items():
            with fake({f"_dmarc.{D}": [rec]}):
                self.assertEqual(maildns.check_dmarc(D).status, want, rec)

    def test_network_error_is_unknown_not_missing(self):
        err = maildns.DnsError("Timeout")
        with fake({D: err, f"_dmarc.{D}": err}):
            self.assertEqual(maildns.check_spf(D).status, "warn")
            self.assertIn("ناموفق", maildns.check_spf(D).detail)
            self.assertEqual(maildns.check_dmarc(D).status, "warn")

    def test_domain_parsing_rejects_junk(self):
        self.assertEqual(maildns.domain_of("no-reply@PostGIS.ir"), "postgis.ir")
        for bad in ("", "x@", "x@localhost", "x@a b.ir", "x@-a.ir"):
            self.assertEqual(maildns.domain_of(bad), "", bad)


class StoredResultTests(TestCase):
    def setUp(self):
        self.cfg = mail.save_config(enabled=True, host="h", port=587, security="starttls", username="u", password="p",
                                    from_email="no-reply@postgis.ir")

    def test_refresh_stores_and_card_reflects(self):
        self.assertIn("بررسی نشده", admin_cards.mail_dns()[0]["text"])
        with fake({}, mx=()):
            maildns.refresh()
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.dns_status, "bad")
        item = admin_cards.mail_dns()[0]
        self.assertEqual(item["level"], "bad")
        self.assertIn("SPF", item["text"])
        with fake(GOOD):
            maildns.refresh()
        self.assertEqual(admin_cards.mail_dns(), [])

    def test_no_card_when_mail_disabled(self):
        MailConfig.objects.update(enabled=False)
        self.assertEqual(admin_cards.mail_dns(), [])

    def test_weekly_tick(self):
        now = timezone.now()
        with fake(GOOD):
            self.assertEqual(maildns.tick(now), "ok")
            self.assertEqual(maildns.tick(now + datetime.timedelta(days=1)), "تازه")
            self.assertEqual(maildns.tick(now + datetime.timedelta(days=8)), "ok")

    def test_tick_does_nothing_when_disabled(self):
        MailConfig.objects.update(enabled=False)
        self.assertEqual(maildns.tick(), "خاموش")


class AdminActionTests(TestCase):
    def test_action_runs_check_and_shows_result_in_form(self):
        U = get_user_model()
        su = U.objects.create_superuser("boss", password="x")
        self.client.force_login(su)
        cfg = mail.save_config(enabled=False, host="h", port=587, security="starttls", username="u",
                               from_email="no-reply@postgis.ir")
        with fake({}, mx=()):
            r = self.client.post(reverse("admin:kernel_mailconfig_changelist"),
                                 {"action": "check_dns", "_selected_action": [cfg.pk]}, follow=True)
        self.assertContains(r, "رکورد SPF پیدا نشد")
        page = self.client.get(reverse("admin:kernel_mailconfig_change", args=[cfg.pk]))
        self.assertContains(page, "v=spf1")
        self.assertContains(page, "dkim_selector")
