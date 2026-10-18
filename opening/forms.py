from django import forms

from core.models import Payer

from .models import OpeningCost


class OpeningCostForm(forms.ModelForm):
    class Meta:
        model = OpeningCost
        fields = ["date", "amount", "category", "paid_to", "description", "paid_by", "bill_file"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paid_by"].queryset = Payer.objects.filter(is_active=True) | (
            Payer.objects.filter(pk=self.instance.paid_by_id) if self.instance.pk else Payer.objects.none()
        )
        if not self.instance.pk and not self.initial.get("paid_by"):
            self.initial["paid_by"] = Payer.default()
