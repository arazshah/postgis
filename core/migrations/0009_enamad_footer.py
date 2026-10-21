from django.db import migrations, models

DEFAULT_ABOUT = "پایگاه داده مکانی PostGIS آماده برای WebGIS، QGIS و GeoServer؛ ساخته‌شده برای جامعه GIS ایران."


def seed_enamad(apps, schema_editor):
    """کد تأیید اینماد این سایت که پیش‌تر اعلام شده بود؛ فقط اگر ردیف تنظیمات هست و خالی است."""
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(pk=1, enamad_meta_content="").update(enamad_meta_content="35683048")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_class_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="enamad_meta_content",
            field=models.CharField(
                blank=True, max_length=100,
                help_text="فقط مقدار content (مثلاً 35683048) را بنویسید؛ چسباندن کل تگ متای اینماد هم کار می‌کند. "
                          "در بخش head همه صفحه‌ها گذاشته می‌شود.",
                verbose_name="کد تأیید مالکیت اینماد (متاتگ)"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="enamad_badge_html",
            field=models.TextField(
                blank=True,
                help_text="کد HTML نماد را از پنل enamad.ir کپی و همان‌طور که هست اینجا بچسبانید. در فوتر نمایش داده می‌شود.",
                verbose_name="کد نماد اینماد (برای فوتر)"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="footer_badges_html",
            field=models.TextField(
                blank=True,
                help_text="کد نماد ساماندهی، زرین‌پال، سازمان نظام صنفی رایانه‌ای و مانند آن. "
                          "هر کد HTML که بگذارید بدون تغییر در فوتر اجرا می‌شود؛ فقط کد معتبر و مطمئن بگذارید.",
                verbose_name="سایر نمادها و کدها (فوتر)"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="footer_about",
            field=models.TextField(blank=True, default=DEFAULT_ABOUT, verbose_name="متن معرفی زیر نام سایت"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="footer_address",
            field=models.TextField(blank=True, verbose_name="نشانی (اختیاری)"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="footer_copyright",
            field=models.CharField(
                blank=True, max_length=200,
                help_text="خالی = «© {سال} {نام سایت}». می‌توانید نام شرکت یا شماره ثبت را هم بنویسید.",
                verbose_name="متن حق نشر"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="footer_links",
            field=models.TextField(
                blank=True,
                help_text="هر خط یک پیوند، به شکل «عنوان | آدرس»؛ مثلاً: حریم خصوصی | /terms/ . "
                          "آدرس باید با / یا https:// شروع شود.",
                verbose_name="پیوندهای دلخواه فوتر"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="social_instagram",
            field=models.URLField(blank=True, verbose_name="اینستاگرام"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="social_telegram",
            field=models.URLField(blank=True, verbose_name="کانال تلگرام"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="social_linkedin",
            field=models.URLField(blank=True, verbose_name="لینکدین"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="social_github",
            field=models.URLField(blank=True, verbose_name="گیت‌هاب"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="social_eitaa",
            field=models.URLField(blank=True, verbose_name="ایتا"),
        ),
        migrations.RunPython(seed_enamad, migrations.RunPython.noop),
    ]
