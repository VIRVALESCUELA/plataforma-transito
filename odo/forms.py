from decimal import Decimal

from django.contrib.auth import get_user_model
from django import forms
from django.utils import timezone

from .models import (
    FuelEntry,
    MaintenanceRecord,
    MaintenanceSchedule,
    Vehicle,
    VehicleAccess,
    VehicleDocument,
    normalize_plate,
    validate_plate,
)
from .permissions import accessible_vehicles_for


MAINTENANCE_TYPE_CHOICES = [
    (
        "DOCUMENTOS Y CONTROL LEGAL",
        [
            ("Revision tecnica", "Revision tecnica"),
            ("Permiso circulacion", "Permiso circulacion"),
            ("SOAP", "SOAP"),
            ("Seguro automotriz", "Seguro automotriz"),
            ("Extintor", "Extintor"),
            ("Botiquin", "Botiquin"),
            ("Triangulos", "Triangulos"),
            ("Chaleco reflectante", "Chaleco reflectante"),
        ],
    ),
    (
        "MOTOR Y LUBRICACION",
        [
            ("Aceite motor", "Aceite motor"),
            ("Filtro de aceite", "Filtro de aceite"),
            ("Filtro de aire motor", "Filtro de aire motor"),
            ("Filtro de combustible", "Filtro de combustible"),
            ("Filtro de polen / cabina", "Filtro de polen / cabina"),
            ("Refrigerante / anticongelante", "Refrigerante / anticongelante"),
            ("Liquido direccion hidraulica", "Liquido direccion hidraulica"),
            ("Liquido frenos", "Liquido frenos"),
            ("Aceite caja automatica", "Aceite caja automatica"),
            ("Aceite caja mecanica", "Aceite caja mecanica"),
            ("Aceite diferencial", "Aceite diferencial"),
            ("Aceite transferencia 4x4", "Aceite transferencia 4x4"),
            ("Correa distribucion", "Correa distribucion"),
            ("Cadena distribucion", "Cadena distribucion"),
            ("Correa accesorios", "Correa accesorios"),
            ("Tensor correa", "Tensor correa"),
            ("Bujias", "Bujias"),
            ("Bujias incandescentes diesel", "Bujias incandescentes diesel"),
            ("Inyectores", "Inyectores"),
            ("Limpieza cuerpo aceleracion", "Limpieza cuerpo aceleracion"),
            ("Limpieza EGR", "Limpieza EGR"),
            ("Turbo", "Turbo"),
            ("PCV / valvula ventilacion", "PCV / valvula ventilacion"),
            ("Soportes motor", "Soportes motor"),
        ],
    ),
    (
        "FRENOS",
        [
            ("Pastillas delanteras", "Pastillas delanteras"),
            ("Pastillas traseras", "Pastillas traseras"),
            ("Discos delanteros", "Discos delanteros"),
            ("Discos traseros", "Discos traseros"),
            ("Balatas", "Balatas"),
            ("Tambores", "Tambores"),
            ("Liquido frenos", "Liquido frenos"),
            ("Sensor desgaste freno", "Sensor desgaste freno"),
            ("Mordazas", "Mordazas"),
            ("ABS sensores", "ABS sensores"),
        ],
    ),
    (
        "SUSPENSION Y DIRECCION",
        [
            ("Amortiguadores", "Amortiguadores"),
            ("Espirales", "Espirales"),
            ("Bandejas", "Bandejas"),
            ("Bujes", "Bujes"),
            ("Rotulas", "Rotulas"),
            ("Terminales direccion", "Terminales direccion"),
            ("Cremallera direccion", "Cremallera direccion"),
            ("Barra estabilizadora", "Barra estabilizadora"),
            ("Bieletas", "Bieletas"),
            ("Alineacion", "Alineacion"),
            ("Balanceo", "Balanceo"),
        ],
    ),
    (
        "NEUMATICOS",
        [
            ("Neumaticos delanteros", "Neumaticos delanteros"),
            ("Neumaticos traseros", "Neumaticos traseros"),
            ("Rotacion neumaticos", "Rotacion neumaticos"),
            ("Balanceo ruedas", "Balanceo ruedas"),
            ("Alineacion", "Alineacion"),
            ("Repuesto", "Repuesto"),
            ("Sensor TPMS", "Sensor TPMS"),
        ],
    ),
    (
        "SISTEMA ELECTRICO",
        [
            ("Bateria", "Bateria"),
            ("Alternador", "Alternador"),
            ("Motor partida", "Motor partida"),
            ("Fusibles", "Fusibles"),
            ("Reles", "Reles"),
            ("Luces delanteras", "Luces delanteras"),
            ("Luces traseras", "Luces traseras"),
            ("Luces freno", "Luces freno"),
            ("Intermitentes", "Intermitentes"),
            ("Escobillas limpiaparabrisas", "Escobillas limpiaparabrisas"),
            ("Sistema carga", "Sistema carga"),
        ],
    ),
    (
        "CLIMATIZACION",
        [
            ("Gas aire acondicionado", "Gas aire acondicionado"),
            ("Compresor AC", "Compresor AC"),
            ("Filtro cabina/polen", "Filtro cabina/polen"),
            ("Ventilador habitaculo", "Ventilador habitaculo"),
            ("Radiador calefaccion", "Radiador calefaccion"),
        ],
    ),
    (
        "REFRIGERACION",
        [
            ("Radiador", "Radiador"),
            ("Termostato", "Termostato"),
            ("Electroventilador", "Electroventilador"),
            ("Bomba agua", "Bomba agua"),
            ("Mangueras refrigerante", "Mangueras refrigerante"),
            ("Deposito expansion", "Deposito expansion"),
        ],
    ),
    (
        "ESCAPE Y EMISIONES",
        [
            ("Catalizador", "Catalizador"),
            ("Filtro DPF", "Filtro DPF"),
            ("Sensor oxigeno", "Sensor oxigeno"),
            ("Sensor NOx", "Sensor NOx"),
            ("Escape", "Escape"),
            ("Silenciador", "Silenciador"),
        ],
    ),
    (
        "TRANSMISION",
        [
            ("Embrague", "Embrague"),
            ("Kit embrague", "Kit embrague"),
            ("Volante bimasa", "Volante bimasa"),
            ("Homocineticas", "Homocineticas"),
            ("Crucetas", "Crucetas"),
            ("Cardan", "Cardan"),
        ],
    ),
    (
        "SEGURIDAD",
        [
            ("Airbags", "Airbags"),
            ("Cinturones", "Cinturones"),
            ("Sensores ABS", "Sensores ABS"),
            ("Camaras", "Camaras"),
            ("Sensores estacionamiento", "Sensores estacionamiento"),
        ],
    ),
    (
        "CARROCERIA Y EXTERIOR",
        [
            ("Bisagras", "Bisagras"),
            ("Cerraduras", "Cerraduras"),
            ("Amortiguadores portalon", "Amortiguadores portalon"),
            ("Sellos puertas", "Sellos puertas"),
            ("Parabrisas", "Parabrisas"),
        ],
    ),
  
]


