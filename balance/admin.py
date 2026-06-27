from django.contrib import admin

from .models import ConceptoGasto, GastoMensual


@admin.register(ConceptoGasto)
class ConceptoGastoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "origen", "orden", "activo")
    list_filter = ("origen", "activo")
    search_fields = ("nombre",)


@admin.register(GastoMensual)
class GastoMensualAdmin(admin.ModelAdmin):
    list_display = ("concepto", "mes", "anio", "monto", "updated_by", "updated_at")
    list_filter = ("anio", "mes", "concepto")
    search_fields = ("concepto__nombre", "observacion")
