from django import forms

from core.models import Payer

from .models import SalaryPayment, Staff


class StaffForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ["name", "role", "phone", "monthly_salary", "joined_on", "left_on", "is_active", "notes"]
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
