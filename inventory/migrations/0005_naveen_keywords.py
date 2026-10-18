from django.db import migrations


def update(apps, schema_editor):
    Vendor = apps.get_model("inventory", "Vendor")
    # Naveen's printed memo is headed "Maa Laxmi Fruit & Vegetable Supplier, Prop. Navin Kumar".
    Vendor.objects.filter(name="Naveen Kumar Vegetables").update(
        match_keywords="naveen, neveen, navin kumar, maa laxmi", supplies="Fresh vegetables (Maa Laxmi Fruit & Vegetable Supplier)"
    )
    Vendor.objects.filter(name="JS Foods").update(
        match_keywords="js foods, jsfoods, j.s. foods, j s foods, js food, j s food, jsfood"
    )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_vendor_names")]
    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
