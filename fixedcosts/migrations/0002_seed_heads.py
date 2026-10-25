from django.db import migrations

HEADS = ["Rent", "Electricity bill", "Staff room rent"]


def seed(apps, schema_editor):
    FixedCostHead = apps.get_model("fixedcosts", "FixedCostHead")
    for name in HEADS:
        if not FixedCostHead.objects.filter(name__iexact=name).exists():
            FixedCostHead.objects.create(name=name)


class Migration(migrations.Migration):
    dependencies = [("fixedcosts", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
