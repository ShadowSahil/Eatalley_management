from django.db import migrations

VENDORS = [
    ("JS Foods", "dairy", "Cheese, butter and dairy", "js foods, jsfoods, j.s. foods, j s foods"),
    ("Sunrise", "flour", "Flour (maida) and bakery items", "sunrise"),
    ("Neveen", "vegetables", "Fresh vegetables", "neveen, naveen"),
    ("Hyperpure", "sauces", "Sauces and additional items", "hyperpure, zomato hyperpure"),
]


def seed(apps, schema_editor):
    Vendor = apps.get_model("inventory", "Vendor")
    for name, category, supplies, keywords in VENDORS:
        Vendor.objects.get_or_create(
            name=name, defaults={"category": category, "supplies": supplies, "match_keywords": keywords}
        )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
