from django.db import migrations

# Everything the expense sheet (Aug–Oct 2026) bought under "Inventory" from
# anyone other than Hyperpure, Naveen, JS Foods, Sunrise (SFS) and Mokafarms —
# those vendors are Inventory bills. Cheese, butter and cream come from JS Foods
# and coffee beans from Mokafarms, so they are not daily expense items; cheese
# bought elsewhere in a pinch is "Adhoc cheese".
# Keep in step with ITEMS in core/sheet_import.py.
ITEMS = [
    ("Milk", "dairy", "L"),
    ("Paneer", "dairy", "kg"),
    ("Condensed milk (Milkmaid)", "dairy", "pcs"),
    ("Dahi", "dairy", "kg"),
    ("Adhoc cheese", "dairy", "pkt"),
    ("Ice", "beverages", "bag"),
    ("Ice cream", "beverages", "pcs"),
    ("Cold Drink", "beverages", "btl"),
    ("Coconut Water", "beverages", "pcs"),
    ("Coffee sachets", "beverages", "pkt"),
    ("Protein powder", "beverages", "kg"),
    ("Water bottles", "beverages", "btl"),
    ("Syrups", "beverages", "btl"),
    ("Watermelon", "veg_fruit", "kg"),
    ("Banana", "veg_fruit", "dozen"),
    ("Cherries", "veg_fruit", "pkt"),
    ("Lemon", "veg_fruit", "kg"),
    ("Mint", "veg_fruit", "pkt"),
    ("Parsley", "veg_fruit", "pkt"),
    ("Basil", "veg_fruit", "pkt"),
    ("Broccoli", "veg_fruit", "kg"),
    ("Mushroom", "veg_fruit", "pkt"),
    ("Cucumber", "veg_fruit", "kg"),
    ("Tomato", "veg_fruit", "kg"),
    ("Cherry tomato", "veg_fruit", "pkt"),
    ("Corn", "veg_fruit", "pkt"),
    ("Vegetables (mixed)", "veg_fruit", "kg"),
    ("Rice", "grocery", "kg"),
    ("Bread", "grocery", "pkt"),
    ("Besan", "grocery", "kg"),
    ("Rajma", "grocery", "kg"),
    ("Refined oil", "grocery", "L"),
    ("Yeast", "grocery", "pkt"),
    ("Ketchup", "grocery", "btl"),
    ("Tabasco", "grocery", "btl"),
    ("Peanut butter", "grocery", "pcs"),
    ("Muesli", "grocery", "pkt"),
    ("Maggi", "grocery", "pkt"),
    ("Fries (frozen)", "grocery", "pkt"),
    ("Pepperoni", "grocery", "pkt"),
    ("Chicken", "grocery", "kg"),
    ("Straws", "packaging", "pkt"),
    ("Foil", "packaging", "nos"),
    ("Wrapping paper", "packaging", "nos"),
    ("Containers", "packaging", "nos"),
    ("Display packets", "packaging", "nos"),
    ("Tape", "packaging", "nos"),
    ("Gloves", "cleaning", "box"),
    ("Kitchen towels", "cleaning", "nos"),
    ("Mop", "cleaning", "nos"),
    ("Lizol", "cleaning", "btl"),
    ("Handwash", "cleaning", "btl"),
    ("Cleaning cloth", "cleaning", "nos"),
    ("Brush", "cleaning", "nos"),
    ("Fly repellent", "cleaning", "nos"),
    ("Room freshener", "cleaning", "nos"),
    ("Gas Cylinder", "gas_fuel", "cyl"),
    ("Batteries", "other", "nos"),
    ("Stationery", "other", "nos"),
]


def seed(apps, schema_editor):
    ExpenseItem = apps.get_model("expenses", "ExpenseItem")
    for name, category, unit in ITEMS:
        if not ExpenseItem.objects.filter(name__iexact=name).exists():
            ExpenseItem.objects.create(name=name, category=category, unit=unit)


class Migration(migrations.Migration):
    dependencies = [("expenses", "0003_dailyexpense_paid_by_dailyexpense_source_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
