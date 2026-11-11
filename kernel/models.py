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


class PluginSetting(models.Model):
    """مقدار یک گزینه‌ی اعلام‌شده‌ی پلاگین (kernel.conf). گزینه‌ی secret رمزنگاری‌شده است."""

    plugin_id = models.CharField("پلاگین", max_length=41)
    key = models.CharField("کلید", max_length=60)
    value = models.TextField("مقدار", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیم پلاگین"
        verbose_name_plural = "تنظیمات پلاگین"
        constraints = [models.UniqueConstraint(fields=["plugin_id", "key"], name="uniq_plugin_setting")]

    def __str__(self):
        return f"{self.plugin_id}.{self.key}"


class PluginUsage(models.Model):
    """شمارنده‌ی روزانه‌ی مصرف پلاگین به‌ازای (معیار، فضای کار، کاربر)؛ ۰ یعنی «بدون فضای کار/کاربر». kernel.metering."""

    plugin_id = models.CharField("پلاگین", max_length=41)
    metric = models.CharField("معیار", max_length=40)
    day = models.DateField("روز")
    workspace_id = models.PositiveIntegerField("پایگاه داده", default=0)
    user_id = models.PositiveIntegerField("کاربر", default=0)
    count = models.BigIntegerField("تعداد", default=0)

    class Meta:
        verbose_name = "مصرف پلاگین"
        verbose_name_plural = "مصرف پلاگین‌ها"
        ordering = ["-day", "plugin_id", "metric"]
        constraints = [models.UniqueConstraint(fields=["plugin_id", "metric", "day", "workspace_id", "user_id"],
                                               name="uniq_plugin_usage")]
        indexes = [models.Index(fields=["plugin_id", "metric", "day"], name="plugin_usage_lookup")]

    def __str__(self):
        return f"{self.plugin_id}.{self.metric} {self.day}: {self.count}"


class PluginDraft(models.Model):
    """پیش‌نویس پلاگین در استودیوی پنل مدیریت؛ امضا ندارد و فعال نمی‌شود، فقط به بسته‌ی بدون امضا تبدیل می‌شود (kernel.studio)."""

    plugin_id = models.CharField("شناسه‌ی پلاگین", max_length=41, unique=True)
    name = models.CharField("نام", max_length=120)
    version = models.CharField("نسخه", max_length=20, default="0.1.0")
    kind = models.CharField("نوع", max_length=10, default="custom")
    requires = models.CharField("نیازمندی‌ها (با ویرگول)", max_length=200, blank=True)
    readme = models.TextField("شرح", blank=True)
    pages = models.JSONField("صفحه‌ها", default=dict, blank=True, help_text="کلید صفحه ← متن TOML")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پیش‌نویس پلاگین"
        verbose_name_plural = "استودیوی پلاگین"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.plugin_id})"


class PluginAlertState(models.Model):
    """وضعیت اجرای هشدار دوره‌ای handler سطح ۲ برای یک پایگاه داده (kernel.alerts): زمان آخرین اجرا و جلوگیری از تکرار پیام."""

    plugin_id = models.CharField("پلاگین", max_length=41)
    handler = models.CharField("handler", max_length=31)
    workspace_id = models.PositiveIntegerField("پایگاه داده")
    last_run = models.DateTimeField("آخرین اجرا", null=True, blank=True)
    last_hash = models.CharField(max_length=40, blank=True)
    last_sent = models.DateTimeField("آخرین ارسال", null=True, blank=True)
    last_error = models.CharField("آخرین خطا", max_length=300, blank=True)

    class Meta:
        verbose_name = "وضعیت هشدار پلاگین"
        verbose_name_plural = "وضعیت هشدارهای پلاگین"
        constraints = [models.UniqueConstraint(fields=["plugin_id", "handler", "workspace_id"], name="uniq_plugin_alert_state")]

    def __str__(self):
        return f"{self.plugin_id}.{self.handler} @ {self.workspace_id}"


