from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.RunSQL("این SQL معتبر نیست")]  # مهاجرت معیوب ساختگی CI
