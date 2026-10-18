from django.db import migrations

# Names as they appear on the bills / in the expense sheet.
RENAMES = [
    ("Neveen", "Naveen Kumar Vegetables", "naveen, neveen"),
    ("Sunrise", "Sunrise Food Services", "sunrise"),
    ("JS Foods", "JS Foods", "js foods, jsfoods, j.s. foods, j s foods, js food"),
]


def rename(apps, schema_editor):
    Vendor = apps.get_model("inventory", "Vendor")
    for old, new, keywords in RENAMES:
        Vendor.objects.filter(name=old).update(name=new, match_keywords=keywords)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_purchase_paid_by_purchase_source")]
    operations = [migrations.RunPython(rename, migrations.RunPython.noop)]
