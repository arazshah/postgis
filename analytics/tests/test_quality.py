from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from analytics import quality, reports, services
from analytics.models import Event, Visit, Visitor


def make_visitor(n, when, source="direct", pages=1, user=None):
    v = Visitor.objects.create(vid=f"{n:032x}", first_source=source, first_medium="none", user=user)
    Visitor.objects.filter(pk=v.pk).update(first_seen=when)
    Visit.objects.create(visitor=v, source=source, pages=pages)
    return v


class BurstTests(TestCase):
    def setUp(self):
        self.base = (timezone.now() - timedelta(days=3)).replace(minute=5, second=0, microsecond=0)

    def test_burst_hour_is_flagged_but_real_visitors_are_not(self):
        n = 0
        for _ in range(15):  # موج: ۱۵ بازدید تک‌صفحه‌ای direct در یک ساعت
            n += 1
            make_visitor(n, self.base)
        for h in range(1, 7):  # ساعت‌های عادی: یکی در ساعت
            n += 1
            make_visitor(n, self.base + timedelta(hours=h))
        reader = make_visitor(900, self.base, pages=4)  # در همان ساعت ولی چند صفحه دیده
        campaign = make_visitor(901, self.base, source="linkedin")
        quality.refresh()
        flagged = Visitor.objects.filter(flag=Visitor.FLAG_BOT)
        self.assertEqual(flagged.count(), 15)
        for v in (reader, campaign):
            v.refresh_from_db()
            self.assertEqual(v.flag, "")

    def test_small_hourly_counts_are_never_a_burst(self):
        for i in range(8):
            make_visitor(i, self.base)
        quality.refresh()
        self.assertFalse(Visitor.objects.exclude(flag="").exists())

    def test_flagged_visitor_who_later_acts_is_released(self):
        vs = [make_visitor(i, self.base) for i in range(14)]
        quality.refresh()
        v = vs[0]
        v.refresh_from_db()
        self.assertEqual(v.flag, Visitor.FLAG_BOT)
        Event.objects.create(visitor=v, name=Event.OTP_REQUESTED)
        quality.refresh()
        v.refresh_from_db()
        self.assertEqual(v.flag, "")

    def test_reports_exclude_flagged_visitors(self):
        for i in range(14):
            make_visitor(i, self.base)
        make_visitor(500, self.base + timedelta(hours=5))
        steps = {s["label"]: s["n"] for s in reports.funnel(30)}
        self.assertEqual(steps["بازدیدکننده"], 15)  # funnel خودش برچسب نمی‌زند
        reports.build(30)  # build برچسب‌ها را به‌روز می‌کند
        steps = {s["label"]: s["n"] for s in reports.funnel(30)}
        self.assertEqual(steps["بازدیدکننده"], 1)
        self.assertEqual(quality.excluded_counts(30)["bot"], 14)


class InternalAccountTests(TestCase):
    def test_excluded_user_visitor_is_flagged_internal_and_not_counted(self):
        user = User.objects.create_user(phone="09121234567", analytics_exclude=True)
        self.client.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537")
        req = type("R", (), {"COOKIES": {"gp_vid": Visitor.objects.get().vid}, "META": {}, "path": "/x"})()
        services.attach_user(req, user, new_user=True)
        self.assertEqual(Visitor.objects.get().flag, Visitor.FLAG_INTERNAL)
        reports.build(30)
        self.assertEqual({s["label"]: s["n"] for s in reports.funnel(30)}["بازدیدکننده"], 0)

    def test_unmarking_account_releases_flag(self):
        user = User.objects.create_user(phone="09121234568", analytics_exclude=True)
        v = make_visitor(1, timezone.now(), user=user)
        quality.refresh()
        v.refresh_from_db()
        self.assertEqual(v.flag, Visitor.FLAG_INTERNAL)
        User.objects.filter(pk=user.pk).update(analytics_exclude=False)
        quality.refresh()
        v.refresh_from_db()
        self.assertEqual(v.flag, "")
