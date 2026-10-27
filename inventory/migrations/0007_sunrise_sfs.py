from django.db import migrations


def update(apps, schema_editor):
    Vendor = apps.get_model("inventory", "Vendor")
    # The expense sheet writes Sunrise Food Services as "SFS".
    Vendor.objects.filter(name="Sunrise Food Services").update(match_keywords="sunrise, sfs")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0006_mokafarms")]
    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
