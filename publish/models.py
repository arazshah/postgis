"""
انتشار لایه‌ها: کاشی برداری (Vector Tiles) و OGC API Features برای هر جدول مکانی.

- هر پایگاه داده یک «سرویس» با شناسه تصادفی دارد (آدرس OGC API)؛ نام دیتابیس در آدرس دیده نمی‌شود.
- لایه عمومی بدون کلید باز است؛ لایه خصوصی کلید API می‌خواهد.
- مجموع درخواست‌های هر پایگاه داده در روز سقف پلن را دارد.
"""
import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _slug(n: int = 10) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


class Service(models.Model):
    database = models.OneToOneField("databases.UserDatabase", on_delete=models.CASCADE, related_name="service",
                                    verbose_name="پایگاه داده")
    slug = models.SlugField("شناسه عمومی", unique=True, default=_slug)
    title = models.CharField("عنوان", max_length=120, blank=True)
    ows_password_encrypted = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "سرویس انتشار"
        verbose_name_plural = "سرویس‌های انتشار"

    def __str__(self):
        return self.slug


class Layer(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="layers", verbose_name="سرویس")
    slug = models.SlugField("شناسه عمومی", unique=True, default=_slug)
    schema = models.CharField(max_length=63, default="public")
    table = models.CharField(max_length=63)
    geom_column = models.CharField(max_length=63)
    srid = models.IntegerField(default=4326)
    geom_type = models.CharField(max_length=40, blank=True)
    title = models.CharField("عنوان", max_length=120, blank=True)
    description = models.TextField("توضیح", blank=True)
    is_public = models.BooleanField("عمومی (بدون کلید)", default=False)
    columns = models.JSONField("ستون‌های منتشرشده", default=list, blank=True,
                               help_text="خالی یعنی همه ستون‌ها به‌جز هندسه.")
    min_zoom = models.PositiveSmallIntegerField(default=0)
    max_zoom = models.PositiveSmallIntegerField(default=22)
    style = models.JSONField("سبک نقشه", default=dict, blank=True)
    bbox = models.JSONField("محدوده (طول و عرض)", default=list, blank=True)
    pk_column = models.CharField(max_length=63, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "لایه منتشرشده"
        verbose_name_plural = "لایه‌های منتشرشده"
        unique_together = [("service", "schema", "table")]
        ordering = ["schema", "table"]

    def __str__(self):
        return f"{self.table} ({self.slug})"

    @property
    def collection_id(self) -> str:
        return self.table if self.schema == "public" else f"{self.schema}.{self.table}"

    @property
    def display_title(self) -> str:
        return self.title or self.table

    @property
    def database(self):
        """برای publish.engine: هر چیزی که schema/table/geom_column/srid/columns و database دارد کاشی می‌شود."""
        return self.service.database


class ApiKey(models.Model):
    PREFIX = "gpk_"

    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="api_keys",
                                 verbose_name="پایگاه داده")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    name = models.CharField("نام", max_length=80)
    prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    can_write = models.BooleanField("اجازه نوشتن (REST API)", default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کلید API"
        verbose_name_plural = "کلیدهای API"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def digest(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, database, user, name: str, can_write: bool = False) -> tuple["ApiKey", str]:
        raw = cls.PREFIX + secrets.token_urlsafe(30)
        key = cls.objects.create(database=database, created_by=user, name=name[:80], prefix=raw[:12],
                                 key_hash=cls.digest(raw), can_write=can_write)
        return key, raw

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])


class DailyUsage(models.Model):
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="+")
    day = models.DateField()
    requests = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("database", "day")]
        verbose_name = "مصرف روزانه انتشار"
        verbose_name_plural = "مصرف روزانه انتشار"


class OwsProject(models.Model):
    """پروژه QGIS منتشرشده با QGIS Server (WMS و WFS)."""

    class Source(models.TextChoices):
        UPLOAD = "upload", "فایل آپلودی"
        DATABASE = "database", "ذخیره‌شده در پایگاه داده"

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="ows_projects",
                                verbose_name="سرویس")
    slug = models.SlugField("شناسه عمومی", unique=True, default=_slug)
    title = models.CharField("عنوان", max_length=120)
    source = models.CharField("منبع", max_length=10, choices=Source.choices, default=Source.UPLOAD)
    source_name = models.CharField("نام فایل یا پروژه", max_length=255, blank=True)
    source_schema = models.CharField(max_length=63, blank=True)
    xml = models.TextField("پروژه پاک‌شده (بدون رمز)", editable=False)
    layers = models.JSONField("لایه‌ها", default=list, blank=True)
    warnings = models.JSONField("هشدارها", default=list, blank=True)
    bbox = models.JSONField("محدوده (طول و عرض)", default=list, blank=True)
    is_public = models.BooleanField("عمومی (بدون کلید)", default=False)
    wfs_enabled = models.BooleanField("WFS فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پروژه WMS/WFS"
        verbose_name_plural = "پروژه‌های WMS/WFS"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.slug})"