ALERT_MAINTENANCE_TYPE_CHOICES = [
    (
        "ALERTAS PRINCIPALES",
        [
            ("Aceite motor", "Cambio de aceite"),
            ("Revision tecnica", "Revision tecnica/Gases"),
        ],
    ),
    (
        "DOCUMENTOS CON FECHA FIJA",
        [
            ("Permiso circulacion", "Permiso circulacion"),
            ("SOAP", "SOAP"),
            ("Seguro automotriz", "Seguro automotriz"),
        ],
    ),
]


CUSTOM_ALERT_CHOICES = [
    (value, label)
    for _group_label, group_choices in MAINTENANCE_TYPE_CHOICES
    for value, label in group_choices
]


class VehicleForm(forms.ModelForm):
    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    class Meta:
        model = Vehicle
        fields = ["plate", "alias", "brand", "model", "year", "current_odometer"]
        labels = {
            "plate": "Patente",
            "alias": "VIN",
            "brand": "Marca",
            "model": "Modelo",
            "year": "Año",
            "current_odometer": "Kilometraje actual",
        }
        widgets = {
            "plate": forms.TextInput(
                attrs={
                    "placeholder": "Ej: ABCD12",
                    "maxlength": 6,
                    "pattern": "([A-Za-z]{4}[0-9]{2}|[A-Za-z]{2}[0-9]{4})",
                    "title": "Formato chileno: ABCD12 o AB1234, sin guiones.",
                    "autocomplete": "off",
                }
            ),
            "alias": forms.TextInput(attrs={"placeholder": "Ej: 1GCEG16Z0E123456"}),
            "brand": forms.TextInput(attrs={"placeholder": "Ej: Toyota"}),
            "model": forms.TextInput(attrs={"placeholder": "Ej: Yaris"}),
            "year": forms.NumberInput(attrs={"min": 1900, "max": 2100}),
            "current_odometer": forms.NumberInput(attrs={"min": 0}),
        }

    def clean_plate(self):
        plate = normalize_plate(self.cleaned_data.get("plate"))
        validate_plate(plate)
        existing_vehicle = Vehicle.objects.filter(plate=plate).first()
        if existing_vehicle:
            if self.owner and (
                self.owner.is_superuser
                or existing_vehicle.staff_access.filter(user=self.owner).exists()
            ):
                raise forms.ValidationError("Esta patente ya existe en ODO.")
            raise forms.ValidationError(
                "Esta patente ya existe. Pide acceso al administrador."
            )
        return plate

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.owner and not instance.owner_id:
            instance.owner = self.owner
        if commit:
            instance.save()
            if self.owner and self.owner.is_staff:
                VehicleAccess.objects.get_or_create(vehicle=instance, user=self.owner)
        return instance


