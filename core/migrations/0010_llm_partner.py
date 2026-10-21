from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_enamad_footer"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="llm_partner_enabled",
            field=models.BooleanField(
                default=False,
                help_text="برای کاربرانی که هنوز حساب سرویس مدل زبانی ندارند.",
                verbose_name="نمایش راهنمای «ساخت حساب مدل زبانی» در صفحه تحلیل",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="llm_partner_name",
            field=models.CharField(default="AvalAI", max_length=50, verbose_name="نام سرویس"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="llm_partner_url",
            field=models.URLField(
                blank=True,
                help_text="پیوند همکاری شما. کنار دکمه، یک جمله شفاف درباره همکاری در فروش نمایش داده می‌شود.",
                max_length=300,
                verbose_name="پیوند ثبت‌نام (همکاری در فروش)",
            ),
        ),
    ]
