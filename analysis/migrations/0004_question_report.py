from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0003_question_answer"),
    ]

    operations = [
        migrations.AddField(
            model_name="question",
            name="result_kind",
            field=models.CharField(blank=True, choices=[("layer", "لایه ساخته شد"), ("empty", "هیچ عارضه‌ای پیدا نشد"),
                                                        ("answer", "پاسخ متنی"), ("failed", "ناموفق")],
                                   max_length=10, verbose_name="نوع نتیجه"),
        ),
        migrations.AddField(
            model_name="question",
            name="steps",
            field=models.JSONField(blank=True, default=list, verbose_name="مراحل اجرا"),
        ),
        migrations.AddField(
            model_name="question",
            name="share_values",
            field=models.BooleanField(default=True, verbose_name="ارسال مقادیر دسته‌ای ستون‌ها به مدل"),
        ),
    ]