class PluginHealthBucket(models.Model):
    """شمارنده‌ی ۵ دقیقه‌ای اجرای کد پلاگین (موفق/ناموفق) برای قطع‌کن خودکار (kernel.health)."""

    plugin_id = models.CharField("پلاگین", max_length=41)
    bucket = models.DateTimeField("بازه")
    runs = models.PositiveIntegerField("اجرا", default=0)
    errors = models.PositiveIntegerField("خطا", default=0)

    class Meta:
        verbose_name = "سلامت پلاگین"
        verbose_name_plural = "سلامت پلاگین‌ها"
        constraints = [models.UniqueConstraint(fields=["plugin_id", "bucket"], name="uniq_plugin_health_bucket")]
        indexes = [models.Index(fields=["plugin_id", "bucket"], name="plugin_health_lookup")]

    def __str__(self):
        return f"{self.plugin_id} {self.bucket:%H:%M}: {self.errors}/{self.runs}"


class PluginTrip(models.Model):
    """ردپای قطع‌کن: چرا و با چه اقدامی (بازگشت به نسخه‌ی قبل یا خاموشی) یک نسخه‌ی پلاگین خودکار کنار گذاشته شد."""

    class Action(models.TextChoices):
        ROLLBACK = "rollback", "بازگشت به نسخه‌ی قبلی"
        DISABLE = "disable", "خاموش شد (نسخه‌ی قبلی نبود)"

    plugin_id = models.CharField("پلاگین", max_length=41, db_index=True)
    release = models.ForeignKey("PluginRelease", null=True, blank=True, on_delete=models.SET_NULL, related_name="trips", verbose_name="نسخه‌ی قطع‌شده")
    version = models.CharField("نسخه‌ی قطع‌شده", max_length=20)
    action = models.CharField("اقدام", max_length=10, choices=Action.choices)
    restored_version = models.CharField("نسخه‌ی بازگردانده‌شده", max_length=20, blank=True)
    runs = models.PositiveIntegerField("اجرا در پنجره")
    errors = models.PositiveIntegerField("خطا در پنجره")
    tripped_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "قطع خودکار پلاگین"
        verbose_name_plural = "قطع‌های خودکار پلاگین"
        ordering = ["-tripped_at"]

    def __str__(self):
        return f"{self.plugin_id} {self.version}: {self.get_action_display()}"


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


class PluginRelease(models.Model):
    """یک نسخه‌ی بسته‌ی پلاگین بارگذاری‌شده از پنل. بسته‌ی بررسی‌شده تغییرناپذیر است و درون پایگاه داده می‌ماند
    (بین وب و worker مشترک؛ بدون مدیریت فایل). فقط نسخه‌ی «فعال» در رجیستری بار می‌شود."""

    class Status(models.TextChoices):
        REJECTED = "rejected", "ردشده"
        CHECKED = "checked", "بررسی‌شده؛ منتظر تأیید"
        ACTIVE = "active", "فعال"
        RETIRED = "retired", "جایگزین‌شده"

    plugin_id = models.CharField("شناسه‌ی پلاگین", max_length=41, db_index=True)
    version = models.CharField("نسخه", max_length=20)
    name = models.CharField("نام", max_length=120, blank=True)
    kind = models.CharField("نوع", max_length=10, blank=True)
    publisher = models.CharField("ناشر", max_length=60, blank=True)
    sha256 = models.CharField("چکیده‌ی بسته", max_length=64, unique=True)
    blob = models.BinaryField("بسته", editable=False)
    size = models.PositiveIntegerField("حجم (بایت)", default=0)
    manifest = models.JSONField("مانیفست", default=dict, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.CHECKED, db_index=True)
    report = models.JSONField("گزارش بررسی", default=list, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+", verbose_name="بارگذارنده")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+", verbose_name="تأییدکننده")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField("زمان فعال‌سازی", null=True, blank=True)

    class Meta:
        verbose_name = "نسخه‌ی پلاگین"
        verbose_name_plural = "نسخه‌ها و بارگذاری پلاگین"
        ordering = ["-uploaded_at"]
        permissions = [("upload_pluginrelease", "بارگذاری بسته‌ی پلاگین"),
                       ("activate_pluginrelease", "تأیید و فعال‌سازی نسخه‌ی پلاگین")]
        constraints = [models.UniqueConstraint(fields=["plugin_id"], condition=models.Q(status="active"),
                                               name="one_active_release_per_plugin")]

    def __str__(self):
        return f"{self.plugin_id} {self.version}"
