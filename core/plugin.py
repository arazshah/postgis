"""مانیفست پلاگین «سایت و تنظیمات» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import nav, plugins
from kernel import settings as site_settings

plugin = plugins.register("core", "سایت و تنظیمات", kind="system")

nav.admin_item("customers", "core.contactrequest", None, plugin=plugin.id, order=70)
nav.admin_item("settings", "core.sitesettings", None, plugin=plugin.id, order=10)
nav.admin_item("settings", "core.teammember", None, plugin=plugin.id, order=20)
nav.admin_item("settings", "core.trustitem", None, plugin=plugin.id, order=30)
nav.admin_badge("core.contactrequest", "core.plugin.new_contacts", plugin=plugin.id)

site_settings.tab("site", "سایت و برند", "globe", plugin=plugin.id, order=10)
site_settings.tab("home", "صفحه‌ی اول", "home", plugin=plugin.id, order=20)
site_settings.tab("users", "کاربران و کلاس", "users", plugin=plugin.id, order=30, status="core.settings_admin.users_status")
site_settings.tab("track", "آمار و اعتماد", "chart", plugin=plugin.id, order=70, status="core.settings_admin.track_status")
site_settings.tab("map", "نقشه و برداشت", "pin", plugin=plugin.id, order=90)
site_settings.section("site", "site", "سایت", plugin=plugin.id, order=10,
                      fields=("site_name", "logo_preview", "logo_file", "clear_logo", "tagline", "announcement", "announcement_level"))
site_settings.section("support", "site", "پشتیبانی", plugin=plugin.id, order=20,
                      fields=("support_phone", "support_telegram", "support_email"))
site_settings.section("home_trust", "home", "صفحه‌ی اول: بخش «داده‌ی شما مال شماست»", plugin=plugin.id, order=30,
                      fields=("home_trust_enabled", "home_trust_title", "home_trust_subtitle"),
                      description="عنوان و زیرعنوان این بخش را اینجا و کارت‌ها و دکمه‌هایش را در جدول‌های پایین همین زبانه ویرایش کنید؛ ترتیب با عدد «ترتیب» (کوچک‌تر = جلوتر) است. با برداشتن تیک «نمایش» ردیف پنهان می‌شود و با «حذف» برای همیشه پاک می‌شود. بخشی که هیچ کارت و دکمه‌ی فعالی ندارد نمایش داده نمی‌شود.")
site_settings.section("enamad", "track", "اینماد و نمادهای اعتماد", plugin=plugin.id, order=40,
                      fields=("enamad_status", "enamad_meta_content", "enamad_badge_html", "footer_badges_html"),
                      description="در پنل enamad.ir دو کد می‌دهند: «متاتگ تأیید مالکیت» که باید در head صفحه اصلی باشد (کادر اول)، و «کد نماد» که در فوتر نشان داده می‌شود (کادر دوم). نمادهای دیگر مثل ساماندهی را در کادر سوم بگذارید. بعد از ذخیره، سایت را باز کنید و فوتر را ببینید.")
site_settings.section("umami", "track", "آمار بازدید (Umami)", plugin=plugin.id, order=50,
                      fields=("umami_script_url", "umami_website_id"),
                      description="در Umami وب‌سایت postgis.ir را اضافه کنید، از Tracking code نشانی script و Website ID را اینجا بگذارید (یا کل تگ script را در کادر اول بچسبانید). اسکریپت فقط برای بازدیدکننده‌ها بارگذاری می‌شود، نه مدیران، و تنظیم «Do Not Track» مرورگر را رعایت می‌کند.")
site_settings.section("company", "site", "هویت شرکت و تماس", plugin=plugin.id, order=60,
                      fields=("about_intro", "contact_intro", "support_whatsapp", "support_hours", "company_name", "company_national_id", "company_economic_code", "show_company_info"),
                      description="متن صفحه‌های «درباره ما» و «تماس». شماره‌ی پشتیبانی همان «تلفن پشتیبانی» بالاست و پیامک اطلاع از درخواست‌های تماس به همان شماره می‌رود (به شرط پر بودن «شماره خط» در بخش پنل پیامک). اعضای تیم را از بخش «اعضای تیم» اضافه کنید. اطلاعات شرکت تا «نمایش اطلاعات شرکت» روشن نشود دیده نمی‌شود.")
site_settings.section("trust", "track", "اعتماد و محل داده", plugin=plugin.id, order=70,
                      fields=("trust_location_line", "trust_intro", "trust_disk_encrypted"),
                      description="ردیف‌های صفحه‌ی «امنیت و محل داده» را از بخش «ردیف‌های صفحه‌ی اعتماد» ویرایش کنید. جمله‌ی کوتاه محل داده در چند صفحه‌ی حساس نمایش داده می‌شود؛ فقط چیزی بنویسید که دقیقاً درست است.")
site_settings.section("footer", "site", "فوتر سایت", plugin=plugin.id, order=100,
                      fields=("footer_about", "footer_address", "footer_copyright", "footer_links", "social_telegram", "social_instagram", "social_linkedin", "social_github", "social_eitaa"),
                      description="تلفن، تلگرام و ایمیل پشتیبانی از بخش «پشتیبانی» بالا در فوتر نشان داده می‌شود. شبکه‌ای که آدرس نداشته باشد نمایش داده نمی‌شود.")
site_settings.section("users", "users", "کاربران و سرویس", plugin=plugin.id, order=110,
                      fields=("signup_open", "allow_new_databases", "max_databases_per_user", "renew_window_days", "expiry_warning_days", "expired_grace_days"))
site_settings.section("map_tiles", "map", "نقشه مرورگر پایگاه داده", plugin=plugin.id, order=140,
                      fields=("map_tile_url", "map_tile_attribution"))

admin_dash.attention("core.admin_cards.attention_leads", plugin=plugin.id, order=30)
admin_dash.attention("core.admin_cards.attention_closed", plugin=plugin.id, order=80)


def new_contacts() -> int:
    from .models import ContactRequest

    return ContactRequest.objects.filter(status=ContactRequest.Status.NEW).count()
