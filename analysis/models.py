"""تنظیم مدل زبانی هر کاربر (کلید خود کاربر، رمزنگاری‌شده) و تاریخچه پرسش‌های فارسی."""
from django.conf import settings
from django.db import models

from databases.crypto import decrypt, encrypt


class LlmConfig(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="llm_config")
    base_url = models.URLField("آدرس سرویس سازگار با OpenAI", default="https://api.avalai.ir/v1")
    model = models.CharField("مدل", max_length=100, default="gpt-4o-mini")
    api_key_encrypted = models.TextField(editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیم مدل زبانی کاربر"
        verbose_name_plural = "تنظیم‌های مدل زبانی کاربران"

    def set_key(self, raw: str):
        self.api_key_encrypted = encrypt(raw.strip())

    def get_key(self) -> str:
        return decrypt(self.api_key_encrypted)

    @property
    def key_hint(self) -> str:
        try:
            k = self.get_key()
        except ValueError:
            return "—"
        return f"…{k[-4:]}" if len(k) > 8 else "تنظیم شده"


class Question(models.Model):
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="questions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    text = models.TextField("پرسش")
    layers = models.JSONField("لایه‌ها", default=list)
    output_table = models.CharField("جدول نتیجه", max_length=63)
    job = models.OneToOneField("jobs.Job", on_delete=models.SET_NULL, null=True, related_name="question")
    goal = models.TextField(blank=True)
    operations = models.JSONField(default=list, blank=True)
    rows = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "پرسش فارسی"
        verbose_name_plural = "پرسش‌های فارسی"
        ordering = ["-created_at"]
