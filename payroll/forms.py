from django import forms

from core.models import Payer

from .models import Leave, SalaryPayment, Staff


class StaffForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ["name", "role", "phone", "monthly_salary", "leave_allowance", "joined_on", "left_on", "is_active", "notes"]
        widgets = {
            "joined_on": forms.DateInput(attrs={"type": "date"}),
            "left_on": forms.DateInput(attrs={"type": "date"}),
        }


class MonthInput(forms.DateInput):
    input_type = "month"

    def format_value(self, value):
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m")
        return value


class PaymentForm(forms.ModelForm):
    month = forms.DateField(widget=MonthInput(), input_formats=["%Y-%m", "%Y-%m-%d"], help_text="Salary month this counts towards")

    class Meta:
        model = SalaryPayment
        fields = ["staff", "month", "kind", "amount", "paid_on", "payment_mode", "paid_by", "note"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get("paid_by"):
            self.initial["paid_by"] = Payer.default()


class LeaveForm(forms.ModelForm):
    class Meta:
        model = Leave
        fields = ["staff", "start", "end", "half_day", "kind", "note"]
        widgets = {
            "start": forms.DateInput(attrs={"type": "date"}),
            "end": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        staff = Staff.objects.filter(is_active=True)
        if self.instance.pk:
            staff = staff | Staff.objects.filter(pk=self.instance.staff_id)
        self.fields["staff"].queryset = staff
        self.fields["end"].required = False

    def clean(self):
        data = super().clean()
        staff, start, end = data.get("staff"), data.get("start"), data.get("end")
        if not (staff and start):
            return data
        end = data["end"] = end or start
        if end < start:
            self.add_error("end", "'To' can't be before 'From'.")
        elif data.get("half_day") and end != start:
            self.add_error("half_day", "A half day is a single day: make 'To' the same as 'From'.")
        else:
            clash = Leave.objects.filter(staff=staff, start__lte=end, end__gte=start).exclude(pk=self.instance.pk).first()
            if clash:
                raise forms.ValidationError(f"{staff} already has leave recorded for {clash.start:%d %b}"
                                            + (f"–{clash.end:%d %b}" if clash.end != clash.start else "") + ".")
        return data
