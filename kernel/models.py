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
    code = models.JSONField("کد سطح ۲", default=dict, blank=True, help_text="نام handler ← منبع پایتون؛ خالی = پلاگین سطح ۱")
    alerts = models.JSONField("هشدارها", default=dict, blank=True, help_text="نام handler ← هر چند دقیقه")
    tests = models.JSONField("آزمون‌ها", default=dict, blank=True, help_text="نام handler ← متن TOML آزمون (kernel.pkgtest)")
    wizard = models.JSONField("مشخصات ویزارد", default=dict, blank=True,
                              help_text="اگر پر باشد پیش‌نویس با ویزارد ساخته شده و صفحه‌هایش از روی این مشخصات ساخته می‌شود (kernel.wizard).")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پیش‌نویس پلاگین"
        verbose_name_plural = "استودیوی پلاگین"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.plugin_id})"


class PluginDraftRevision(models.Model):
    """تاریخچه‌ی نقشه‌ی پلاگین در استودیوی دیداری (docs/adr/0010): هر عملیات یک نسخه؛ برای بازگشت. حداکثر ۶۰ نسخه‌ی اخیر هر پیش‌نویس."""

    KEEP = 60

    draft = models.ForeignKey(PluginDraft, on_delete=models.CASCADE, related_name="revisions")
    spec = models.JSONField("نقشه")
    label = models.CharField("عملیات", max_length=120, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "نسخه‌ی پیش‌نویس"
        verbose_name_plural = "نسخه‌های پیش‌نویس"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.draft.plugin_id} #{self.pk}"


class PluginMedia(models.Model):
    """تصویر آگهی بازارچه پلاگین (docs/adr/0010 مرحله‌ی ۸): بازرمزگذاری‌شده‌ی بی‌فراداده، حداکثر ۳ تصویر برای هر پلاگین؛ عمومی با نشانی غیرقابل‌حدس (token)."""

    MAX_PER_PLUGIN = 3

    plugin_id = models.CharField("پلاگین", max_length=41, db_index=True)
    token = models.CharField(max_length=24, unique=True)
    content_type = models.CharField(max_length=20, default="image/webp")
    data = models.BinaryField(editable=False)
    width = models.PositiveSmallIntegerField(default=0)
    height = models.PositiveSmallIntegerField(default=0)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تصویر آگهی پلاگین"
        verbose_name_plural = "تصویرهای آگهی پلاگین"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.plugin_id} #{self.pk}"


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
    workspace_id = models.PositiveBigIntegerField("پایگاه داده (۰ = نامشخص)", default=0)
    runs = models.PositiveIntegerField("اجرا", default=0)
    errors = models.PositiveIntegerField("خطا", default=0)

    class Meta:
        verbose_name = "سلامت پلاگین"
        verbose_name_plural = "سلامت پلاگین‌ها"
        constraints = [models.UniqueConstraint(fields=["plugin_id", "bucket", "workspace_id"], name="uniq_plugin_health_bucket_ws")]
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
    seen_at = models.DateTimeField("دیده‌شده توسط مدیر", null=True, blank=True)

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
    notified = models.PositiveSmallIntegerField("مرحله‌ی اطلاع‌رسانی انقضا", default=0,
                                                help_text="۰ = چیزی نگفته‌ایم، ۱ = هشدار نزدیک انقضا داده شد، ۲ = انقضا اعلام شد (تمدید صفرش می‌کند).")
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
    access = models.JSONField("دسترسی و قیمت (ویزارد)", default=dict, blank=True,
                              help_text="هنگام فعال‌شدن اعمال می‌شود (kernel.publish)؛ بسته‌ی بارگذاری‌شده‌ی بیرونی خالی است.")
    notes = models.TextField("یادداشت انتشار", blank=True, help_text="چه چیزی در این نسخه تغییر کرد (استودیوی پلاگین).")
    spec = models.JSONField("نقشه‌ی استودیو", default=dict, blank=True,
                            help_text="نسخه‌ی نقشه‌ی پلاگین هنگام انتشار؛ برای بازگرداندن پیش‌نویس به این نسخه (فقط نسخه‌های استودیو).")
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


