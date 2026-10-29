"""استان هر شهرستان و شهر را با چندضلعی واقعی دوباره تعیین می‌کند (فهرست‌های ساخته‌شده با روش قدیمی جعبه‌ای
مثلاً شهرستان تهران را زیر البرز گذاشته بودند)؛ بدون نیاز به بازسازی دستی فهرست."""
from django.db import migrations


def reassign(apps, schema_editor):
    from iranmap import osm

    osm._assign_parents(apps.get_model("iranmap", "Area"))


class Migration(migrations.Migration):
    dependencies = [("iranmap", "0001_initial")]
    operations = [migrations.RunPython(reassign, migrations.RunPython.noop)]
