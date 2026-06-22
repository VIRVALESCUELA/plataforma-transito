from django import forms

from .models import ScheduleResource


class ScheduleResourceForm(forms.ModelForm):
    class Meta:
        model = ScheduleResource
        fields = ["name", "instructor", "vehicle", "color", "sort_order", "is_active"]
        labels = {
            "name": "Nombre de grilla",
            "instructor": "Instructor",
            "vehicle": "Auto / patente",
            "color": "Color de grilla",
            "sort_order": "Orden",
            "is_active": "Activo",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Juan / Auto ABCD-12"}),
            "instructor": forms.TextInput(attrs={"placeholder": "Juan Perez"}),
            "vehicle": forms.TextInput(attrs={"placeholder": "ABCD-12"}),
            "color": forms.TextInput(attrs={"type": "color"}),
            "sort_order": forms.NumberInput(attrs={"min": 1}),
        }
