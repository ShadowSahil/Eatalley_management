"""
One-off import of the old Google Sheet expense tracker (Aug–Oct 2026).

    python manage.py import_expense_sheet expenses.xlsx --dry-run   # preview
    python manage.py import_expense_sheet expenses.xlsx             # import
    python manage.py import_expense_sheet --undo                    # remove everything it imported

Sheet layout: tabs "August", "September", "October" (running costs) and
"Opening" (one-time setup costs), each with columns
Date | Amount | By | To | Type | Comment(s) | Mode.

Where rows go:
  * Type "Inventory" paid to JS Foods / Sunrise (SFS) / Naveen / Hyperpure / Mokafarms -> Inventory bills
  * Type "Bill" / "Rent", and staff room rent                         -> Fixed costs
  * other Inventory, Misc, Marketing                                  -> Daily expenses
    (Inventory rows get the item named in the comment; the item list is
     seeded by expenses/migrations/0004_sheet_items.py)
  * Type "Salary"                                                     -> Staff payments
    (paid to someone on the Staff page with a monthly salary -> their payments;
     everyone else -> "Adhoc helper". Add monthly staff on the Staff page first.)
  * Type "Equipments" / "Interior" and the whole "Opening" tab        -> Opening costs
"By" (who paid) becomes "Paid by". Every row is tagged with SOURCE so --undo
removes exactly what this command created.
"""

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Payer
from core.periods import add_months
from expenses.models import DailyExpense, ExpenseItem
from fixedcosts.models import FixedCost, FixedCostHead
from inventory.models import Purchase, Vendor
from opening.models import OpeningCost
from payroll.models import SalaryPayment, Staff

SOURCE = "gsheet-2026"
MONTH_TABS = ["August", "September", "October"]
BUSINESS_PAYER = "Eatalley"

# --------------------------------------------------------------- vendors & staff

VENDOR_RULES = [  # substring of "To" (lower-case) -> vendor name
    ("hyperpure", "Hyperpure"),
    ("js food", "JS Foods"),
    ("j s food", "JS Foods"),
    ("sunrise", "Sunrise Food Services"),
    ("sfs", "Sunrise Food Services"),
    ("naveen", "Naveen Kumar Vegetables"),
    ("mokafarm", "Mokafarms"),
    ("moka farm", "Mokafarms"),
]
ADHOC = ("Adhoc helper", "Daily / ad-hoc helpers and labour")

# --------------------------------------------------------------- daily expense items

