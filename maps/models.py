"""
نقشه چندلایه: چند جدول مکانی یک پایگاه داده کنار هم، هر کدام با سبک خودش.

- لایه نقشه به «انتشار» جدول وابسته نیست و از سهمیه لایه‌های منتشرشده کم نمی‌کند؛ خود نقشه واحد انتشار است.
- کاشی هر لایه از آدرس همان نقشه سرو می‌شود: /maps/<slug>/t/<layer>/{z}/{x}/{y}.mvt
- در کاشی‌ها فقط ستون‌های پنجره اطلاعات، رنگ‌آمیزی و برچسب فرستاده می‌شوند (اگر پنجره اطلاعات خالی باشد همه ستون‌ها).
"""
from django.conf import settings
from django.db import models

from publish.models import _slug


class WebMap(models.Model):
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="maps",
                                 verbose_name="پایگاه داده")
    slug = models.SlugField("شناسه عمومی", unique=True, default=_slug)
    title = models.CharField("عنوان", max_length=120)
    description = models.TextField("توضیح", blank=True)
    is_public = models.BooleanField("عمومی (بدون کلید)", default=False)
    basemap = models.CharField("نقشه پایه", max_length=10, default="iran")
    view = models.JSONField("نمای شروع", default=dict, blank=True,
                            help_text="خالی یعنی محدوده همه لایه‌ها؛ وگرنه {center: [طول, عرض], zoom}.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "نقشه چندلایه"
        verbose_name_plural = "نقشه‌های چندلایه"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title} ({self.slug})"

    def bbox(self) -> list[float]:
        boxes = [x.bbox for x in self.layers.all() if x.bbox and len(x.bbox) == 4]
        if not boxes:
            return []
        return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


class MapLayer(models.Model):
    webmap = models.ForeignKey(WebMap, on_delete=models.CASCADE, related_name="layers", verbose_name="نقشه")
    schema = models.CharField(max_length=63, default="public")
    table = models.CharField(max_length=63)
    geom_column = models.CharField(max_length=63)
    srid = models.IntegerField(default=4326)
    geom_type = models.CharField(max_length=40, blank=True)
    title = models.CharField("عنوان", max_length=120, blank=True)
    position = models.PositiveIntegerField("ترتیب", default=0, help_text="کوچک‌تر یعنی بالاتر روی نقشه.")
    visible = models.BooleanField("روشن در شروع", default=True)
    style = models.JSONField("سبک", default=dict, blank=True)
    bbox = models.JSONField("محدوده (طول و عرض)", default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "لایه نقشه"
        verbose_name_plural = "لایه‌های نقشه"
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.webmap.title}: {self.table}"

    @property
    def database(self):
        return self.webmap.database

    @property
    def collection_id(self) -> str:
        return self.table if self.schema == "public" else f"{self.schema}.{self.table}"

    @property
    def display_title(self) -> str:
        return self.title or self.table

    @property
    def columns(self) -> list[str]:
        """ستون‌هایی که در کاشی‌ها می‌آیند؛ خالی یعنی همه (برای publish.engine)."""
        st = self.style or {}
        popup = [c for c in st.get("popup") or [] if isinstance(c, str)]
        if not popup:
            return []
        extra = [st.get(k) for k in ("field", "label") if st.get(k)]
        return list(dict.fromkeys(popup + extra))
