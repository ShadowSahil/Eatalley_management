"""
One-off import of the old Google Sheet expense tracker (Aug–Oct 2026).

    python manage.py import_expense_sheet expenses.xlsx --dry-run   # preview
    python manage.py import_expense_sheet expenses.xlsx             # import
    python manage.py import_expense_sheet --undo                    # remove everything it imported

Sheet layout: tabs "August", "September", "October" (running costs) and
"Opening" (one-time setup costs), each with columns
Date | Amount | By | To | Type | Comment(s) | Mode.

Rows are filed by the rules in core/sheet_import.py, except that payments to
our vendors become (paid) Inventory bills here, and the whole "Opening" tab
goes to Opening costs. Add monthly staff on the Staff page first.
"By" (who paid) becomes "Paid by". Every row is tagged with SOURCE so --undo
removes exactly what this command created.

For a single month going forward, use Daily expense → Import from Google Sheet
on the website instead.
"""

from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.sheet_import import (  # noqa: F401 - ITEMS, MIXED, classify_inventory are used by the tests
    ITEMS,
    MIXED,
    OPENING_CATEGORIES,
    Saver,
    classify_inventory,
    read_rows,
    route,
    vendor_matcher,
)
from expenses.models import DailyExpense
from fixedcosts.models import FixedCost
from inventory.models import Purchase
from opening.models import OpeningCost
from payroll.models import SalaryPayment, Staff

SOURCE = "gsheet-2026"
MONTH_TABS = ["August", "September", "October"]
MODELS = (DailyExpense, Purchase, FixedCost, SalaryPayment, OpeningCost)


def read_tab(wb, name):
    if name not in wb.sheetnames:
        raise CommandError(f"The sheet has no '{name}' tab.")
    rows, problems = read_rows(wb[name], name)
    if problems:
        raise CommandError(f"'{name}': " + " ".join(problems))
    return rows


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
        if any(m.objects.filter(source=SOURCE).exists() for m in MODELS):
            raise CommandError("The sheet is already imported. Run with --undo first to re-import.")

        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True)
        monthly = [r for tab in MONTH_TABS for r in read_tab(wb, tab)]
        opening = read_tab(wb, "Opening")

        plan = defaultdict(list)  # destination -> rows (with mapping info)
        vendor_of = vendor_matcher()
        monthly_staff = list(Staff.objects.filter(monthly_salary__gt=0))
        for r in monthly:
            route(r, vendor_of, monthly_staff)
            plan[r["dest"]].append(r)
        for r in opening:
            r.update(dest="opening", category=OPENING_CATEGORIES.get(r["type"], "misc"))
            plan["opening"].append(r)

        self.report(monthly, opening, plan)
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing was saved."))
            return
        saver = Saver(SOURCE)
        with transaction.atomic():
            for rows in plan.values():
                for r in rows:
                    saver.save(r)
        self.stdout.write(self.style.SUCCESS("Imported. Undo any time with: manage.py import_expense_sheet --undo"))

    def report(self, monthly, opening, plan):
        w = self.stdout.write
        total = lambda rows: sum((r["amount"] for r in rows), Decimal(0))  # noqa: E731
        w(f"Sheet: {len(monthly)} rows in {', '.join(MONTH_TABS)} (₹{total(monthly):,.0f}), "
          f"{len(opening)} rows in Opening (₹{total(opening):,.0f})")
        for dest, label in (("expenses", "expenses"), ("vendor", "bills"), ("fixed", "fixed"),
                            ("salary", "salary"), ("opening", "opening")):
            w(f"  -> {label:9} {len(plan[dest]):4} rows  ₹{total(plan[dest]):>12,.0f}")
        mapped = total([r for rows in plan.values() for r in rows])
        w(f"     total     {sum(len(v) for v in plan.values()):4} rows  ₹{mapped:>12,.0f}")
        by_item = defaultdict(lambda: [0, Decimal(0)])
        for r in plan["expenses"]:
            by_item[r["item"][0]][0] += 1
            by_item[r["item"][0]][1] += r["amount"]
        w("  Daily expense items:")
        for name, (n, amt) in sorted(by_item.items(), key=lambda x: -x[1][1]):
            w(f"     {name:32} {n:3}  ₹{amt:>10,.0f}")

    def undo(self):
        with transaction.atomic():
            counts = {m.__name__: m.objects.filter(source=SOURCE).delete()[0] for m in MODELS}
        self.stdout.write(self.style.SUCCESS(f"Removed imported rows: {counts}"))
        self.stdout.write("Items, staff and people created by the import were kept; delete them in Admin if unwanted.")
