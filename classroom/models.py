"""پلن کلاس: قرارداد با دانشگاه یا آموزشگاه، کلاس‌های استاد و پایگاه داده هر دانشجو."""
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


class ContractRequest(models.Model):
    """درخواست همکاری از صفحه «پلن کلاس» (پیش از قرارداد)."""

    class Status(models.TextChoices):
        NEW = "new", "جدید"
        CONTACTED = "contacted", "تماس گرفته شد"
        SIGNED = "signed", "قرارداد بسته شد"
        REJECTED = "rejected", "منتفی"

    institution = models.CharField("دانشگاه یا آموزشگاه", max_length=200)
    name = models.CharField("نام و سمت", max_length=150)
    phone = models.CharField("موبایل", max_length=11)
    email = models.EmailField("ایمیل", blank=True)
    students = models.PositiveIntegerField("تعداد تقریبی دانشجو", default=30)
    term = models.CharField("ترم یا بازه", max_length=100, blank=True)
    course = models.CharField("درس", max_length=150, blank=True)
    message = models.TextField("توضیح", blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.NEW)
    admin_note = models.TextField("یادداشت مدیر", blank=True)
    created_at = models.DateTimeField("ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "درخواست پلن کلاس"
        verbose_name_plural = "درخواست‌های پلن کلاس"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.institution} — {self.name}"


class Contract(models.Model):
    """قرارداد امضاشده: تعداد صندلی (دانشجو) و بازه اعتبار؛ استادهای مجاز کلاس می‌سازند."""

    institution = models.CharField("دانشگاه یا آموزشگاه", max_length=200)
    number = models.CharField("شماره قرارداد", max_length=60, blank=True)
    seats = models.PositiveIntegerField("تعداد دانشجو (صندلی)", default=30)
    price_per_seat_toman = models.PositiveIntegerField("مبلغ هر دانشجو (تومان)", default=0)
    starts_at = models.DateField("شروع")
    ends_at = models.DateField("پایان ترم", help_text="پایگاه داده‌های دانشجویان در این روز بایگانی و غیرفعال می‌شوند.")
    quota_mb = models.PositiveIntegerField("حجم هر دانشجو (مگابایت)", default=500)
    teachers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="class_contracts", blank=True,
                                      verbose_name="استادها")
    teacher_phones = models.TextField("موبایل استادها", blank=True,
                                      help_text="هر خط یک شماره؛ با اولین ورود به حساب استاد وصل می‌شود.")
    request = models.ForeignKey(ContractRequest, null=True, blank=True, on_delete=models.SET_NULL,
                                verbose_name="درخواست مبدأ")
    notes = models.TextField("یادداشت", blank=True)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "قرارداد کلاس"
        verbose_name_plural = "قراردادهای کلاس"
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.institution} ({self.seats} نفر)"

    @property
    def used_seats(self) -> int:
        return Enrollment.objects.filter(classroom__contract=self).count()

    @property
    def free_seats(self) -> int:
        return max(0, self.seats - self.used_seats)

    @property
    def is_current(self) -> bool:
        today = timezone.localdate()
        return self.is_active and self.starts_at <= today <= self.ends_at

    @property
    def total_toman(self) -> int:
        return self.seats * self.price_per_seat_toman


class Classroom(models.Model):
    class Template(models.TextChoices):
        EMPTY = "empty", "پایگاه داده خالی با PostGIS"
        SAMPLE = "sample", "داده تمرینی تهران (مدارس، مترو، پارک)"
        OSM = "osm", "داده آماده یک شهر از OSM"

    class Status(models.TextChoices):
        ACTIVE = "active", "فعال"
        ARCHIVED = "archived", "بایگانی‌شده"

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="classrooms",
                                 verbose_name="قرارداد")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="taught_classes",
                                verbose_name="استاد")
    title = models.CharField("عنوان کلاس", max_length=150)
    code = models.CharField("کد ورود", max_length=8, unique=True, default=new_code)
    template = models.CharField("داده آغازین", max_length=10, choices=Template.choices, default=Template.SAMPLE)
    osm_area = models.ForeignKey("iranmap.Area", null=True, blank=True, on_delete=models.SET_NULL,
                                 verbose_name="شهر (برای داده OSM)")
    capacity = models.PositiveIntegerField("ظرفیت", default=30)
    is_open = models.BooleanField("ثبت‌نام باز است", default=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کلاس"
        verbose_name_plural = "کلاس‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def ends_at(self):
        return self.contract.ends_at


class Enrollment(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="enrollments",
                                  verbose_name="کلاس")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments",
                                verbose_name="دانشجو")
    full_name = models.CharField("نام دانشجو", max_length=120)
    student_no = models.CharField("شماره دانشجویی", max_length=30, blank=True)
    database = models.OneToOneField("databases.UserDatabase", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="enrollment", verbose_name="پایگاه داده")
    archive = models.ForeignKey("jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                verbose_name="بکاپ پایان ترم")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دانشجو"
        verbose_name_plural = "دانشجوها"
        ordering = ["full_name"]
        constraints = [models.UniqueConstraint(fields=["classroom", "student"], name="uniq_enrollment")]

    def __str__(self):
        return f"{self.full_name} در {self.classroom}"
