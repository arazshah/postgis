from django.db.models.signals import post_save
from django.dispatch import receiver

from databases.models import UserDatabase


@receiver(post_save, sender=UserDatabase)
def no_expiry(sender, instance, **kwargs):
    """دستگاه اعتبار زمانی ندارد: هر بار که ساخت/تمدید تاریخ انقضا می‌گذارد، بی‌درنگ برداشته می‌شود."""
    if instance.expires_at is not None:
        UserDatabase.objects.filter(pk=instance.pk).update(expires_at=None, expiry_warned_at=None)
        instance.expires_at = None
