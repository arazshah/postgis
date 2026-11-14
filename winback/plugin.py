"""مانیفست پلاگین «بازگشت کاربران» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0012)."""
from kernel import conf, jobs, nav, plugins, pricing
from kernel import profile as profile_sections

plugin = plugins.register("winback", "بازگشت کاربران", kind="system", requires=("accounts",))

conf.option(plugin.id, "enabled", "ساخت فهرست و ارسال پیام بازگشت", kind="bool", default=False,
            help="سوئیچ کلی. خاموش = هیچ فهرستی ساخته نمی‌شود و چیزی نمی‌رود. ارسال همیشه بعد از تأیید مدیر است.")
conf.option(plugin.id, "control_percent", "درصد گروه کنترل", kind="int", default=10, min=0, max=50,
            help="این درصد از هر فهرست عمداً پیام نمی‌گیرد تا اثر واقعی پیام سنجیده شود.")
conf.option(plugin.id, "max_batch", "سقف هر فهرست روزانه", kind="int", default=300, min=10, max=5000)

conf.option(plugin.id, "coupon_hours", "مهلت کد تخفیف بازگشت (ساعت)", kind="int", default=72, min=6, max=720,
            help="از لحظه‌ی کلیک کاربر روی لینک پیامک؛ مهلت کوتاه حس فوریت می‌سازد.")

pricing.register("winback", "winback.coupons.quote", "winback.coupons.bind", plugin=plugin.id)
jobs.register_tick("winback", "winback.services.tick", plugin=plugin.id, order=70)

nav.admin_item("marketing", "winback.batch", None, plugin=plugin.id, order=14)
nav.admin_item("marketing", "winback.route", None, plugin=plugin.id, order=15)
nav.admin_item("marketing", "winback.message", None, plugin=plugin.id, order=16)
nav.admin_badge("winback.batch", "winback.services.pending_batches", plugin=plugin.id)

profile_sections.section("winback", "پیام‌ها و پیشنهادها", "winback/_profile.html", plugin=plugin.id, order=30,
                         context="winback.profile.context", actions=("winback_pref",), handle="winback.profile.handle")
