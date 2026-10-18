from django import forms

from .models import DailyExpense, ExpenseItem


class ExpenseItemForm(forms.ModelForm):
    class Meta:
        model = ExpenseItem
        fields = ["name", "category", "unit", "is_active"]

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = ExpenseItem.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("An item with this name already exists.")
        return name


class DailyExpenseForm(forms.ModelForm):
    class Meta:
        model = DailyExpense
        fields = ["date", "item", "quantity", "amount", "payment_mode", "paid_by", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active = ExpenseItem.objects.filter(is_active=True)
        if self.instance.pk:
            active = active | ExpenseItem.objects.filter(pk=self.instance.item_id)
        self.fields["item"].queryset = active


class ImportFileForm(forms.Form):
    file = forms.FileField(help_text="Excel (.xlsx) or CSV with an 'Item' column. 'Unit' and 'Category' columns are optional.")
