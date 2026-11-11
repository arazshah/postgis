"""ارائه‌دهنده‌ی تنظیم مدل زبانی کاربر برای هسته (kernel.llm)؛ در plugin.py ثبت می‌شود."""
from urllib.parse import urlsplit

from kernel import llm

from .models import LlmConfig


class AnalysisLlm(llm.Provider):
    def config(self, user):
        return LlmConfig.objects.filter(user=user).first()

    def save(self, user, base_url, model, key):
        url = (base_url or "").strip().rstrip("/")
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc:
            raise llm.LlmConfigError("آدرس سرویس باید با https شروع شود؛ مثلاً https://api.avalai.ir/v1")
        cfg = self.config(user)
        key = (key or "").strip()
        if not key and cfg is None:
            raise llm.LlmConfigError("کلید API را وارد کنید.")
        cfg = cfg or LlmConfig(user=user)
        cfg.base_url = url
        cfg.model = (model or "gpt-4o").strip()[:100]
        if key:
            cfg.set_key(key)
        cfg.save()
        return cfg