# Phrases rewritten to single tokens before matching (order matters).
PHRASES = [
    (r"ice\s*cream", "icecream"),
    (r"milk\s*maid|milkmade|milkmaid|condensed?\s*milk|condesed\s*milk|condensed", "milkmaid"),
    (r"coconut\s*water", "coconutwater"),
    (r"cold\s*drinks?", "colddrink"),
    (r"diet\s*coke", "coke"),
    (r"ice\s*cubes?|\bcubes?\b", "ice"),
    (r"ice\s*tray", "tray"),
    (r"milk\s*straw", "straw"),
    (r"water\s*bottles?", "waterbottle"),
    (r"coffee\s*sachet", "coffeesachet"),
    (r"kitchen\s*towel", "kitchentowel"),
    (r"display\s*packet", "packet"),
    (r"cherry\s*tomato", "cherrytomato"),
    (r"peanut\s*butter", "peanutbutter"),
    (r"wrapping\s*paper", "wrapping"),
    (r"room\s*fresh(e)?ner", "freshener"),
]
# Everything bought under "Inventory" outside the vendors above. Keep the
# names in step with expenses/migrations/0004_sheet_items.py.
ITEMS = [  # name, category, unit, token regex
    ("Milk", "dairy", "L", r"milk"),
    ("Paneer", "dairy", "kg", r"paneer"),
    ("Condensed milk (Milkmaid)", "dairy", "pcs", r"milkmaid"),
    ("Dahi", "dairy", "kg", r"dahi|curd"),
    ("Adhoc cheese", "dairy", "pkt", r"cheese|parm|parmesan|cheddar"),  # top-ups outside JS Foods
    ("Ice", "beverages", "bag", r"ice"),
    ("Ice cream", "beverages", "pcs", r"icecream"),
    ("Cold Drink", "beverages", "btl", r"colddrink|coke|sprite|soda"),
    ("Coconut Water", "beverages", "pcs", r"coconutwater"),
    ("Coffee sachets", "beverages", "pkt", r"coffeesachet"),
    ("Protein powder", "beverages", "kg", r"protein"),
    ("Water bottles", "beverages", "btl", r"waterbottle"),
    ("Syrups", "beverages", "btl", r"syrup"),
    ("Watermelon", "veg_fruit", "kg", r"watermelon"),
    ("Banana", "veg_fruit", "dozen", r"banana"),
    ("Cherries", "veg_fruit", "pkt", r"cheery|cherry"),
    ("Lemon", "veg_fruit", "kg", r"lemon|nembu|nimbu"),
    ("Mint", "veg_fruit", "pkt", r"mint"),
    ("Parsley", "veg_fruit", "pkt", r"parsley"),
    ("Basil", "veg_fruit", "pkt", r"basil"),
    ("Broccoli", "veg_fruit", "kg", r"broccoli"),
    ("Mushroom", "veg_fruit", "pkt", r"mushrooms?"),
    ("Cucumber", "veg_fruit", "kg", r"cucumber"),
    ("Tomato", "veg_fruit", "kg", r"tomato"),
    ("Cherry tomato", "veg_fruit", "pkt", r"cherrytomato"),
    ("Corn", "veg_fruit", "pkt", r"corn"),
    ("Vegetables (mixed)", "veg_fruit", "kg", r"vegetables?"),
    ("Rice", "grocery", "kg", r"rice"),
    ("Bread", "grocery", "pkt", r"bread"),
    ("Besan", "grocery", "kg", r"besan"),
    ("Rajma", "grocery", "kg", r"rajma"),
    ("Refined oil", "grocery", "L", r"refined"),
    ("Yeast", "grocery", "pkt", r"yeast"),
    ("Ketchup", "grocery", "btl", r"ketchup"),
    ("Tabasco", "grocery", "btl", r"tabasco|tabisco"),
    ("Peanut butter", "grocery", "pcs", r"peanutbutter"),
    ("Muesli", "grocery", "pkt", r"muesli"),
    ("Maggi", "grocery", "pkt", r"maggi|maggie"),
    ("Fries (frozen)", "grocery", "pkt", r"fries"),
    ("Pepperoni", "grocery", "pkt", r"pepperoni"),
    ("Chicken", "grocery", "kg", r"chicken"),
    ("Straws", "packaging", "pkt", r"straws?"),
    ("Foil", "packaging", "nos", r"foil"),
    ("Wrapping paper", "packaging", "nos", r"wrapping"),
    ("Containers", "packaging", "nos", r"containers?"),
    ("Display packets", "packaging", "nos", r"packets?"),
    ("Tape", "packaging", "nos", r"tape"),
    ("Gloves", "cleaning", "box", r"gloves"),
    ("Kitchen towels", "cleaning", "nos", r"kitchentowel"),
    ("Mop", "cleaning", "nos", r"mop"),
    ("Lizol", "cleaning", "btl", r"lizol"),
    ("Handwash", "cleaning", "btl", r"handwash"),
    ("Cleaning cloth", "cleaning", "nos", r"cloth"),
    ("Brush", "cleaning", "nos", r"brush"),
    ("Fly repellent", "cleaning", "nos", r"makkhi"),
    ("Room freshener", "cleaning", "nos", r"freshener"),
    ("Gas Cylinder", "gas_fuel", "cyl", r"cylinder|gas"),
    ("Batteries", "other", "nos", r"cell|battery|batteries"),
    ("Stationery", "other", "nos", r"markers?|stationery"),
    ("Change given to customer", "other", "nos", r"change"),
]
MIXED = ("Mixed groceries", "grocery", "nos")

