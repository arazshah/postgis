from django.apps import AppConfig


class WinbackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "winback"
    verbose_name = "بازگشت کاربران"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from . import referrals

        user_logged_in.connect(referrals.attach, dispatch_uid="winback.referral.attach")
