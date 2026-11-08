"""درخواست دریافت تصویر ماهواره‌ای: برش از دروازه‌ی خارجی و ورود به سرویس رستر."""
import math
import secrets
from datetime import datetime

import jdatetime
from django.conf import settings
from django.db import models
from django.utils import timezone

from satgate.spec import PRODUCTS, satellite_of

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _token() -> str:
    return secrets.token_hex(16)


class SatRequest(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "در حال برش روی دروازه"
        DOWNLOADING = "downloading", "در حال دریافت و آماده‌سازی"
        READY = "ready", "آماده"
        FAILED = "failed", "ناموفق"

    PRODUCT_CHOICES = [(k, p.title) for k, p in PRODUCTS.items()]

    token = models.CharField(max_length=32, unique=True, default=_token, editable=False)
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="sat_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    product = models.CharField("محصول", max_length=20, choices=PRODUCT_CHOICES)
    scene_id = models.CharField("شناسه‌ی تصویر", max_length=120, blank=True)
    scene_date = models.CharField("تاریخ تصویر", max_length=25, blank=True)
    cloud = models.FloatField("ابر (٪)", null=True, blank=True)
    bbox = models.JSONField("محدوده", default=list)
    area_km2 = models.FloatField("مساحت (کیلومتر مربع)", default=0)
    est_bytes = models.BigIntegerField("حجم برآوردی", default=0)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.PROCESSING, db_index=True)
    message = models.TextField("پیام", blank=True)
    charged = models.BooleanField("از اعتبار کم شده", default=True)
    remote = models.JSONField("پاسخ دروازه", default=dict, blank=True)
    raster = models.ForeignKey("enterprise.Raster", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "درخواست تصویر ماهواره‌ای"
        verbose_name_plural = "درخواست‌های تصویر ماهواره‌ای"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["database", "charged", "created_at"], name="satreq_credit_idx")]

    def __str__(self):
        return self.title

    @property
    def spec(self):
        return PRODUCTS[self.product]

    @property
    def title(self) -> str:
        """مثلاً «شاخص گیاهی NDVI · ۱۴۰۵/۰۸/۰۶» (تاریخ تصویر شمسی)."""
        dt = self.scene_dt
        when = ""
        if dt:
            when = " · " + jdatetime.date.fromgregorian(date=dt.date()).strftime("%Y/%m/%d").translate(FA_DIGITS)
        return f"{self.spec.title}{when}"

    @property
    def satellite(self) -> str:
        return satellite_of(self.scene_id)[0]

    @property
    def agency(self) -> str:
        return satellite_of(self.scene_id)[1]

    @property
    def info(self) -> dict:
        """ویژگی‌های تصویر برای دیالوگ «ویژگی‌های تصویر» (مقدارهای خام؛ قالب‌بندی در مرورگر)."""
        r = self.raster
        dt = self.scene_dt
        return {
            "title": self.title, "satellite": self.satellite, "agency": self.agency, "product": self.spec.title,
            "date": jdatetime.date.fromgregorian(date=dt.date()).strftime("%Y/%m/%d").translate(FA_DIGITS) if dt else "",
            "cloud": self.cloud, "area": self.area_km2, "res": self.spec.res_m, "scene": self.scene_id,
            "bbox": self.bbox, "bands": r.bands if r else None, "dtype": r.dtype if r else "", "crs": r.crs if r else "",
            "size": r.size_bytes if r else None, "width": r.width if r else None, "height": r.height if r else None,
            "attribution": (r.meta or {}).get("attribution", "") if r else "",
            "created": jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.created_at)).strftime("%Y/%m/%d %H:%M")
            .translate(FA_DIGITS),
        }

    @property
    def scene_dt(self):
        try:
            return datetime.fromisoformat(self.scene_date.replace("Z", "+00:00")) if self.scene_date else None
        except ValueError:
            return None

    @property
    def tile(self) -> tuple[int, int, int]:
        """کاشی z/x/y که مرکز محدوده را می‌پوشاند؛ برای تصویر کوچک روی کارت."""
        w, s, e, n = self.bbox
        z = max(4, min(13, int(math.log2(360 / max(e - w, (n - s) * 1.5, 1e-4) / 1.2))))
        lon, lat = (w + e) / 2, max(min((s + n) / 2, 85), -85)
        x = int((lon + 180) / 360 * 2 ** z)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z)
        return z, x, y

    @property
    def active(self) -> bool:
        return self.status in (self.Status.PROCESSING, self.Status.DOWNLOADING)
