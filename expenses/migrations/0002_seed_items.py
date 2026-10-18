from django.db import migrations

# A starting list; the full list from the last two months can be imported
# from Excel on the Items page.
ITEMS = [
    ("Milk", "dairy", "L"),
    ("Cold Drink", "beverages", "btl"),
    ("Coconut Water", "beverages", "pcs"),
]


def seed(apps, schema_editor):
    ExpenseItem = apps.get_model("expenses", "ExpenseItem")
    for name, category, unit in ITEMS:
        if not ExpenseItem.objects.filter(name__iexact=name).exists():
            ExpenseItem.objects.create(name=name, category=category, unit=unit)


class Migration(migrations.Migration):
    dependencies = [("expenses", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
