"""تمرین‌های کلاس: ساخت، تحویل دانشجو، نمره و برگشت برای اصلاح، صفحه ورود با کد (بدون نیاز به سرور PostGIS)."""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from classroom import services
from classroom.models import Assignment, Classroom, Contract, Enrollment, Submission
from databases.models import DatabaseServer, UserDatabase


@override_settings(ALLOWED_HOSTS=["testserver"])
class AssignmentTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.contract = Contract.objects.create(institution="دانشگاه آزمون", seats=5, starts_at=today - timedelta(days=1),
                                                ends_at=today + timedelta(days=60), teacher_phones="09120000061")
        self.teacher = User.objects.create_user("09120000061")
        self.c = services.create_class(self.teacher, self.contract, "کلاس آزمون", "empty", 5)
        server = DatabaseServer(name="x", host="127.0.0.1", port=5432, admin_user="postgres", sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password("x")
        server.save()
        self.student = User.objects.create_user("09120000062")
        self.other = User.objects.create_user("09120000063")
        db = UserDatabase.objects.create(owner=self.student, server=server, plan=services.class_plan(100),
                                         db_name="c_s62", role_name="c_s62_u", status="active")
        self.enr = Enrollment.objects.create(classroom=self.c, student=self.student, full_name="سارا احمدی",
                                             student_no="4001", database=db)

    def _make(self, **kw):
        data = {"title": "تمرین ۱", "body": "بافر ۵۰۰ متری", "max_score": "20", "due_days": "7", "is_published": "1"}
        data.update(kw)
        return services.save_assignment(self.c, data)

    # --- سرویس‌ها
    def test_save_validates_and_sets_due(self):
        a = self._make()
        self.assertTrue(a.is_published)
        self.assertEqual(timezone.localtime(a.due_at).date(), timezone.localdate() + timedelta(days=7))
        for bad in ({"title": " "}, {"max_score": "x"}, {"max_score": "0"}, {"due_days": "9999"}, {"due_date": "نادرست"}):
            with self.assertRaises(services.ClassError):
                self._make(**bad)
        b = services.save_assignment(self.c, {"title": "تمرین ۲", "due_days": "keep", "max_score": "۱۰"}, a)
        self.assertEqual((b.pk, b.max_score, b.due_at), (a.pk, 10, a.due_at))  # «keep» مهلت را نگه می‌دارد
        self.assertFalse(b.is_published)  # چک‌باکس نیامده
        self.assertIsNone(self._make(due_days="").due_at)

    def test_submit_grade_return_cycle(self):
        a = self._make()
        with self.assertRaisesMessage(services.ClassError, "پاسخ را بنویسید"):
            services.submit(a, self.enr, "", None)
        sub = services.submit(a, self.enr, "SELECT 1", None)
        self.assertEqual((sub.status, sub.is_late), ("submitted", False))
        # برگشت بدون توضیح، نمره‌ی خارج از سقف و نمره‌ی غیرعددی پذیرفته نمی‌شود
        with self.assertRaisesMessage(services.ClassError, "چه چیزی"):
            services.grade(sub, "return", "", " ")
        with self.assertRaisesMessage(services.ClassError, "بین"):
            services.grade(sub, "grade", "21", "")
        with self.assertRaisesMessage(services.ClassError, "عدد"):
            services.grade(sub, "grade", "abc", "")
        services.grade(sub, "return", "", "جدول خروجی را بسازید")
        sub.refresh_from_db()
        self.assertEqual(sub.status, "returned")
        sub = services.submit(a, self.enr, "CREATE TABLE hw1 AS SELECT 1", None)  # دوباره تحویل
        self.assertEqual(sub.status, "submitted")
        services.grade(sub, "grade", "۱۷٫۵", "عالی")
        sub.refresh_from_db()
        self.assertEqual((sub.status, sub.score_text), ("graded", "17.5"))
        with self.assertRaisesMessage(services.ClassError, "نمره"):  # بعد از نمره قفل است
            services.submit(a, self.enr, "تغییر", None)
        self.assertEqual(Submission.objects.count(), 1)

    def test_late_flag_and_foreign_map(self):
        a = self._make(due_days="")
        Assignment.objects.filter(pk=a.pk).update(due_at=timezone.now() - timedelta(hours=1))
        a.refresh_from_db()
        self.assertTrue(services.submit(a, self.enr, "دیر", None).is_late)
        with self.assertRaisesMessage(services.ClassError, "نقشه"):
            services.submit(a, self.enr, "x", "999999")

    def test_archived_class_is_closed(self):
        a = self._make()
        services.archive(self.c)
        with self.assertRaises(services.ClassError):
            services.submit(a, self.enr, "x", None)
        with self.assertRaises(services.ClassError):
            self._make(title="جدید")

    # --- صفحه‌ها
    def test_student_pages(self):
        a = self._make()
        hidden = self._make(title="پنهان", is_published="")
        self.client.force_login(self.student)
        r = self.client.get(reverse("classroom:join", args=[self.c.code]))
        self.assertContains(r, "تمرین ۱")
        self.assertNotContains(r, "پنهان")
        self.assertEqual(self.client.get(reverse("classroom:assignment", args=[self.c.code, hidden.pk])).status_code, 404)
        url = reverse("classroom:assignment", args=[self.c.code, a.pk])
        self.assertContains(self.client.get(url), "تحویل تمرین")
        r = self.client.post(url, {"note": "پاسخ من"}, follow=True)
        self.assertContains(r, "تحویل شد")
        self.assertEqual(Submission.objects.get().note, "پاسخ من")
        # غیر عضو کلاس دسترسی ندارد
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_teacher_flow(self):
        self.client.force_login(self.teacher)
        detail = reverse("classroom:detail", args=[self.c.pk])
        self.assertContains(self.client.get(detail), "هنوز تمرینی نساخته")
        self.client.post(detail, {"action": "assignment_save", "title": "تمرین ۱", "body": "شرح", "max_score": "20",
                                  "due_days": "3", "is_published": "1"})
        a = Assignment.objects.get()
        self.assertContains(self.client.get(detail), "بررسی تحویل‌ها")
        # ویرایش و پنهان‌کردن
        self.client.post(detail, {"action": "assignment_save", "assignment": a.pk, "title": "تمرین یک",
                                  "max_score": "10", "due_days": "keep"})
        a.refresh_from_db()
        self.assertEqual((a.title, a.max_score, a.is_published), ("تمرین یک", 10, False))
        self.client.post(detail, {"action": "assignment_toggle", "assignment": a.pk})
        a.refresh_from_db()
        self.assertTrue(a.is_published)
        sub = services.submit(a, self.enr, "پاسخ", None)
        review = reverse("classroom:assignment_review", args=[self.c.pk, a.pk])
        r = self.client.get(review)
        self.assertContains(r, "سارا احمدی")
        self.assertContains(r, "بررسی تحویل بعدی")
        grade = reverse("classroom:assignment_grade", args=[self.c.pk, a.pk, self.enr.pk])
        self.assertContains(self.client.get(grade), "پاسخ")
        r = self.client.post(grade, {"do": "grade", "score": "9", "feedback": "خوب"}, follow=True)
        sub.refresh_from_db()
        self.assertEqual((sub.status, sub.score_text), ("graded", "9"))
        self.assertContains(r, "نمره‌ی سارا احمدی ثبت شد")
        # خطای نمره پیام می‌دهد و نمره را عوض نمی‌کند
        r = self.client.post(grade, {"do": "grade", "score": "99"}, follow=True)
        self.assertContains(r, "نمره باید بین")
        # CSV
        csv = self.client.get(review, {"format": "csv"}).content.decode()
        self.assertIn("سارا احمدی", csv)
        self.assertIn("9", csv)
        self.assertIn("تمرین یک (از 10)", self.client.get(detail, {"format": "csv"}).content.decode())
        # پیش‌نمایش استاد
        self.assertContains(self.client.get(reverse("classroom:assignment", args=[self.c.code, a.pk])), "پیش‌نمایش استاد")
        # دانشجو نمره را می‌بیند
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("classroom:assignment", args=[self.c.code, a.pk])), "نمره‌ی شما")
        # استادِ کلاس دیگر دسترسی ندارد
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(review).status_code, 404)
        self.assertEqual(self.client.post(detail, {"action": "assignment_delete", "assignment": a.pk}).status_code, 404)
        self.client.force_login(self.teacher)
        self.client.post(detail, {"action": "assignment_delete", "assignment": a.pk})
        self.assertFalse(Assignment.objects.exists())

    def test_enter_by_code(self):
        self.client.force_login(self.other)
        url = reverse("classroom:enter")
        self.assertContains(self.client.get(url), "هنوز در کلاسی نیستید")
        self.assertContains(self.client.post(url, {"code": "ZZZZZZ"}), "پیدا نشد")
        r = self.client.post(url, {"code": f" {self.c.code.lower()} "})
        self.assertRedirects(r, reverse("classroom:join", args=[self.c.code]), fetch_redirect_response=False)
        self.client.force_login(self.student)
        r = self.client.get(url)
        self.assertContains(r, "کلاس آزمون")
        self.assertEqual(Classroom.objects.count(), 1)
