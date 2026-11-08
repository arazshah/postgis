"""درخواست دریافت تصویر ماهواره‌ای: برش از دروازه‌ی خارجی و ورود به سرویس رستر."""
import math
import secrets
from datetime import datetime

import jdatetime
from django.conf import settings
from django.db import models
from django.utils import timezone

from satgate.spec import INDICES, MISSIONS, PRODUCTS, get_product, satellite_of

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
    mission = models.CharField("ماهواره", max_length=12, default="sentinel2")
    mask = models.BooleanField("حذف ابر و سایه", default=False)
    composite = models.JSONField("ترکیب بی‌ابر (بازه و سقف‌ها)", null=True, blank=True, default=None)
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
        return get_product(self.mission, self.product)

    @property
    def title(self) -> str:
        """مثلاً «شاخص گیاهی NDVI · ۱۴۰۵/۰۸/۰۶» (تاریخ تصویر شمسی)؛ ترکیب: «… · ترکیب بی‌ابر تا ۱۴۰۵/۰۸/۰۶»."""
        dt = self.scene_dt
        when = ""
        if dt:
            when = " · " + jdatetime.date.fromgregorian(date=dt.date()).strftime("%Y/%m/%d").translate(FA_DIGITS)
        if self.composite:
            return f"{self.spec.title} · ترکیب بی‌ابر{when.replace(' · ', ' تا ', 1) if when else ''}"
        return f"{self.spec.title}{when}"

    @property
    def satellite(self) -> str:
        if self.composite:                       # ترکیب از چند تصویر یک ماهواره: نام ماموریت
            m = MISSIONS.get(self.mission)
            return m.title if m else ""
        return satellite_of(self.scene_id)[0]

    @property
    def agency(self) -> str:
        if self.composite:
            m = MISSIONS.get(self.mission)
            return m.agency if m else ""
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
            "mask": self.mask, "composite": bool(self.composite), "used": (self.remote or {}).get("used"),
            "period": self._period(),
            "created": jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.created_at)).strftime("%Y/%m/%d %H:%M")
            .translate(FA_DIGITS),
        }

    def _period(self) -> str:
        if not self.composite:
            return ""
        try:
            a, b = (jdatetime.date.fromgregorian(date=datetime.fromisoformat(self.composite[k]).date()).strftime("%Y/%m/%d")
                    .translate(FA_DIGITS) for k in ("start", "end"))
        except (KeyError, ValueError):
            return ""
        return f"{a} تا {b}"

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


class SatAnalysis(models.Model):
    """آمار هر ناحیه‌ی یک شاخص روی لایه‌ی چندضلعی (سری زمانی)؛ نتیجه در جدولی داخل پایگاه داده‌ی خود کاربر می‌نشیند."""

    class Status(models.TextChoices):
        PROCESSING = "processing", "در حال محاسبه"
        DOWNLOADING = "downloading", "در حال نوشتن جدول نتیجه"
        READY = "ready", "آماده"
        FAILED = "failed", "ناموفق"

    class Source(models.TextChoices):
        SATELLITE = "satellite", "تصویر ماهواره‌ای (دروازه)"
        RASTER = "raster", "رستر موجود (روی سرور ما)"

    token = models.CharField(max_length=32, unique=True, default=_token, editable=False)
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="sat_analyses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField("جدول نتیجه", max_length=63)
    layer = models.CharField("لایه‌ی چندضلعی", max_length=130)
    id_column = models.CharField("ستون شناسه", max_length=63)
    source = models.CharField("منبع", max_length=10, choices=Source.choices, default=Source.SATELLITE)
    mission = models.CharField("ماهواره", max_length=12, default="sentinel2")
    index = models.CharField("شاخص", max_length=8, default="ndvi")
    start = models.DateField("از", null=True, blank=True)
    end = models.DateField("تا", null=True, blank=True)
    max_cloud = models.FloatField("حداکثر ابر", default=40)
    mask = models.BooleanField("حذف ابر و سایه", default=True)
    raster = models.ForeignKey("enterprise.Raster", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    features = models.PositiveIntegerField("تعداد عارضه", default=0)
    area_km2 = models.FloatField("مساحت (کیلومتر مربع)", default=0)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.PROCESSING, db_index=True)
    message = models.TextField("پیام", blank=True)
    charged = models.BooleanField("از اعتبار کم شده", default=False)
    remote = models.JSONField("پاسخ دروازه", default=dict, blank=True)
    rows = models.PositiveIntegerField("ردیف نتیجه", default=0)
    scenes = models.JSONField("تصویرهای محاسبه‌شده", default=list, blank=True)
    monitor = models.ForeignKey("satellite.SatMonitor", null=True, blank=True, on_delete=models.SET_NULL, related_name="runs")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "تحلیل ماهواره‌ای"
        verbose_name_plural = "تحلیل‌های ماهواره‌ای"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["database", "charged", "created_at"], name="satan_credit_idx")]

    def __str__(self):
        return f"{self.index.upper()} · {self.layer}"

    @property
    def index_title(self) -> str:
        return INDICES[self.index][2] if self.index in INDICES else self.index

    @property
    def active(self) -> bool:
        return self.status in (self.Status.PROCESSING, self.Status.DOWNLOADING)

    @property
    def table_ref(self) -> str:
        return f"public.{self.name}"

    @property
    def latest_name(self) -> str:
        return f"{self.name}_latest"

    @property
    def mission_title(self) -> str:
        m = MISSIONS.get(self.mission)
        return m.title if m else self.mission


class SatMonitor(models.Model):
    """پایش خودکار: هر چند روز تصویر تازه‌ی بازه را برای قطعه‌ها بسنج و اگر افت محسوس بود هشدار بده."""

    class Freq(models.IntegerChoices):
        WEEKLY = 7, "هفتگی"
        BIWEEKLY = 14, "هر دو هفته"
        MONTHLY = 30, "ماهانه"

    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="sat_monitors")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField("نام پایش", max_length=80)
    layer = models.CharField("لایه‌ی چندضلعی", max_length=130)
    id_column = models.CharField("ستون شناسه", max_length=63)
    table_name = models.CharField("جدول نتیجه", max_length=63)
    mission = models.CharField("ماهواره", max_length=12, default="sentinel2")
    index = models.CharField("شاخص", max_length=8, default="ndvi")
    max_cloud = models.FloatField("حداکثر ابر", default=40)
    every_days = models.PositiveSmallIntegerField("هر چند روز", choices=Freq.choices, default=Freq.WEEKLY)
    drop_pct = models.PositiveSmallIntegerField("افت هشدار (٪)", default=20,
                                                help_text="اگر میانگین شاخص یک قطعه نسبت به تصویر قبلی این‌قدر درصد کم شود هشدار می‌دهد.")
    min_valid_pct = models.PositiveSmallIntegerField("حداقل پیکسل بی‌ابر (٪)", default=50)
    enabled = models.BooleanField("فعال", default=True)
    last_run_at = models.DateTimeField("آخرین بررسی", null=True, blank=True)
    last_scene_date = models.DateField("تاریخ آخرین تصویر پردازش‌شده", null=True, blank=True)
    last_alert_at = models.DateTimeField("آخرین هشدار", null=True, blank=True)
    last_message = models.CharField("نتیجه‌ی آخرین بررسی", max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "پایش ماهواره‌ای"
        verbose_name_plural = "پایش‌های ماهواره‌ای"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def index_title(self) -> str:
        return INDICES.get(self.index, (0, 0, self.index))[2]

    @property
    def mission_title(self) -> str:
        m = MISSIONS.get(self.mission)
        return m.title if m else self.mission
