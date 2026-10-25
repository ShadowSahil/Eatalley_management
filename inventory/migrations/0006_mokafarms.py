from django.db import migrations


def seed(apps, schema_editor):
    Vendor = apps.get_model("inventory", "Vendor")
    Vendor.objects.get_or_create(
        name="Mokafarms",
        defaults={"category": "beverages", "supplies": "Coffee beans", "match_keywords": "mokafarms, moka farms, mokafarm"},
    )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0005_naveen_keywords")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
