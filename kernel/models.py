"""مدل‌های سکو: سازمان (مشتری)، وضعیت پلاگین و مجوز دسترسی.

عمداً هیچ کلید خارجی به مدل‌های پلاگین‌ها ندارد (فضای کار، پلن): مجوزها با شناسه‌ی متنی به آن‌ها اشاره می‌کنند تا هسته به
هیچ پلاگینی وابسته نباشد و مهاجرت‌های هسته به مهاجرت پلاگین‌ها گره نخورد. پاک‌سازی مجوز فضای کار حذف‌شده با رویداد
`workspace.deleted` است.
"""
from django.conf import settings
from django.db import models


class Organization(models.Model):
    """مشتری سازمانی: چند کاربر که مجوزهای مشترک می‌گیرند (مثلاً پلاگین اختصاصی یک مجموعه)."""
    name = models.CharField("نام", max_length=150)
    slug = models.SlugField("شناسه", unique=True)
    note = models.TextField("یادداشت داخلی", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "سازمان مشتری"
        verbose_name_plural = "سازمان‌های مشتری"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrgMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "مدیر سازمان"
        MEMBER = "member", "عضو"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="members", verbose_name="سازمان")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships",
                             verbose_name="کاربر")
    role = models.CharField("نقش", max_length=6, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "عضو سازمان"
        verbose_name_plural = "اعضای سازمان"
        constraints = [models.UniqueConstraint(fields=["org", "user"], name="uniq_org_member")]

    def __str__(self):
        return f"{self.user} ← {self.org}"


class PluginState(models.Model):
    """وضعیت یک پلاگین: روشن/خاموش و باز برای همه یا محدود به دارندگان مجوز. نبودن ردیف = روشن و باز (پیش‌فرض)."""

    class Access(models.TextChoices):
        OPEN = "open", "باز (برای همه)"
        RESTRICTED = "restricted", "محدود (فقط دارندگان مجوز)"

    plugin_id = models.CharField("شناسه‌ی پلاگین", max_length=41, unique=True)
    enabled = models.BooleanField("روشن", default=True,
                                  help_text="خاموش یعنی منو، صفحه‌ها و آدرس‌های این پلاگین برای همه ناپدید می‌شود.")
    access = models.CharField("دسترسی", max_length=10, choices=Access.choices, default=Access.OPEN)
    note = models.TextField("یادداشت داخلی", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "وضعیت پلاگین"
        verbose_name_plural = "پلاگین‌ها"
        ordering = ["plugin_id"]

    def __str__(self):
        return self.plugin_id


class Entitlement(models.Model):
    """مجوز: چه کسی (همه، پلن، سازمان، کاربر یا یک فضای کار) به یک پلاگین محدود دسترسی دارد."""

    class Kind(models.TextChoices):
        ALL = "all", "همه"
        PLAN = "plan", "پلن"
        ORG = "org", "سازمان"
        USER = "user", "کاربر"
        WORKSPACE = "workspace", "فضای کار (پایگاه داده)"

    class Source(models.TextChoices):
        MANUAL = "manual", "اعطای دستی"
        PLAN = "plan", "همراه پلن"
        PURCHASE = "purchase", "خرید"
        TRIAL = "trial", "آزمایشی"

    state = models.ForeignKey(PluginState, on_delete=models.CASCADE, related_name="entitlements", verbose_name="پلاگین")
    kind = models.CharField("دارنده", max_length=10, choices=Kind.choices)
    subject = models.CharField("شناسه‌ی دارنده", max_length=64, blank=True,
                               help_text="شناسه‌ی عددی کاربر، سازمان یا پایگاه داده، یا شناسه‌ی (slug) پلن. برای «همه» خالی.")
    source = models.CharField("منبع", max_length=10, choices=Source.choices, default=Source.MANUAL)
    expires_at = models.DateTimeField("انقضا", null=True, blank=True, help_text="خالی یعنی بدون انقضا.")
    limits = models.JSONField("سقف‌ها", default=dict, blank=True,
                              help_text='مثلاً {"devices": 50}؛ پلاگین خودش می‌خواند.')
    note = models.CharField("یادداشت (مثلاً شماره‌ی قرارداد)", max_length=200, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="اعطاکننده")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مجوز"
        verbose_name_plural = "مجوزها"
        constraints = [models.UniqueConstraint(fields=["state", "kind", "subject"], name="uniq_entitlement")]

    def __str__(self):
        return f"{self.state_id}: {self.get_kind_display()} {self.subject}".strip()
