"""بخش «دستیار هوشمند» صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html


def tab_status(obj):
    return ("ok", "فعال") if obj.assistant_enabled and obj.assistant_key_ready else ("warn", "خاموش")


def assistant_status(obj):
    from kb import vectors

    if not obj.assistant_key_ready:
        return format_html('<b style="color:#b42318">کلید API وارد نشده</b>')
    try:
        total, done = vectors.stats(obj.assistant_embedding_model)
        sem = vectors.available()
    except Exception:
        total, done, sem = 0, 0, False
    state = "فعال" if obj.assistant_enabled else "کلید ذخیره شده، ولی دستیار خاموش است"
    color = "#1a7f4b" if obj.assistant_enabled else "#b54708"
    if sem:
        detail = f"جست‌وجوی معنایی: {done} از {total} تکه آماده"
    else:
        detail = "pgvector روی پایگاه داده پنل نیست؛ فقط جست‌وجوی کلیدواژه‌ای کار می‌کند"
    return format_html('<b style="color:{}">{}</b> — {}', color, state, detail)


def assistant_tools(obj):
    return format_html(
        '<a class="button" href="{}">آزمایش اتصال</a>&nbsp; <a class="button" href="{}">ساخت / به‌روزرسانی embedding</a>',
        reverse("admin:core_sitesettings_assistanttest"), reverse("admin:core_sitesettings_assistantembed"))


def test_view(request, model_admin):
    from . import llm

    conf = model_admin.model.get()
    if not conf.assistant_key_ready:
        messages.error(request, "اول کلید API را وارد و ذخیره کنید.")
        return
    try:
        res = llm.ping(conf)
    except llm.LLMError as exc:
        messages.error(request, f"آزمایش ناموفق بود: {exc}")
    else:
        messages.success(request, f"اتصال درست است: مدل embedding بُردار {res['dims']}بُعدی داد و مدل گفتگو پاسخ داد "
                                  f"(«{res['reply']}»).")


def embed_view(request, model_admin):
    from kb import embedding, vectors

    conf = model_admin.model.get()
    if not vectors.available() and not vectors.setup():
        messages.error(request, "افزونه pgvector روی پایگاه داده پنل نصب نیست؛ ایمیج panel-db باید "
                                "pgvector/pgvector:pg16 باشد. تا آن زمان دستیار با جست‌وجوی کلیدواژه‌ای کار می‌کند.")
        return
    res = embedding.embed_pending(conf)
    total, done = vectors.stats(conf.assistant_embedding_model)
    if res["error"]:
        messages.error(request, f"ساخت embedding کامل نشد ({res['embedded']} تکه انجام شد): {res['error']}")
    else:
        messages.success(request, f"{res['embedded']} تکه جدید ساخته شد؛ پوشش فعلی {done} از {total}.")
