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

conf.option(plugin.id, "ref_enabled", "برنامه‌ی «دوستت را بیاور»", kind="bool", default=False,
            help="روشن = هر کاربر لینک دعوت دارد و بعد از ساخت پایگاه توسط دوستش، هر دو پاداش می‌گیرند.")
conf.option(plugin.id, "ref_kind", "نوع پاداش دعوت", kind="choice", default="trial",
            choices=(("trial", "آزمایش رایگان یک پلاگین"), ("extend", "تمدید پایگاه"), ("coupon", "تخفیف مهلت‌دار")))
conf.option(plugin.id, "ref_plugin", "شناسه‌ی پلاگین پاداش (برای آزمایش رایگان)", kind="str", default="")
conf.option(plugin.id, "ref_days", "روزِ پاداش", kind="int", default=14, min=1, max=365)
conf.option(plugin.id, "ref_percent", "درصد تخفیف پاداش", kind="int", default=20, min=1, max=90)
conf.option(plugin.id, "ref_cap", "سقف پاداش ماهانه‌ی هر معرف", kind="int", default=10, min=1, max=100)

pricing.register("winback", "winback.coupons.quote", "winback.coupons.bind", plugin=plugin.id)
jobs.register_tick("winback", "winback.services.tick", plugin=plugin.id, order=70)

nav.admin_item("marketing", "winback.batch", None, plugin=plugin.id, order=14)
nav.admin_item("marketing", "winback.route", None, plugin=plugin.id, order=15)
nav.admin_item("marketing", "winback.message", None, plugin=plugin.id, order=16)
nav.admin_badge("winback.batch", "winback.services.pending_batches", plugin=plugin.id)

profile_sections.section("winback", "پیام‌ها و پیشنهادها", "winback/_profile.html", plugin=plugin.id, order=30,
                         context="winback.profile.context", actions=("winback_pref",), handle="winback.profile.handle")

profile_sections.section("invite", "دعوت دوستان", "winback/_invite.html", plugin=plugin.id, order=40,
                         context="winback.profile.invite_context")

nav.admin_item("marketing", "winback.referral", None, plugin=plugin.id, order=17)
