from django.db import migrations


def seed(apps, schema_editor):
    Payer = apps.get_model("core", "Payer")
    Payer.objects.get_or_create(name="Eatalley", defaults={"is_business": True})


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
