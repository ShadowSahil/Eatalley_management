from django import forms

from core.models import Payer
from payroll.forms import MonthInput

from .models import FixedCost, FixedCostHead


class FixedCostForm(forms.ModelForm):
    month = forms.DateField(widget=MonthInput(), input_formats=["%Y-%m", "%Y-%m-%d"], help_text="Month this cost is for")

    class Meta:
        model = FixedCost
        fields = ["head", "month", "amount", "paid_on", "payment_mode", "paid_by", "note", "bill_file"]
        widgets = {
            "paid_on": forms.DateInput(attrs={"type": "date"}),
            "bill_file": forms.ClearableFileInput(attrs={"accept": "application/pdf,image/*"}),
        }
        help_texts = {"bill_file": "PDF or photo of the bill / receipt (optional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        heads = FixedCostHead.objects.filter(is_active=True)
        if self.instance.pk:
            heads = heads | FixedCostHead.objects.filter(pk=self.instance.head_id)
        self.fields["head"].queryset = heads
        self.fields["paid_by"].queryset = Payer.objects.filter(is_active=True) | (
            Payer.objects.filter(pk=self.instance.paid_by_id) if self.instance.pk else Payer.objects.none()
        )
        if not self.instance.pk and not self.initial.get("paid_by"):
            self.initial["paid_by"] = Payer.default()


class HeadForm(forms.ModelForm):
    class Meta:
        model = FixedCostHead
        fields = ["name", "is_active"]
        labels = {"name": "Name", "is_active": "Expected every month"}

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if FixedCostHead.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A fixed cost with this name already exists.")
        return name
