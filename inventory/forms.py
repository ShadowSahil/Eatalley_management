from django import forms

from core.models import Payer

from .models import Purchase, PurchaseLine, Vendor


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "category", "supplies", "match_keywords", "phone", "gstin", "is_active"]


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = [
            "vendor", "bill_date", "bill_number", "category", "total", "tax_amount",
            "bill_file", "is_paid", "paid_on", "payment_mode", "paid_by", "notes",
        ]
        widgets = {
            "bill_date": forms.DateInput(attrs={"type": "date"}),
            "paid_on": forms.DateInput(attrs={"type": "date"}),
            "bill_file": forms.ClearableFileInput(attrs={"accept": "application/pdf,image/*"}),
        }
        help_texts = {
            "bill_file": "PDF or photo of the bill (optional)",
            "total": "Leave empty to use the sum of the lines below",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["total"].required = False
        vendors = Vendor.objects.filter(is_active=True)
        if self.instance.pk:
            vendors = vendors | Vendor.objects.filter(pk=self.instance.vendor_id)
        self.fields["vendor"].queryset = vendors
        if not self.instance.pk and not self.initial.get("paid_by"):
            self.initial["paid_by"] = Payer.default()

    def clean(self):
        data = super().clean()
        if data.get("is_paid") and not data.get("paid_on"):
            data["paid_on"] = data.get("bill_date")
        return data


def line_formset(extra=4):
    return forms.inlineformset_factory(
        Purchase,
        PurchaseLine,
        fields=["description", "quantity", "unit", "amount"],
        extra=extra,
        can_delete=True,
    )


LineFormSet = line_formset()


class ScanForm(forms.Form):
    pdf = forms.FileField(label="Bill PDF")
