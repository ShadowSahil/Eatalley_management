# Eatalley management

Internal website for the Eatalley team: daily expenses, Petpooja sales, inventory bills, staff salaries and P&L.
Everyone logs in with their own username; all team members have the same access.

| Page | What it does |
|---|---|
| **Daily expense** (home page) | Add several expenses at once: the date defaults to today (any earlier date can be picked), choose the item from the dropdown, then enter quantity, amount and how it was paid. The amount fills in automatically from the last price paid. New items can be added from the dropdown. |
| **Sales** | Upload a Petpooja Excel/CSV export. Shows total and net sales, orders, average order, discounts, GST, mode of payment, order type, channel, item-wise and category-wise sales, filtered by Daily / Weekly / Monthly / Quarterly / Financial year / custom range. |
| **Inventory** | Vendor bills (JS Foods, Sunrise, Neveen, Hyperpure, Mokafarms, plus any others you add). Upload the PDF and the site tries to read the vendor, bill number, date and total, or enter them by hand. Tracks unpaid bills. |
| **P&L** | Sales (excluding GST) minus inventory bills, daily expenses and salaries, with a statement, chart and breakdown for any period. |
| **Opening costs** | One-time setup spending (oven, furniture, fit-out, launch), kept outside the P&L. You can keep adding to it. |
| **Who paid** | Every expense, bill, salary and opening cost records who paid: Eatalley's own money or a partner. This page totals it per person, like the old sheet's "Per user" tab. |
| **Staff** | Staff list with monthly salary. Record salary, advances and bonuses, and see each person's outstanding balance for the month. |

Financial years run April–March, and quarters are financial quarters (Q1 = Apr–Jun).

## Running it on your computer

Requires Python 3.10 or newer (the project was built on 3.12).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser      # your own login
.venv/bin/python manage.py runserver
```

Open http://127.0.0.1:8000. Add the rest of the team under **More → Team logins**.

Run the tests with `.venv/bin/python manage.py test`.

## Loading your data

- **Vendor bills**: Hyperpure PDFs are read automatically, including each item and the GST; check the filled-in form before saving. When one PDF holds two invoices (a Bill of Supply plus a Tax Invoice for the same order), they are saved together as one bill.
- **Old bills for payments already recorded**: upload them the normal way (Inventory → Add bill → Read bill). If a payment from the old sheet matches the bill, choose **Attach to that entry**. If the vendor was paid several bills in one go, choose **Part of ₹… paid …**: the bill is saved as paid and its amount comes off that payment, which disappears once all its bills are in. Either way nothing is counted twice.
- **Expense item list**: go to **More → Expense items → Import a list from Excel**. Upload a sheet with an `Item` column; `Unit` and `Category` columns are optional. Milk, Cold Drink and Coconut Water are already in the list.
- **Petpooja sales**: in Petpooja, export the *Order Report* (the `Order_Listing_….xlsx` file, one row per bill) and, for item-wise numbers, the *Item wise* report. Part payments (e.g. ₹76 UPI + ₹1,000 cash on one bill) are split by payment mode; customer names and phone numbers in the export are not stored. Upload them under **Sales → Upload Petpooja Excel**. Uploading a file again for the same dates replaces the earlier numbers.
  The importer finds the header row and matches common Petpooja column names. If an export isn't recognised, add its column names to `ORDER_FIELDS` / `ITEM_FIELDS` in `sales/importer.py`.
- **Old Google Sheet (Aug–Oct 2026)**: already imported with `python manage.py import_expense_sheet <sheet.xlsx>`. Vendor payments became inventory bills, salaries became staff payments ("Adhoc helper" for daily labour), equipment, interior and the Opening tab became opening costs, and everything else became daily expenses. `--dry-run` previews; `--undo` removes everything it imported.
- **Petpooja API**: when Petpooja makes it available, it can feed the same `SaleOrder` / `SaleItemLine` tables that the Excel importer fills, so the dashboards won't need to change.

## Hosting (later)

Everything that changes between a laptop and a server is read from environment variables:

| Variable | Example |
|---|---|
| `DJANGO_SECRET_KEY` | a long random string |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_ALLOWED_HOSTS` | `eatalley.onrender.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://eatalley.onrender.com` |
| `DATABASE_URL` | `postgres://…` (if not set, a local SQLite file is used) |
| `DJANGO_MEDIA_ROOT` | a path on a persistent disk, for uploaded bills and Excel files |

Build: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
Start: `gunicorn eatalley.wsgi`

Uploaded files must live on a persistent disk (or the server must be one that keeps files between restarts). They are served only to logged-in users.
