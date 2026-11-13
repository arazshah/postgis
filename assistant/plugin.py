"""مانیفست پلاگین «دستیار هوشمند» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import ai, conf, nav, plugins
from kernel import dash as admin_dash
from kernel import settings as site_settings

plugin = plugins.register("assistant", "دستیار هوشمند", kind="system", requires=("kb",))

nav.admin_item("support", "assistant.usage", None, plugin=plugin.id, order=60)

site_settings.tab("assistant", "دستیار هوشمند", "spark", plugin=plugin.id, order=60, status="assistant.settings_admin.tab_status")
site_settings.section("assistant", "assistant", "دستیار هوشمند (پرسش و پاسخ روی پایگاه دانش)", plugin=plugin.id, order=160,
                      fields=("assistant_enabled", "assistant_status", "assistant_base_url", "assistant_api_key", "clear_assistant_api_key", "assistant_chat_model", "assistant_embedding_model", "assistant_welcome", "assistant_member_daily", "assistant_guest_daily", "assistant_global_daily", "assistant_max_tokens", "assistant_tools"),
                      description="از سرویس‌های سازگار با OpenAI مثل AvalAI استفاده می‌شود: آدرس، کلید API و نام مدل را وارد کنید، ذخیره کنید، سپس «آزمایش اتصال» و «ساخت embedding» را بزنید. دستیار فقط از مقاله‌های پایگاه دانش جواب می‌دهد و به داده کاربران دسترسی ندارد. بعد از افزودن یا ویرایش مقاله‌ها، embedding هر ۱۰ دقیقه (با run_maintenance) خودکار به‌روز می‌شود.")
site_settings.display("assistant_status", "وضعیت دستیار", "assistant.settings_admin.assistant_status", plugin=plugin.id)
site_settings.display("assistant_tools", "ابزار دستیار", "assistant.settings_admin.assistant_tools", plugin=plugin.id)
site_settings.tool("assistanttest", "assistant-test/", "assistant.settings_admin.test_view", plugin=plugin.id)
site_settings.tool("assistantembed", "assistant-embed/", "assistant.settings_admin.embed_view", plugin=plugin.id)

admin_dash.health("assistant.admin_cards.health", plugin=plugin.id, order=60)

# هوش مصنوعی استودیوی پلاگین (docs/adr/0010): قرارداد هسته با همین تنظیم «دستیار سایت»
conf.option(plugin.id, "studio_daily", "سقف روزانه‌ی دستیار استودیوی پلاگین (برای هر مدیر)", kind="int", default=60, min=1, max=1000,
            help="هر درخواست به دستیار در استودیوی پلاگین یک واحد است؛ متن پرسش و پاسخ ذخیره نمی‌شود.")


def _install_ai():
    from .studio_ai import StudioAi

    ai.set_provider(StudioAi())


_install_ai()
