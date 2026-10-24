from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0002_toolrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="question",
            name="answer",
            field=models.TextField(blank=True, verbose_name="پاسخ متنی"),
        ),
    ]
