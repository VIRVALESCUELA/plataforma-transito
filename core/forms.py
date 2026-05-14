from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import ActivationCode, Inscripcion, Profile, UserRole


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
            now = timezone.now()
            if activation:
                profile.access_activated_at = now
                profile.access_expires_at = now + timedelta(days=activation.duration_days)
                profile.activated_course_name = activation.course_name
                profile.save(
                    update_fields=[
                        "access_activated_at",
                        "access_expires_at",
                        "activated_course_name",
                    ]
                )
                activation.used_by = user
                activation.used_at = now
                activation.save(update_fields=["used_by", "used_at"])

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
        fields = ["nombre", "comuna", "correo", "telefono", "curso"]
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "Ingresa tu nombre completo", "maxlength": 80}),
            "comuna": forms.TextInput(attrs={"placeholder": "Ej: Penalolen", "maxlength": 80}),
            "correo": forms.EmailInput(attrs={"placeholder": "tu@email.cl", "maxlength": 80}),
            "telefono": forms.TextInput(attrs={"placeholder": "+56 9 1234 5678", "maxlength": 80}),
            "curso": forms.Select(),
        }