class PublisherKey(models.Model):
    """کلید عمومی ناشر بسته‌های پلاگین (Ed25519). فقط کلید عمومی اینجا می‌ماند؛ کلید خصوصی هرگز به سرور نمی‌رسد
    (در مرورگر مدیر ساخته می‌شود). افزودن/حذف با تأیید تازه (stepup)."""

    name = models.CharField("نام ناشر", max_length=40, unique=True)
    public_key = models.CharField("کلید عمومی (base64)", max_length=64)
    active = models.BooleanField("فعال", default=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+", verbose_name="افزوده‌شده توسط")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "کلید ناشر"
        verbose_name_plural = "کلیدهای ناشر"
        ordering = ["name"]

    def __str__(self):
        return self.name


class PlatformSetting(models.Model):
    """تنظیم سکو که مدیر در پنل می‌دهد (جلوتر از متغیر محیطی؛ فقط مقدار غیرحساس)."""

    key = models.CharField(max_length=40, unique=True)
    value = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیم سکو"
        verbose_name_plural = "تنظیم‌های سکو"


class IngestToken(models.Model):
    """توکن دریافت داده‌ی دستگاه برای یک `[[ingest]]` یک پایگاه (docs/plugins/ingest.md). فقط چکیده‌ی SHA-256 ذخیره می‌شود؛
    خودِ توکن یک‌بار هنگام ساخت دیده می‌شود. `workspace_id` عددی است تا هسته مدل پایگاه داده را نشناسد."""

    plugin_id = models.CharField("پلاگین", max_length=41)
    page = models.CharField("صفحه", max_length=31)
    key = models.CharField("نقطه‌ی دریافت", max_length=31)
    workspace_id = models.PositiveBigIntegerField("پایگاه داده", db_index=True)
    prefix = models.CharField("پیشوند توکن", max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField("برچسب", max_length=60, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="ساخته‌شده توسط")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField("آخرین استفاده", null=True, blank=True)
    revoked_at = models.DateTimeField("ابطال", null=True, blank=True)

    class Meta:
        verbose_name = "توکن دریافت داده"
        verbose_name_plural = "توکن‌های دریافت داده"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["workspace_id", "plugin_id", "page", "key"], name="ingest_token_scope")]

    def __str__(self):
        return f"{self.plugin_id}/{self.page}/{self.key} {self.prefix}…"


class PluginTable(models.Model):
    """ردپای جدولی که هسته برای یک پلاگین در پایگاه یک مشتری ساخته است (kernel.tables)؛ `spec_hash` = ساختار اعلام‌شده‌ی اعمال‌شده."""

    plugin_id = models.CharField("پلاگین", max_length=41)
    table = models.CharField("جدول", max_length=63)
    workspace_id = models.PositiveBigIntegerField("پایگاه داده", db_index=True)
    spec_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "جدول پلاگین"
        verbose_name_plural = "جدول‌های پلاگین"
        constraints = [models.UniqueConstraint(fields=["plugin_id", "table", "workspace_id"], name="uniq_plugin_table_ws")]

    def __str__(self):
        return f"{self.plugin_id}.{self.table} @ {self.workspace_id}"


class NotifyChannel(models.Model):
    """کانال پیام‌رسان (بله، تلگرام…): توکن ربات رمزنگاری‌شده؛ `api_base` برای رله‌ی سرور خارجی (مثلاً تلگرام)."""

    key = models.CharField("کانال", max_length=20, unique=True)
    enabled = models.BooleanField("فعال", default=False)
    token_enc = models.TextField("توکن ربات (رمزنگاری‌شده)", blank=True)
    token_hint = models.CharField(max_length=12, blank=True)
    bot_username = models.CharField("نام کاربری ربات", max_length=64, blank=True)
    api_base = models.CharField("نشانی پایه‌ی API", max_length=200, blank=True,
                                help_text="خالی = نشانی رسمی. برای تلگرام نشانی رله‌ی سرور خارجی را بگذارید.")
    update_offset = models.BigIntegerField(default=0)
    last_ok = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "کانال پیام‌رسان"
        verbose_name_plural = "کانال‌های پیام‌رسان"

    def __str__(self):
        return self.key


