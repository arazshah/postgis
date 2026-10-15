"""نواحی اداری ایران (از خود فایل OSM) برای انتخاب محدوده داده آماده."""
from django.db import models


class Area(models.Model):
    LEVELS = [("province", "استان"), ("county", "شهرستان"), ("city", "شهر")]

    name = models.CharField("نام", max_length=120)
    name_en = models.CharField("نام لاتین", max_length=120, blank=True)
    level = models.CharField("سطح", max_length=10, choices=LEVELS)
    province = models.CharField("استان", max_length=120, blank=True)
    osm_id = models.CharField(max_length=30, blank=True)
    population = models.BigIntegerField("جمعیت", null=True, blank=True)
    bbox = models.JSONField("محدوده")
    geometry = models.JSONField("مرز ساده‌شده (GeoJSON)")

    class Meta:
        verbose_name = "ناحیه ایران"
        verbose_name_plural = "نواحی ایران (از OSM)"
        ordering = ["level", "province", "name"]
        indexes = [models.Index(fields=["level", "name"])]

    def __str__(self):
        return f"{self.get_level_display()} {self.name}"

    @property
    def label(self) -> str:
        if self.level == "province":
            return f"استان {self.name}"
        suffix = f" — استان {self.province}" if self.province else ""
        return f"{self.get_level_display()} {self.name}{suffix}"

    @property
    def area_deg2(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])
