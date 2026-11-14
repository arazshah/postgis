"""فاز ۳: دوستت را بیاور (لینک، نسبت‌دادن هنگام ورود، پاداش بعد از فعال‌شدن، سقف و ضد سوءاستفاده)."""
import datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases.models import DatabaseServer, Plan, UserDatabase
from kernel import conf, entitlements
from kernel.models import Entitlement
from kernel.plugins import registry
from winback import referrals
from winback.models import Coupon, InviteCode, Referral


class RefBase(TestCase):
    def setUp(self):
        for k, v in (("ref_enabled", True), ("ref_kind", "coupon"), ("ref_percent", 25)):
            conf.set_value("winback", k, v)
            self.addCleanup(conf.clear, "winback", k)
        self.addCleanup(entitlements.invalidate)
        server = DatabaseServer(name="s", host="h", public_host="x", is_default=True)
        server.set_admin_password("x")
        server.save()
        self.server, self.plan = server, Plan.objects.get(slug="free")
        self.ref = User.objects.create_user("09121110001")
        self.code = referrals.code_for(self.ref).code

    def new_friend(self, phone="09121110002"):
        self.client.logout()
        self.client.get(reverse("winback:invite", args=[self.code]))
        friend = User.objects.create_user(phone)
        self.client.force_login(friend)  # سیگنال ورود
        return friend

    def make_db(self, user, expires=None):
        return UserDatabase.objects.create(owner=user, server=self.server, plan=self.plan, label="d", db_name=f"d{user.pk}",
                                           role_name=f"r{user.pk}", status="active", expires_at=expires)


class AttachTests(RefBase):
    def test_invite_link_sets_session_and_goes_to_login(self):
        r = self.client.get(reverse("winback:invite", args=[self.code]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("utm_source=referral", r["Location"])
        self.assertEqual(self.client.session[referrals.SESSION_KEY], self.code)

    def test_unknown_code_404(self):
        self.assertEqual(self.client.get("/r/invite/nope/").status_code, 404)

    def test_new_user_login_creates_referral(self):
        friend = self.new_friend()
        r = Referral.objects.get(referred=friend)
        self.assertEqual(r.referrer, self.ref)
        self.assertNotIn(referrals.SESSION_KEY, self.client.session)

    def test_self_old_user_and_disabled_not_attributed(self):
        self.client.get(reverse("winback:invite", args=[self.code]))
        self.client.force_login(self.ref)  # خود معرف
        self.assertFalse(Referral.objects.exists())
        old = User.objects.create_user("09121110003")
        User.objects.filter(pk=old.pk).update(date_joined=timezone.now() - datetime.timedelta(days=3))
        self.client.get(reverse("winback:invite", args=[self.code]))
        self.client.force_login(User.objects.get(pk=old.pk))
        self.assertFalse(Referral.objects.exists())
        conf.set_value("winback", "ref_enabled", False)
        self.new_friend("09121110004")
        self.assertFalse(Referral.objects.exists())

    def test_staff_cannot_be_referred(self):
        self.client.get(reverse("winback:invite", args=[self.code]))
        self.client.force_login(User.objects.create_superuser(username="adm", password="x"))
        self.assertFalse(Referral.objects.exists())


class RewardTests(RefBase):
    def test_no_reward_before_database_then_both_rewarded_once(self):
        friend = self.new_friend()
        self.assertEqual(referrals.reward_due(), 0)  # هنوز پایگاه نساخته
        self.make_db(friend)
        with mock.patch("winback.referrals.workspace.notify_user") as notify:
            self.assertEqual(referrals.reward_due(), 1)
            self.assertEqual(notify.call_count, 2)
        self.assertEqual(referrals.reward_due(), 0)  # فقط یک بار
        self.assertEqual(Coupon.objects.filter(user=friend, percent=25).count(), 1)
        self.assertEqual(Coupon.objects.filter(user=self.ref, percent=25).count(), 1)
        self.assertEqual(referrals.stats(self.ref), {"invited": 1, "rewarded": 1})

    def test_monthly_cap_keeps_pending(self):
        conf.set_value("winback", "ref_cap", 1)
        self.addCleanup(conf.clear, "winback", "ref_cap")
        for phone in ("09121110010", "09121110011"):
            self.make_db(self.new_friend(phone))
        with mock.patch("winback.referrals.workspace.notify_user"):
            self.assertEqual(referrals.reward_due(), 1)
            self.assertEqual(referrals.reward_due(), 0)
        self.assertEqual(Referral.objects.filter(rewarded_at__isnull=True).count(), 1)

    def test_misconfigured_trial_without_plugin_rewards_nothing(self):
        conf.set_value("winback", "ref_kind", "trial")
        self.make_db(self.new_friend())
        self.assertEqual(referrals.reward_due(), 0)

    def test_trial_reward_grants_entitlements(self):
        pid = next(p.id for p in registry.plugins.values() if p.kind != "system")
        conf.set_value("winback", "ref_kind", "trial")
        conf.set_value("winback", "ref_plugin", pid)
        self.addCleanup(conf.clear, "winback", "ref_plugin")
        friend = self.new_friend()
        self.make_db(friend)
        with mock.patch("winback.referrals.workspace.notify_user"):
            referrals.reward_due()
        self.assertEqual(Entitlement.objects.filter(kind="user", source="trial").count(), 2)
        self.assertIn(friend.pk, [int(s) for s in Entitlement.objects.values_list("subject", flat=True)])

    def test_extend_skips_unlimited_database(self):
        conf.set_value("winback", "ref_kind", "extend")
        friend = self.new_friend()
        db = self.make_db(friend, expires=None)  # بدون انقضا: نباید انقضا بگیرد
        self.make_db(self.ref, expires=timezone.now() + datetime.timedelta(days=2))
        with mock.patch("winback.referrals.workspace.notify_user"):
            self.assertEqual(referrals.reward_due(), 1)  # معرف تمدید شد، دوست نه
        db.refresh_from_db()
        self.assertIsNone(db.expires_at)
        self.assertIn("جزئی", Referral.objects.get().note)


class ProfileTests(RefBase):
    def test_profile_shows_link_and_reward(self):
        self.client.force_login(self.ref)
        r = self.client.get(reverse("accounts:profile"))
        self.assertContains(r, f"/r/invite/{self.code}/")
        self.assertContains(r, "۲۵٪" if "۲۵٪" in r.content.decode() else "25٪")

    def test_disabled_shows_notice_without_code(self):
        conf.set_value("winback", "ref_enabled", False)
        User.objects.filter(pk=self.ref.pk).update()
        InviteCode.objects.all().delete()
        self.client.force_login(self.ref)
        self.assertContains(self.client.get(reverse("accounts:profile")), "فعلاً فعال نیست")
        self.assertFalse(InviteCode.objects.exists())
