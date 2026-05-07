from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

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
    first_name = forms.CharField(max_length=150, required=True, label="Nombre")
    last_name = forms.CharField(max_length=150, required=True, label="Apellido")
    email = forms.EmailField(required=True, label="Correo")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            Profile.objects.update_or_create(
                user=user, defaults={"role": UserRole.ALUMNO}
            )
        return user


class ActivationCodeForm(forms.Form):
    activation_code = forms.CharField(
        max_length=40,
        label="Codigo de activacion",
        widget=forms.TextInput(
            attrs={"placeholder": "Ingresa tu codigo del curso"}
        ),
    )

    def clean_activation_code(self):
        code = (self.cleaned_data.get("activation_code") or "").strip()
        try:
            activation = ActivationCode.objects.get(code=code)
        except ActivationCode.DoesNotExist as exc:
            raise forms.ValidationError("El codigo de activacion no existe.") from exc
        if not activation.is_enabled:
            raise forms.ValidationError("Este codigo de activacion no esta habilitado.")
        if activation.used_by_id is not None:
            raise forms.ValidationError("Este codigo de activacion ya fue utilizado.")
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
