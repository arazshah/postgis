"""جدول‌هایی که مالک برای REST API باز کرده و فرم‌های جمع‌آوری میدانی روی آن‌ها."""
import secrets

from django.db import models


def _slug() -> str:
    return secrets.token_urlsafe(8).replace("-", "x").replace("_", "y").lower()[:10]


class ApiTable(models.Model):
    service = models.ForeignKey("publish.Service", on_delete=models.CASCADE, related_name="api_tables")
    schema = models.CharField(max_length=63, default="public")
    table = models.CharField(max_length=63)
    public_read = models.BooleanField("خواندن بدون کلید", default=False)
    can_insert = models.BooleanField("افزودن سطر", default=False)
    can_update = models.BooleanField("ویرایش سطر", default=False)
    can_delete = models.BooleanField("حذف سطر", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "جدول REST API"
        verbose_name_plural = "جدول‌های REST API"
        constraints = [models.UniqueConstraint(fields=["service", "schema", "table"], name="uniq_api_table")]
        ordering = ["schema", "table"]

    def __str__(self):
        return self.path

    @property
    def path(self) -> str:
        return self.table if self.schema == "public" else f"{self.schema}.{self.table}"


class FieldForm(models.Model):
    class Access(models.TextChoices):
        PUBLIC = "public", "همه (لینک عمومی)"
        TEAM = "team", "فقط اعضای تیم (با ورود)"

    api_table = models.ForeignKey(ApiTable, on_delete=models.CASCADE, related_name="forms")
    slug = models.SlugField(unique=True, default=_slug)
    title = models.CharField("عنوان فرم", max_length=120)
    intro = models.TextField("توضیح بالای فرم", blank=True)
    fields = models.JSONField("ستون‌ها", default=list)
    access = models.CharField("دسترسی", max_length=6, choices=Access.choices, default=Access.TEAM)
    is_open = models.BooleanField("باز است", default=True)
    submissions = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "فرم میدانی"
        verbose_name_plural = "فرم‌های میدانی"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
