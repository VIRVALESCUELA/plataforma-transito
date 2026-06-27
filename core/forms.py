from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import ActivationCode, FichaAlumno, FichaMovimiento, Inscripcion, Profile, UserRole
from .services import activate_code_for_user


User = get_user_model()

COURSE_CHOICES = [
    ("", "Selecciona un curso"),
    ("Curso base mecanico", "Curso base mecanico"),
    ("Curso intensivo", "Curso intensivo"),
    ("Curso rush", "Curso rush"),
    ("Curso domicilio", "Curso domicilio"),
    ("Curso teorico", "Curso teorico"),
    ("Ensayo sicotecnico", "Ensayo sicotecnico"),
    ("Teorico promo Instagram", "Teorico promo Instagram"),
    ("Help me!", "Help me!"),
    ("Full automatico", "Full automatico"),
]

FICHA_COURSE_CHOICES = COURSE_CHOICES + [
    ("Clase extra", "Clase extra"),
    ("Ensayo sicotecnico", "Ensayo sicotecnico"),
    ("Simulador", "Simulador"),
    ("Libro", "Libro"),
]


def normalize_chilean_whatsapp(value):
    raw_value = (value or "").strip()
    digits = "".join(char for char in raw_value if char.isdigit())
    if not digits:
        return ""
    if digits.startswith("56"):
        national = digits[2:]
    elif digits.startswith("9"):
        national = digits
    else:
        raise forms.ValidationError("Ingresa un WhatsApp chileno. Ej: +56 9 1234 5678.")
    if len(national) != 9 or not national.startswith("9"):
        raise forms.ValidationError("Ingresa un WhatsApp chileno. Ej: +56 9 1234 5678.")
    return f"+56 {national[0]} {national[1:5]} {national[5:]}"


class StudentSignupForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=False, label="Nombre")
    last_name = forms.CharField(max_length=150, required=False, label="Apellido")
    email = forms.EmailField(required=True, label="Correo")
    activation_code = forms.CharField(
        max_length=40,
        required=False,
        label="Codigo de activacion",
        help_text="Opcional. Si ya tienes un codigo, tu curso queda activo al crear la cuenta.",
        widget=forms.TextInput(attrs={"placeholder": "Ej: CLASEB-ABC123"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "email", "activation_code")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(
            username__iexact=email
        ).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        code = (cleaned_data.get("activation_code") or "").strip()
        email = (cleaned_data.get("email") or "").strip().lower()

        if not code:
            return cleaned_data

        try:
            activation = ActivationCode.objects.select_related("inscripcion").get(code=code)
        except ActivationCode.DoesNotExist as exc:
            raise forms.ValidationError("El codigo de activacion no existe.") from exc

        if not activation.is_enabled:
            raise forms.ValidationError("Este codigo de activacion no esta habilitado.")
        if activation.used_by_id is not None:
            raise forms.ValidationError("Este codigo de activacion ya fue utilizado.")

        inscripcion = getattr(activation, "inscripcion", None)
        if inscripcion and email and inscripcion.correo.lower() != email:
            raise forms.ValidationError(
                "El correo no coincide con la inscripcion asociada a este codigo."
            )

        cleaned_data["activation_instance"] = activation
        cleaned_data["linked_inscripcion"] = inscripcion
        return cleaned_data

    def _find_inscripcion(self):
        if self.cleaned_data.get("linked_inscripcion"):
            return self.cleaned_data["linked_inscripcion"]

        email = self.cleaned_data.get("email")
        if not email:
            return None

        return (
            Inscripcion.objects.filter(correo__iexact=email, user__isnull=True)
            .order_by("-created_at")
            .first()
        )

    def _apply_name_from_inscripcion(self, user, inscripcion):
        if not inscripcion:
            return

        parts = (inscripcion.nombre or "").split()
        if not user.first_name and parts:
            user.first_name = parts[0]
        if not user.last_name and len(parts) > 1:
            user.last_name = " ".join(parts[1:])

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["email"]
        user.first_name = self.cleaned_data.get("first_name") or ""
        user.last_name = self.cleaned_data.get("last_name") or ""
        inscripcion = self._find_inscripcion()
        self.linked_inscripcion = inscripcion
        self._apply_name_from_inscripcion(user, inscripcion)

        if commit:
            user.save()
            profile, _ = Profile.objects.update_or_create(
                user=user, defaults={"role": UserRole.ALUMNO}
            )

            activation = self.cleaned_data.get("activation_instance")
            if activation:
                activate_code_for_user(user, activation)

            if inscripcion:
                inscripcion.user = user
                if activation:
                    inscripcion.status = Inscripcion.Status.CURSO_ACTIVO
                elif inscripcion.status in (
                    Inscripcion.Status.PENDIENTE,
                    Inscripcion.Status.CONTACTADO,
                    Inscripcion.Status.MATRICULADO,
                ):
                    inscripcion.status = Inscripcion.Status.CUENTA_CREADA
                inscripcion.save(update_fields=["user", "status"])

        return user


class ActivationCodeForm(forms.Form):
    activation_code = forms.CharField(
        max_length=40,
        label="Codigo de activacion",
        widget=forms.TextInput(
            attrs={"placeholder": "Ingresa tu codigo del curso"}
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_activation_code(self):
        code = (self.cleaned_data.get("activation_code") or "").strip()
        try:
            activation = ActivationCode.objects.select_related("inscripcion").get(code=code)
        except ActivationCode.DoesNotExist as exc:
            raise forms.ValidationError("El codigo de activacion no existe.") from exc
        if not activation.is_enabled:
            raise forms.ValidationError("Este codigo de activacion no esta habilitado.")
        if activation.used_by_id is not None:
            raise forms.ValidationError("Este codigo de activacion ya fue utilizado.")
        inscripcion = getattr(activation, "inscripcion", None)
        user_email = (getattr(self.user, "email", "") or "").lower()
        if inscripcion and user_email and inscripcion.correo.lower() != user_email:
            raise forms.ValidationError(
                "Este codigo pertenece a una inscripcion con otro correo."
            )
        self.cleaned_data["activation_instance"] = activation
        return code


class InscripcionForm(forms.ModelForm):
    curso = forms.ChoiceField(
        choices=COURSE_CHOICES,
        required=False,
        label="Curso",
    )

    class Meta:
        model = Inscripcion
        fields = ["nombre", "comuna", "direccion", "correo", "telefono", "curso"]
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "Ingresa tu nombre completo", "maxlength": 80}),
            "comuna": forms.TextInput(attrs={"placeholder": "Ej: Penalolen", "maxlength": 80}),
            "direccion": forms.TextInput(attrs={"placeholder": "Ej: Av. Principal 1234", "maxlength": 120}),
            "correo": forms.EmailInput(attrs={"placeholder": "tu@email.cl", "maxlength": 80}),
            "telefono": forms.TextInput(
                attrs={
                    "type": "tel",
                    "inputmode": "tel",
                    "placeholder": "+56 9 1234 5678",
                    "maxlength": 17,
                    "autocomplete": "tel",
                    "pattern": r"(\+?56\s?)?9\s?\d{4}\s?\d{4}",
                    "title": "Formato esperado: +56 9 1234 5678",
                }
            ),
            "curso": forms.Select(),
        }

    def clean_telefono(self):
        return normalize_chilean_whatsapp(self.cleaned_data.get("telefono"))


class FichaAlumnoForm(forms.ModelForm):
    curso = forms.ChoiceField(
        choices=FICHA_COURSE_CHOICES,
        required=False,
        label="Curso / producto",
    )

    class Meta:
        model = FichaAlumno
        fields = [
            "numero_ficha",
            "fecha_inscripcion",
            "nombre",
            "correo",
            "telefono",
            "direccion",
            "curso",
            "rut",
            "fecha_nacimiento",
            "valor_pagado",
            "forma_pago",
            "observaciones",
        ]
        widgets = {
            "numero_ficha": forms.NumberInput(attrs={"min": 1, "placeholder": "Automatico"}),
            "fecha_inscripcion": forms.DateInput(attrs={"type": "date"}),
            "correo": forms.EmailInput(attrs={"placeholder": "alumno@email.cl"}),
            "direccion": forms.TextInput(attrs={"placeholder": "Direccion del alumno"}),
            "telefono": forms.TextInput(
                attrs={
                    "type": "tel",
                    "inputmode": "tel",
                    "placeholder": "+56 9 1234 5678",
                    "maxlength": 17,
                    "autocomplete": "tel",
                    "pattern": r"(\+?56\s?)?9\s?\d{4}\s?\d{4}",
                    "title": "Formato esperado: +56 9 1234 5678",
                }
            ),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_course = self.initial.get("curso") or getattr(self.instance, "curso", "")
        if current_course and current_course not in dict(self.fields["curso"].choices):
            self.fields["curso"].choices = list(self.fields["curso"].choices) + [
                (current_course, current_course)
            ]

    def clean_telefono(self):
        return normalize_chilean_whatsapp(self.cleaned_data.get("telefono"))


class FichaMovimientoForm(forms.ModelForm):
    concepto = forms.ChoiceField(
        choices=FICHA_COURSE_CHOICES + [("Abono", "Abono"), ("Otro", "Otro")],
        label="Concepto",
    )

    class Meta:
        model = FichaMovimiento
        fields = ["fecha", "concepto", "monto", "forma_pago", "observaciones"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "monto": forms.NumberInput(attrs={"min": 0, "placeholder": "0"}),
            "observaciones": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_concept = self.initial.get("concepto") or getattr(self.instance, "concepto", "")
        if current_concept and current_concept not in dict(self.fields["concepto"].choices):
            self.fields["concepto"].choices = list(self.fields["concepto"].choices) + [
                (current_concept, current_concept)
            ]

    def save(self, commit=True):
        movimiento = super().save(commit=False)
        movimiento.tipo = FichaMovimiento.tipo_desde_concepto(movimiento.concepto)
        if commit:
            movimiento.save()
        return movimiento
