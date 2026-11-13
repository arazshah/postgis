"""پیاده‌سازی قرارداد `kernel.ai` با همان تنظیم «دستیار سایت» (AvalAI و مشابه): سهمیه‌ی روزانه‌ی هر مدیر و ثبت مصرف (فقط شمارنده)."""
from __future__ import annotations

import time
from datetime import timedelta

from django.utils import timezone

from kernel import ai, conf

from . import llm
from .models import Usage

PURPOSE_MODE = "studio"
MAX_TOKENS = 3000


class StudioAi(ai.Provider):
    def _conf(self):
        from core.models import SiteSettings

        return SiteSettings.get()

    def available(self) -> bool:
        return bool(self._conf().assistant_key_ready)

    def cap(self) -> int:
        return int(conf.get("assistant", "studio_daily") or 0)

    def chat(self, user, purpose: str, messages: list[dict], max_tokens: int | None = None) -> str:
        site = self._conf()
        if not site.assistant_key_ready:
            raise ai.AiError("دستیار تنظیم نشده است؛ آدرس و کلید API را در تنظیمات سایت ← دستیار هوشمند بگذارید.")
        actor = f"u:{getattr(user, 'pk', 0)}"
        used = Usage.objects.filter(actor=actor, mode=PURPOSE_MODE, created_at__gte=timezone.now() - timedelta(days=1)).exclude(status=Usage.Status.ERROR).count()
        if used >= self.cap():
            raise ai.AiError("سقف روزانه‌ی دستیار استودیو برای شما تمام شد؛ فردا دوباره امتحان کنید یا سقف را در تنظیمات پلاگین «دستیار» بالا ببرید.")
        t0 = time.monotonic()
        row = Usage(user=user if getattr(user, "pk", None) else None, actor=actor, mode=PURPOSE_MODE, path=f"studio:{purpose}"[:200])
        try:
            out = llm.chat(site, messages, max_tokens=min(max_tokens or MAX_TOKENS, MAX_TOKENS))
        except llm.LLMError as exc:
            row.status, row.latency_ms = Usage.Status.ERROR, int((time.monotonic() - t0) * 1000)
            row.save()
            raise ai.AiError(str(exc)) from exc
        except ValueError as exc:  # کلید رمزنگاری‌شده خوانده نشد
            raise ai.AiError("کلید دستیار خوانده نشد؛ دوباره آن را در تنظیمات ذخیره کنید.") from exc
        row.answer_chars, row.latency_ms = len(out), int((time.monotonic() - t0) * 1000)
        row.save()
        return out
