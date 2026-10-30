from django.db import migrations, models


def mark_owner_accounts(apps, schema_editor):
    """دو حساب سازنده (سازمان «آراز») که برای آزمون‌ها استفاده شده‌اند، از آمار بیرون بمانند؛ بقیه را مدیر در پنل علامت می‌زند."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_staff=False, organization="آراز").update(analytics_exclude=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_remove_bale_add_logo")]
    operations = [
        migrations.AddField(
            model_name="user", name="analytics_exclude",
            field=models.BooleanField(
                default=False, verbose_name="حساب داخلی (در آمار شمرده نشود)",
                help_text="حساب خودتان و تیم: بازدید و رویدادهای این کاربر از قیف و گزارش منابع ورود بیرون می‌ماند.")),
        migrations.RunPython(mark_owner_accounts, migrations.RunPython.noop),
    ]