class NotifyAddress(models.Model):
    """مقصد پیام‌رسان یک کاربر. تا وقتی `chat_id` خالی است «در انتظار تأیید» است و فقط کد یک‌بارمصرف (هش) دارد."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notify_addresses")
    channel = models.CharField(max_length=20)
    chat_id = models.CharField(max_length=40, blank=True)
    code_hash = models.CharField(max_length=64, blank=True, db_index=True)
    code_expires = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "channel"], name="notify_addr_user_channel")]
        verbose_name = "مقصد پیام‌رسان"
        verbose_name_plural = "مقصدهای پیام‌رسان"


class NotifyPref(models.Model):
    """ترجیح اعلان کاربر: ساعت سکوت (محلی؛ هشدار بحرانی نادیده می‌گیرد) و پیامک/ایمیل پشتیبان."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notify_pref")
    quiet_from = models.PositiveSmallIntegerField(null=True, blank=True)
    quiet_to = models.PositiveSmallIntegerField(null=True, blank=True)
    fallback = models.BooleanField("پیامک/ایمیل اگر پیام‌رسان نرسید", default=True)


class NotifyLog(models.Model):
    """سابقه‌ی ارسال (برای سقف نرخ، جلوگیری از تکرار و عیب‌یابی). متن پیام نگهداری نمی‌شود."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=20)
    key = models.CharField(max_length=80, blank=True)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class SourceHost(models.Model):
    """میزبان بیرونی مجاز برای `[[sources]]`: فقط مدیر می‌افزاید؛ فهرست سفید دقیق (بدون wildcard)."""

    host = models.CharField("میزبان", max_length=120, unique=True)
    note = models.CharField("یادداشت", max_length=200, blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "میزبان مجاز منبع بیرونی"
        verbose_name_plural = "میزبان‌های مجاز منابع بیرونی"

    def __str__(self):
        return self.host


class SourceState(models.Model):
    """وضعیت و تنظیم یک منبع بیرونی در یک پایگاه (ADR-0009). کلید API رمزنگاری‌شده؛ `cursor` آخرین مقدار دریافت‌شده."""

    plugin_id = models.CharField(max_length=64)
    page = models.CharField(max_length=40)
    key = models.CharField(max_length=40)
    workspace_id = models.PositiveBigIntegerField()
    enabled = models.BooleanField(default=False)
    inputs = models.JSONField(default=dict)
    secret_enc = models.TextField(blank=True)
    cursor = models.CharField(max_length=64, blank=True)
    next_run = models.DateTimeField(null=True, blank=True, db_index=True)
    last_run = models.DateTimeField(null=True, blank=True)
    last_ok = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    last_rows = models.PositiveIntegerField(default=0)
    fails = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plugin_id", "page", "key", "workspace_id"], name="source_state_unique")]
        verbose_name = "وضعیت منبع بیرونی"
        verbose_name_plural = "وضعیت منابع بیرونی"


class ReportLayout(models.Model):
    """چیدمان ذخیره‌شده‌ی گزارش PDF یک صفحه در یک پایگاه (مشترک بین ویرایشگرها) + لوگوی بازکدگذاری‌شده (≤۱ مگابایت)."""

    workspace_id = models.PositiveBigIntegerField()
    plugin_id = models.CharField(max_length=64)
    page = models.CharField(max_length=40)
    key = models.CharField(max_length=40)
    layout = models.JSONField(default=dict)
    logo = models.BinaryField(null=True, blank=True, editable=False)
    logo_mime = models.CharField(max_length=20, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace_id", "plugin_id", "page", "key"], name="report_layout_unique")]
        verbose_name = "چیدمان گزارش"
        verbose_name_plural = "چیدمان گزارش‌ها"