# Non-inventory rows: first matching rule on "To + Comment" wins.
OTHER_RULES = [
    (r"^gst\b", ("GST payment", "gst", "nos")),
    (r"\bca\b|notary|filing charges", ("CA & compliance fees", "admin", "nos")),
    (r"anthropic|claude|subs\b", ("Software subscriptions", "admin", "nos")),
    (r"recharge", ("Phone recharge", "utilities", "nos")),
    (r"customer|\bchange\b|extra cash", ("Change given to customer", "other", "nos")),
    (r"\broom\b|\bstay\b", ("Staff room rent", "rent", "nos")),
    (r"\brent\b", ("Rent", "rent", "nos")),
    (r"menu|printing", ("Menu & printing", "marketing", "nos")),
    (r"billboard|sign\b", ("Signage & billboards", "marketing", "nos")),
    (r"team meeting|staff|daaru|alcohol|gift|rashan|whiskey", ("Staff welfare & team meetings", "staff", "nos")),
    (r"agarbatti|dhoopbatti|\bhit\b", ("Agarbatti & pest control", "cleaning", "nos")),
    (r"porter", ("Porter & transport", "transport", "nos")),
    (r"fire|board|pech|hardware", ("Repairs & fittings", "repairs", "nos")),
    (r"electricity", ("Electricity & maintenance", "utilities", "nos")),
]
TYPE_DEFAULTS = {
    "bill": ("Electricity & maintenance", "utilities", "nos"),
    "rent": ("Rent", "rent", "nos"),
    "marketing": ("Signage & billboards", "marketing", "nos"),
}
MISC = ("Miscellaneous", "other", "nos")
# Rows classified as these go to Fixed costs (month = the month paid) instead of daily expenses.
FIXED_HEADS = {
    "Rent": "Rent",
    "Electricity & maintenance": "Electricity bill",
    "Staff room rent": "Staff room rent",
}

OPENING_CATEGORIES = {
    "interior": "interior", "equipments": "equipment", "equipment": "equipment", "misc": "misc",
    "inventory": "inventory", "shop": "shop", "food tasting": "food_tasting", "marketing": "marketing",
}


def text(v):
    if v is None or isinstance(v, datetime):  # a few comment cells were auto-converted to dates
        return ""
    return " ".join(str(v).split())


def classify_inventory(comment):
    s = comment.lower()
    for pattern, token in PHRASES:
        s = re.sub(pattern, f" {token} ", s)
    found = {name for name, _, _, rx in ITEMS if re.search(rf"\b(?:{rx})\b", s)}
    if len(found) == 1:
        name = found.pop()
        return next(i[:3] for i in ITEMS if i[0] == name)
    return MIXED


def classify_other(kind, to, comment):
    s = f"{to} | {comment}".lower()
    for rx, item in OTHER_RULES:
        if re.search(rx, s):
            return item
    return TYPE_DEFAULTS.get(kind, MISC)


def salary_month(paid_on, amount, monthly):
    """Big payments in the first week of a month are last month's salary."""
    if paid_on.day <= 7 and monthly and amount >= monthly / 2:
        return add_months(paid_on.replace(day=1), -1)
    return paid_on.replace(day=1)


# --------------------------------------------------------------- reading


def read_tab(wb, name):
    if name not in wb.sheetnames:
        raise CommandError(f"The sheet has no '{name}' tab.")
    rows = list(wb[name].iter_rows(values_only=True))
    header = [text(c).lower() for c in rows[0][:7]]
    if header[:5] != ["date", "amount", "by", "to", "type"]:
        raise CommandError(f"Unexpected columns in '{name}': {rows[0][:7]}")
    out = []
    for i, r in enumerate(rows[1:], start=2):
        r = list(r) + [None] * 7
        if r[0] is None and r[1] is None:
            continue
        if not isinstance(r[0], datetime) or not isinstance(r[1], (int, float)):
            raise CommandError(f"'{name}' row {i}: can't read date/amount {r[:2]}")
        out.append({
            "tab": name,
            "date": r[0].date(),
            "amount": Decimal(str(r[1])).quantize(Decimal("0.01")),
            "by": text(r[2]) or BUSINESS_PAYER,
            "to": text(r[3]),
            "type": text(r[4]).lower(),
            "comment": text(r[5]),
            "mode": "cash" if text(r[6]).lower() == "cash" else "",
        })
    return out


