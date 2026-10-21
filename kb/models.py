from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from . import text as fa

# بخش‌های ثابت آدرس /kb/ که نباید شناسه مقاله شوند
RESERVED_SLUGS = frozenset({"search", "c", "api"})


class Category(models.Model):
    slug = models.SlugField("شناسه", unique=True, max_length=60)
    title = models.CharField("عنوان", max_length=120)
    description = models.CharField("توضیح کوتاه", max_length=300, blank=True)
    icon = models.CharField("نماد (ایموجی)", max_length=8, blank=True)
    order = models.PositiveIntegerField("ترتیب", default=100)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        verbose_name = "دسته"
        verbose_name_plural = "دسته‌ها"
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("kb:category", args=[self.slug])


class Article(models.Model):
    class Kind(models.TextChoices):
        FAQ = "faq", "پرسش و پاسخ"
        HOWTO = "howto", "راهنمای گام‌به‌گام"
        CONCEPT = "concept", "مفهوم و توضیح"
        TROUBLE = "trouble", "عیب‌یابی"
        REFERENCE = "reference", "مرجع"

    class Audience(models.TextChoices):
        PUBLIC = "public", "عمومی (همه)"
        MEMBER = "member", "فقط کاربران واردشده"
        STAFF = "staff", "داخلی (فقط مدیران)"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PUBLISHED = "published", "منتشرشده"

    slug = models.SlugField("شناسه (آدرس)", unique=True, max_length=90, allow_unicode=False)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="articles", verbose_name="دسته")
    title = models.CharField("عنوان یا پرسش", max_length=200,
                             help_text="ترجیحاً همان جمله‌ای که کاربر می‌پرسد، مثلاً «چطور پایگاه داده بسازم؟»")
    summary = models.TextField(
        "پاسخ کوتاه", max_length=800,
        help_text="پاسخ مستقیم در یک تا سه جمله، بدون نیاز به خواندن بقیه مقاله. در نتایج جست‌وجو و پاسخ دستیار می‌آید.")
    body = models.TextField("متن کامل (Markdown)", blank=True,
                            help_text="سرفصل با ## و ###؛ مقدارهای پلن با {{plan_quota}} و جدول پلن‌ها با {{plans_table}}.")
    kind = models.CharField("نوع", max_length=10, choices=Kind.choices, default=Kind.HOWTO)
    audience = models.CharField("مخاطب", max_length=8, choices=Audience.choices, default=Audience.PUBLIC)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PUBLISHED)
    keywords = models.CharField(
        "کلیدواژه‌ها و هم‌معنی‌ها", max_length=400, blank=True,
        help_text="با ویرگول جدا کنید؛ شامل نام‌های دیگر و اشتباهات رایج، مثل: ریست رمز, فراموشی رمز, password")
    related = models.ManyToManyField("self", blank=True, symmetrical=False, verbose_name="مقاله‌های مرتبط")
    is_featured = models.BooleanField("نمایش در پرسش‌های متداول صفحه اصلی", default=False)
    order = models.PositiveIntegerField("ترتیب", default=100)
    reviewed_at = models.DateField("آخرین بازبینی محتوا", default=timezone.localdate)

    # همگام‌سازی با فایل‌های محتوا (kb/content)
    managed = models.BooleanField("از فایل محتوا آمده", default=False, editable=False)
    locked = models.BooleanField(
        "ویرایش‌شده در پنل (همگام‌سازی از فایل رویش نمی‌نویسد)", default=False,
        help_text="اگر روشن باشد، دستور kb_sync این مقاله را تغییر نمی‌دهد.")
    content_hash = models.CharField(max_length=64, blank=True, editable=False)
    search_text = models.TextField(blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "مقاله"
        verbose_name_plural = "مقاله‌ها"
        ordering = ["category__order", "order", "id"]
        indexes = [models.Index(fields=["status", "audience"])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("kb:article", args=[self.slug])

    def clean(self):
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({"slug": "این شناسه رزرو شده است؛ شناسه دیگری انتخاب کنید."})

    def save(self, *args, **kwargs):
        self.search_text = fa.normalize(" ".join(
            [self.title, self.summary, self.keywords, fa.plain_text(self.body)]))
        super().save(*args, **kwargs)
        from .chunking import rebuild_chunks

        rebuild_chunks(self)

    @property
    def is_visible(self) -> bool:
        return self.status == self.Status.PUBLISHED and self.category.is_active

    def keyword_list(self) -> list[str]:
        return [k.strip() for k in self.keywords.replace("،", ",").split(",") if k.strip()]


class ArticleChunk(models.Model):
    """تکه‌های مقاله برای بازیابی (RAG). متن خام با توکن‌ها نگه داشته می‌شود تا با تغییر پلن کهنه نشود."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="chunks")
    ordinal = models.PositiveSmallIntegerField()
    heading = models.CharField(max_length=300, blank=True)
    anchor = models.CharField(max_length=300, blank=True)
    text = models.TextField()
    text_hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["article_id", "ordinal"]
        unique_together = [("article", "ordinal")]

    def __str__(self):
        return f"{self.article.slug}#{self.ordinal}"


class MissedQuery(models.Model):
    """جست‌وجوهای بی‌نتیجه (بدون اطلاعات کاربر)؛ فهرست مقاله‌های بعدی."""

    query_norm = models.CharField(max_length=200, unique=True)
    sample = models.CharField("نمونه عبارت", max_length=200)
    count = models.PositiveIntegerField("تعداد", default=1)
    last_seen = models.DateTimeField(auto_now=True)
    resolved = models.BooleanField("پاسخ داده شد", default=False)

    class Meta:
        verbose_name = "جست‌وجوی بی‌نتیجه"
        verbose_name_plural = "جست‌وجوهای بی‌نتیجه"
        ordering = ["resolved", "-count", "-last_seen"]

    def __str__(self):
        return self.sample


class Feedback(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="feedback")
    helpful = models.BooleanField("مفید بود")
    comment = models.CharField("توضیح", max_length=500, blank=True)
    session_key = models.CharField(max_length=40, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "بازخورد مقاله"
        verbose_name_plural = "بازخوردهای مقاله‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.article.slug}: {'مفید' if self.helpful else 'نامفید'}"