class OwnerVehicleFormMixin:
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["vehicle"].queryset = accessible_vehicles_for(user)


class VehicleAccessForm(forms.ModelForm):
    class Meta:
        model = VehicleAccess
        fields = ["user", "vehicle"]
        labels = {
            "user": "Staff",
            "vehicle": "Patente",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["user"].queryset = user_model.objects.filter(
            is_staff=True,
            is_active=True,
        ).order_by("email", "username")
        self.fields["vehicle"].queryset = Vehicle.objects.all().order_by("plate")
        self.fields["user"].empty_label = "Selecciona staff"
        self.fields["vehicle"].empty_label = "Selecciona patente"


class VehicleDocumentForm(OwnerVehicleFormMixin, forms.ModelForm):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label="Vehiculo",
        empty_label="Selecciona vehiculo",
    )

    class Meta:
        model = VehicleDocument
        fields = ["vehicle", "document_type", "file", "issued_at", "expires_at", "notes"]
        labels = {
            "document_type": "Tipo de documento",
            "file": "Archivo",
            "issued_at": "Fecha de emision",
            "expires_at": "Fecha de vencimiento",
            "notes": "Notas",
        }
        widgets = {
            "issued_at": forms.DateInput(attrs={"type": "date"}),
            "expires_at": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def save(self, commit=True, uploaded_by=None):
        instance = super().save(commit=False)
        if uploaded_by is not None:
            instance.uploaded_by = uploaded_by
        if commit:
            instance.save()
        return instance


class FuelEntryForm(OwnerVehicleFormMixin, forms.ModelForm):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label="Vehiculo",
        empty_label="Selecciona vehiculo",
    )
    total_cost = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=True,
        label="Monto cargado",
        min_value=Decimal("0"),
    )

    class Meta:
        model = FuelEntry
        fields = [
            "vehicle",
            "date",
            "odometer",
            "liters",
            "total_cost",
            "notes",
        ]
        labels = {
            "date": "Fecha",
            "odometer": "Kilometraje",
            "liters": "Litros",
            "notes": "Notas",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "odometer": forms.NumberInput(attrs={"min": 0}),
            "liters": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_date(self):
        return self.cleaned_data.get("date") or timezone.localdate()

    def clean(self):
        cleaned_data = super().clean()
        vehicle = cleaned_data.get("vehicle")
        odometer = cleaned_data.get("odometer")
        liters = cleaned_data.get("liters")
        total_cost = cleaned_data.get("total_cost")
        if (
            vehicle is not None
            and odometer is not None
            and odometer < vehicle.current_odometer
        ):
            self.add_error(
                "odometer",
                f"El kilometraje no puede ser menor al actual ({vehicle.current_odometer} km).",
            )
        if liters is not None and liters <= 0:
            self.add_error("liters", "Los litros deben ser mayores a cero.")
        if liters is not None and total_cost is not None and liters > 0:
            cleaned_data["price_per_liter"] = (total_cost / liters).quantize(
                Decimal("0.01")
            )
        return cleaned_data

    def save(self, commit=True, created_by=None):
        instance = super().save(commit=False)
        instance.price_per_liter = self.cleaned_data["price_per_liter"]
        if created_by is not None:
            instance.created_by = created_by
        if commit:
            instance.save()
        return instance


class MaintenanceTypeMultipleChoiceField(forms.MultipleChoiceField):
    def to_python(self, value):
        if value in self.empty_values:
            return []
        if isinstance(value, str):
            return [value]
        return super().to_python(value)


class MaintenanceScheduleForm(OwnerVehicleFormMixin, forms.ModelForm):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label="Vehiculo",
        empty_label="Selecciona vehiculo",
    )
    name = MaintenanceTypeMultipleChoiceField(
        choices=ALERT_MAINTENANCE_TYPE_CHOICES,
        label="Alertas a controlar",
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    custom_name = forms.ChoiceField(
        choices=[("", "Selecciona mantencion")] + CUSTOM_ALERT_CHOICES,
        label="Alerta personalizada",
        required=False,
    )

    class Meta:
        model = MaintenanceSchedule
        fields = ["vehicle", "name", "due_odometer", "due_date", "notes"]
        labels = {
            "name": "Alertas",
            "due_odometer": "Vence en kilometraje",
            "due_date": "Vence en fecha",
            "notes": "Nota de alerta",
        }
        widgets = {
            "due_odometer": forms.NumberInput(attrs={"min": 0}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        selected_names = cleaned_data.get("name") or []
        custom_name = cleaned_data.get("custom_name")
        if not selected_names and not custom_name:
            raise forms.ValidationError(
                "Selecciona una alerta rapida o una alerta personalizada."
            )
        if not cleaned_data.get("due_odometer") and not cleaned_data.get("due_date"):
            raise forms.ValidationError(
                "Indica kilometraje, fecha o ambos para programar la mantencion."
            )
        return cleaned_data

    def save_many(self):
        vehicle = self.cleaned_data["vehicle"]
        due_odometer = self.cleaned_data.get("due_odometer")
        due_date = self.cleaned_data.get("due_date")
        notes = self.cleaned_data.get("notes", "")
        names = list(self.cleaned_data["name"])
        custom_name = self.cleaned_data.get("custom_name")
        if custom_name and custom_name not in names:
            names.append(custom_name)
        schedules = []
        for name in names:
            schedules.append(
                MaintenanceSchedule.objects.create(
                    vehicle=vehicle,
                    name=name,
                    due_odometer=due_odometer,
                    due_date=due_date,
                    notes=notes,
                )
            )
        return schedules


class MaintenanceRecordForm(OwnerVehicleFormMixin, forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label="Vehiculo",
        empty_label="Selecciona vehiculo",
    )
    services = MaintenanceTypeMultipleChoiceField(
        choices=MAINTENANCE_TYPE_CHOICES,
        label="Mantenciones realizadas",
        widget=forms.CheckboxSelectMultiple,
    )
    date = forms.DateField(
        required=False,
        label="Fecha",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    odometer = forms.IntegerField(
        min_value=0,
        label="Kilometraje",
        widget=forms.NumberInput(attrs={"min": 0}),
    )
    cost = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Costo total",
        min_value=Decimal("0"),
    )
    notes = forms.CharField(
        required=False,
        label="Notas",
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean_date(self):
        return self.cleaned_data.get("date") or timezone.localdate()

    def clean(self):
        cleaned_data = super().clean()
        vehicle = cleaned_data.get("vehicle")
        odometer = cleaned_data.get("odometer")
        if (
            vehicle is not None
            and odometer is not None
            and odometer < vehicle.current_odometer
        ):
            self.add_error(
                "odometer",
                f"El kilometraje no puede ser menor al actual ({vehicle.current_odometer} km).",
            )
        return cleaned_data

    def save_many(self, created_by=None):
        vehicle = self.cleaned_data["vehicle"]
        date = self.cleaned_data["date"]
        odometer = self.cleaned_data["odometer"]
        cost = self.cleaned_data.get("cost") or Decimal("0")
        notes = self.cleaned_data.get("notes", "")
        records = []
        for service in self.cleaned_data["services"]:
            records.append(
                MaintenanceRecord.objects.create(
                    vehicle=vehicle,
                    name=service,
                    date=date,
                    odometer=odometer,
                    cost=cost,
                    notes=notes,
                    created_by=created_by,
                )
            )
        return records
