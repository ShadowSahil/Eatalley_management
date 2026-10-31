from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Payer
from core.periods import add_months, month_end, parse_date, today
from core.templatetags.money import format_inr

from .forms import LeaveForm, PaymentForm, StaffForm
from .models import Leave, SalaryPayment, Staff
from .services import leave_days

ZERO = Decimal(0)


def _month_from(request):
    raw = request.GET.get("month", "")
    d = parse_date(f"{raw}-01") if len(raw) == 7 else None
    return (d or today()).replace(day=1)


def _url(month):
    return f"{reverse('payroll:index')}?month={month:%Y-%m}"


def index(request):
    month = _month_from(request)
    m_end = month_end(month)
    payments = SalaryPayment.objects.filter(month=month).select_related("staff", "created_by").order_by("paid_on")
    paid = defaultdict(lambda: defaultdict(lambda: ZERO))
    for p in payments:
        paid[p.staff_id][p.kind] += p.amount

    off = leave_days(month, m_end)
    rows = []
    for s in Staff.objects.all():
        if not s.employed_during(month, m_end) and s.id not in paid and s.id not in off:
            continue
        got = paid.get(s.id, {})
        total_paid = sum(got.values(), ZERO)
        rows.append({
            "staff": s,
            "leave_days": off.get(s.id, ZERO),
            "over_allowance": max(off.get(s.id, ZERO) - s.leave_allowance, ZERO),
            "salary_paid": got.get("salary", ZERO),
            "advance": got.get("advance", ZERO),
            "bonus": got.get("bonus", ZERO),
            "total_paid": total_paid,
            "balance": max(s.monthly_salary - got.get("salary", ZERO) - got.get("advance", ZERO), ZERO),
        })

    return render(request, "payroll/index.html", {
        "month": month,
        "prev_month": add_months(month, -1),
        "next_month": add_months(month, 1),
        "rows": rows,
        "payments": payments,
        "total_paid": payments.aggregate(v=Sum("amount"))["v"] or ZERO,
        "total_salary": sum((r["staff"].monthly_salary for r in rows if r["staff"].is_active), ZERO),
        "total_balance": sum((r["balance"] for r in rows), ZERO),
        "staff_form": StaffForm(prefix="staff"),
        "leaves": Leave.objects.filter(start__lte=m_end, end__gte=month).select_related("staff").order_by("start"),
    })


def staff_add(request):
    form = StaffForm(request.POST or None, prefix="staff")
    if request.method == "POST" and form.is_valid():
        s = form.save()
        messages.success(request, f"Added {s.name}.")
        return redirect("payroll:index")
    return render(request, "core/form_page.html", {"form": form, "title": "Add staff member", "back": "payroll:index"})


def staff_edit(request, pk):
    staff = get_object_or_404(Staff, pk=pk)
    form = StaffForm(request.POST or None, instance=staff)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved {staff.name}.")
        return redirect("payroll:index")
    history = staff.payments.order_by("-month", "-paid_on")[:24]
    # Leave days per month for the last 12 months, against the allowance.
    this_month = today().replace(day=1)
    leave_months = []
    for i in range(12):
        m = add_months(this_month, -i)
        if staff.joined_on and month_end(m) < staff.joined_on:
            break
        days = leave_days(m, month_end(m)).get(staff.id, ZERO)
        leave_months.append({"month": m, "days": days, "over": max(days - staff.leave_allowance, ZERO)})
    return render(request, "payroll/staff_edit.html", {
        "form": form, "staff": staff, "history": history,
        "leaves": staff.leaves.all()[:30], "leave_months": leave_months,
    })


def payment_form(request, pk=None):
    payment = get_object_or_404(SalaryPayment, pk=pk) if pk else None
    initial = {}
    if not payment:
        month = _month_from(request)
        initial = {"month": month, "paid_on": today(), "kind": request.GET.get("kind", "salary")}
        staff_id = request.GET.get("staff", "")
        if staff_id.isdigit():
            initial["staff"] = int(staff_id)
            if request.GET.get("amount"):
                initial["amount"] = request.GET["amount"]
    form = PaymentForm(request.POST or None, instance=payment, initial=initial)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        if not payment:
            p.created_by = request.user
        p.save()
        messages.success(request, f"Recorded {p.get_kind_display().lower()} of {format_inr(p.amount)} for {p.staff} ({p.month:%b %Y}).")
        return redirect(_url(p.month))
    return render(request, "core/form_page.html", {
        "form": form,
        "title": "Edit payment" if payment else "Record salary payment",
        "back_url": _url(payment.month if payment else initial["month"]),
        "delete_url": reverse("payroll:payment_delete", args=[payment.pk]) if payment else None,
    })


@require_POST
def payment_delete(request, pk):
    p = get_object_or_404(SalaryPayment, pk=pk)
    p.delete()
    messages.success(request, f"Deleted payment of {format_inr(p.amount)} to {p.staff}.")
    return redirect(_url(p.month))


@require_POST
def pay_all(request):
    """Record the remaining salary for everyone who still has a balance this month."""
    month = parse_date(request.POST.get("month"), today()).replace(day=1)
    m_end = month_end(month)
    created = ZERO
    n = 0
    for s in Staff.objects.filter(is_active=True):
        if not s.employed_during(month, m_end):
            continue
        done = SalaryPayment.objects.filter(staff=s, month=month, kind__in=["salary", "advance"]).aggregate(v=Sum("amount"))["v"] or ZERO
        balance = s.monthly_salary - done
        if balance > 0:
            SalaryPayment.objects.create(
                staff=s, month=month, kind="salary", amount=balance, paid_on=today(),
                payment_mode=request.POST.get("payment_mode") or "cash", paid_by=Payer.default(), created_by=request.user,
            )
            created += balance
            n += 1
    if n:
        messages.success(request, f"Recorded salary for {n} staff — {format_inr(created)} for {month:%B %Y}.")
    else:
        messages.info(request, "Everyone is already paid for this month.")
    return redirect(_url(month))


def leave_form(request, pk=None):
    leave = get_object_or_404(Leave, pk=pk) if pk else None
    initial = {}
    if not leave:
        day = parse_date(request.GET.get("date"), today())
        initial = {"start": day, "end": day}
        if request.GET.get("staff", "").isdigit():
            initial["staff"] = int(request.GET["staff"])
    form = LeaveForm(request.POST or None, instance=leave, initial=initial)
    if request.method == "POST" and form.is_valid():
        lv = form.save(commit=False)
        if not leave:
            lv.created_by = request.user
        lv.save()
        days = f"{lv.days.normalize():f} day{'s' if lv.days != 1 else ''}"
        messages.success(request, f"{'Saved' if leave else 'Recorded'} leave for {lv.staff}: {days} from {lv.start:%d %b}.")
        return redirect(_url(lv.start.replace(day=1)))
    month = (leave.start if leave else initial["start"]).replace(day=1)
    return render(request, "core/form_page.html", {
        "form": form,
        "title": "Edit leave" if leave else "Record leave",
        "back_url": _url(month),
        "delete_url": reverse("payroll:leave_delete", args=[leave.pk]) if leave else None,
    })


@require_POST
def leave_delete(request, pk):
    lv = get_object_or_404(Leave, pk=pk)
    lv.delete()
    messages.success(request, f"Deleted leave for {lv.staff} ({lv.start:%d %b}).")
    return redirect(_url(lv.start.replace(day=1)))
