from django.db import migrations, models


class Migration(migrations.Migration):
    """کاربر سایت می‌تواند به‌جای موبایل با ایمیل و رمز عبور ثبت‌نام کند."""

    dependencies = [("accounts", "0005_analytics_exclude")]

    operations = [
        migrations.RemoveConstraint(model_name="user", name="user_has_username_or_phone"),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=(models.Q(username__isnull=False) | models.Q(phone__isnull=False)
                           | models.Q(email__isnull=False)),
                name="user_has_login_identity"),
        ),
    ]