class Command(BaseCommand):
    help = "Import the Aug–Oct Google Sheet expense tracker (or --undo it)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="The sheet downloaded as .xlsx")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be imported, change nothing")
        parser.add_argument("--undo", action="store_true", help="Delete everything this command imported")

    def handle(self, path=None, dry_run=False, undo=False, **opts):
        if undo:
            return self.undo()
        if not path:
            raise CommandError("Give the path to the downloaded .xlsx")
        if any(m.objects.filter(source=SOURCE).exists() for m in (DailyExpense, Purchase, FixedCost, SalaryPayment, OpeningCost)):
            raise CommandError("The sheet is already imported. Run with --undo first to re-import.")

        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True)
        monthly = [r for tab in MONTH_TABS for r in read_tab(wb, tab)]
        opening = read_tab(wb, "Opening")

        plan = defaultdict(list)  # destination -> rows (with mapping info)
        for r in monthly:
            kind, to_l = r["type"], r["to"].lower()
            if kind == "inventory" and any(k in to_l for k, _ in VENDOR_RULES):
                r["vendor"] = next(v for k, v in VENDOR_RULES if k in to_l)
                plan["bills"].append(r)
            elif kind == "inventory":
                r["item"] = classify_inventory(r["comment"])
                plan["expenses"].append(r)
            elif kind == "salary":
                plan["salary"].append(r)
            elif kind in ("equipments", "equipment", "interior"):
                r["category"] = "interior" if kind == "interior" else "equipment"
                plan["opening"].append(r)
            else:
                r["item"] = classify_other(kind, r["to"], r["comment"])
                if r["item"][0] in FIXED_HEADS:
                    r["head"] = FIXED_HEADS[r["item"][0]]
                    plan["fixed"].append(r)
                else:
                    plan["expenses"].append(r)
        for r in opening:
            r["category"] = OPENING_CATEGORIES.get(r["type"], "misc")
            plan["opening"].append(r)

        self.report(monthly, opening, plan)
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing was saved."))
            return
        with transaction.atomic():
            self.save(plan)
        self.stdout.write(self.style.SUCCESS("Imported. Undo any time with: manage.py import_expense_sheet --undo"))

    # ----------------------------------------------------------- output

    def report(self, monthly, opening, plan):
        w = self.stdout.write
        total = lambda rows: sum((r["amount"] for r in rows), Decimal(0))  # noqa: E731
        w(f"Sheet: {len(monthly)} rows in {', '.join(MONTH_TABS)} (₹{total(monthly):,.0f}), "
          f"{len(opening)} rows in Opening (₹{total(opening):,.0f})")
        for dest in ("expenses", "bills", "fixed", "salary", "opening"):
            w(f"  -> {dest:9} {len(plan[dest]):4} rows  ₹{total(plan[dest]):>12,.0f}")
        mapped = total([r for rows in plan.values() for r in rows])
        w(f"     total     {sum(len(v) for v in plan.values()):4} rows  ₹{mapped:>12,.0f}")
        by_item = defaultdict(lambda: [0, Decimal(0)])
        for r in plan["expenses"]:
            by_item[r["item"][0]][0] += 1
            by_item[r["item"][0]][1] += r["amount"]
        w("  Daily expense items:")
        for name, (n, amt) in sorted(by_item.items(), key=lambda x: -x[1][1]):
            w(f"     {name:32} {n:3}  ₹{amt:>10,.0f}")

    # ----------------------------------------------------------- saving

    def save(self, plan):
        payers = {}

        def payer(name):
            key = name.strip().lower()
            if key not in payers:
                p = Payer.objects.filter(name__iexact=name.strip()).first()
                if not p:
                    p = Payer.objects.create(name=name.strip().title(), is_business=key == BUSINESS_PAYER.lower())
                payers[key] = p
            return payers[key]

        items = {}

        def item(name, category, unit):
            if name not in items:
                obj = ExpenseItem.objects.filter(name__iexact=name).first()
                items[name] = obj or ExpenseItem.objects.create(name=name, category=category, unit=unit)
            return items[name]

        for r in plan["expenses"]:
            note = ": ".join(x for x in (r["to"], r["comment"]) if x)
            DailyExpense.objects.create(
                date=r["date"], item=item(*r["item"]), amount=r["amount"], payment_mode=r["mode"],
                paid_by=payer(r["by"]), note=note[:200], source=SOURCE,
            )

        vendors = {v.name: v for v in Vendor.objects.all()}
        for r in plan["bills"]:
            vendor = vendors.get(r["vendor"]) or Vendor.objects.create(name=r["vendor"])
            vendors[vendor.name] = vendor
            Purchase.objects.create(
                vendor=vendor, bill_date=r["date"], category=vendor.category, total=r["amount"],
                is_paid=True, paid_on=r["date"], payment_mode=r["mode"], paid_by=payer(r["by"]),
                notes=f"Payment recorded in the expense sheet{': ' + r['comment'] if r['comment'] else ''}"[:300],
                source=SOURCE,
            )

        monthly_staff = list(Staff.objects.filter(monthly_salary__gt=0))

        def staff_for(to):
            """Match the sheet's "To" (often a first or last name) to someone on the Staff page."""
            to = to.lower().strip()
            for s in monthly_staff:
                name = s.name.lower()
                if to and (to == name or to in name.split() or name in to):
                    return s
            return None

        adhoc = Staff.objects.filter(name__iexact=ADHOC[0]).first() or Staff.objects.create(
            name=ADHOC[0], role=ADHOC[1], monthly_salary=0, notes="Paid per day; no fixed monthly salary"
        )
        for r in plan["salary"]:
            monthly = staff_for(r["to"])
            person = monthly or adhoc
            is_advance = "advance" in r["comment"].lower()
            month = r["date"].replace(day=1) if is_advance or not monthly else salary_month(
                r["date"], r["amount"], person.monthly_salary
            )
            SalaryPayment.objects.create(
                staff=person, month=month, kind="advance" if is_advance else "salary", amount=r["amount"],
                paid_on=r["date"], payment_mode=r["mode"], paid_by=payer(r["by"]),
                note=(": ".join(x for x in (r["to"], r["comment"]) if x) if not monthly else r["comment"])[:200],
                source=SOURCE,
            )

        heads = {}
        for r in plan["fixed"]:
            if r["head"] not in heads:
                heads[r["head"]] = (FixedCostHead.objects.filter(name__iexact=r["head"]).first()
                                     or FixedCostHead.objects.create(name=r["head"]))
            FixedCost.objects.create(
                head=heads[r["head"]], month=r["date"].replace(day=1), amount=r["amount"], paid_on=r["date"],
                payment_mode=r["mode"], paid_by=payer(r["by"]),
                note=": ".join(x for x in (r["to"], r["comment"]) if x)[:200], source=SOURCE,
            )

        for r in plan["opening"]:
            OpeningCost.objects.create(
                date=r["date"], amount=r["amount"], category=r["category"], paid_to=r["to"][:100],
                description=r["comment"][:200], paid_by=payer(r["by"]), source=SOURCE,
            )

    def undo(self):
        with transaction.atomic():
            counts = {m.__name__: m.objects.filter(source=SOURCE).delete()[0]
                      for m in (DailyExpense, Purchase, FixedCost, SalaryPayment, OpeningCost)}
        self.stdout.write(self.style.SUCCESS(f"Removed imported rows: {counts}"))
        self.stdout.write("Items, staff and people created by the import were kept; delete them in Admin if unwanted.")
