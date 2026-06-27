from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractMonth
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import TemplateView

from core.models import FichaAlumno, FichaMovimiento
from odo.models import FuelEntry, MaintenanceRecord

from .models import ConceptoGasto, GastoMensual


MONTHS = [
    (1, "Enero"),
    (2, "Febrero"),
    (3, "Marzo"),
    (4, "Abril"),
    (5, "Mayo"),
    (6, "Junio"),
    (7, "Julio"),
    (8, "Agosto"),
    (9, "Septiembre"),
    (10, "Octubre"),
    (11, "Noviembre"),
    (12, "Diciembre"),
]


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return bool(self.request.user and self.request.user.is_staff)

    def handle_no_permission(self):
        messages.error(self.request, "No tienes permisos para acceder a esta seccion.")
        return redirect("core_web:dashboard")


def parse_money(value):
    cleaned = "".join(char for char in (value or "") if char.isdigit())
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def money_by_month(queryset, date_field, amount_field):
    rows = (
        queryset.annotate(month=ExtractMonth(date_field))
        .values("month")
        .annotate(total=Sum(amount_field))
    )
    values = {month: Decimal("0") for month, _ in MONTHS}
    for row in rows:
        if row["month"]:
            values[row["month"]] = row["total"] or Decimal("0")
    return values


def count_and_money_by_month(queryset, date_field="fecha_inscripcion", amount_field="valor_pagado"):
    rows = (
        queryset.annotate(month=ExtractMonth(date_field))
        .values("month")
        .annotate(cantidad=Count("id"), total=Sum(amount_field))
    )
    values = {
        month: {"cantidad": 0, "total": Decimal("0")}
        for month, _ in MONTHS
    }
    for row in rows:
        if row["month"]:
            values[row["month"]] = {
                "cantidad": row["cantidad"] or 0,
                "total": row["total"] or Decimal("0"),
            }
    return values


def product_rows_for_year(year):
    movimientos = FichaMovimiento.objects.filter(fecha__year=year)
    fichas_sin_movimientos = FichaAlumno.objects.filter(
        fecha_inscripcion__year=year,
        movimientos__isnull=True,
    )
    clases_extra_filter = Q(curso__icontains="extra")
    ensayos_filter = (
        Q(curso__icontains="sico")
        | Q(curso__icontains="psico")
        | Q(curso__icontains="ensayo")
    )
    simulador_filter = Q(curso__icontains="simulador")
    libro_filter = Q(curso__icontains="libro")
    standalone_products_filter = (
        clases_extra_filter | ensayos_filter | simulador_filter | libro_filter
    )

    legacy_product_specs = [
        (
            "Alumnos matriculados",
            fichas_sin_movimientos.exclude(standalone_products_filter),
        ),
        ("Clases extras", fichas_sin_movimientos.filter(clases_extra_filter)),
        ("Ensayos sicotecnicos", fichas_sin_movimientos.filter(ensayos_filter)),
        ("Simulador", fichas_sin_movimientos.filter(simulador_filter)),
        ("Libro", fichas_sin_movimientos.filter(libro_filter)),
        ("Abonos", fichas_sin_movimientos.none()),
    ]
    movement_product_specs = [
        (
            "Alumnos matriculados",
            movimientos.filter(tipo=FichaMovimiento.Tipo.CURSO),
        ),
        ("Clases extras", movimientos.filter(tipo=FichaMovimiento.Tipo.CLASE_EXTRA)),
        ("Ensayos sicotecnicos", movimientos.filter(tipo=FichaMovimiento.Tipo.ENSAYO_SICOTECNICO)),
        ("Simulador", movimientos.filter(tipo=FichaMovimiento.Tipo.SIMULADOR)),
        ("Libro", movimientos.filter(tipo=FichaMovimiento.Tipo.LIBRO)),
        ("Abonos", movimientos.filter(tipo=FichaMovimiento.Tipo.ABONO)),
    ]
    rows = []
    for (name, legacy_queryset), (_, movement_queryset) in zip(
        legacy_product_specs,
        movement_product_specs,
    ):
        month_values = count_and_money_by_month(legacy_queryset)
        movement_values = count_and_money_by_month(movement_queryset, "fecha", "monto")
        for month, value in movement_values.items():
            month_values[month]["cantidad"] += value["cantidad"]
            month_values[month]["total"] += value["total"]
        total_count = sum(item["cantidad"] for item in month_values.values())
        total_money = sum((item["total"] for item in month_values.values()), Decimal("0"))
        average_price = total_money / total_count if total_count else Decimal("0")
        rows.append(
            {
                "nombre": name,
                "meses": month_values,
                "cantidad_total": total_count,
                "ingreso_total": total_money,
                "precio_promedio": average_price,
            }
        )
    return rows


def manual_expense_rows(year):
    conceptos = ConceptoGasto.objects.filter(
        activo=True,
        origen=ConceptoGasto.Origen.MANUAL,
    )
    gastos = GastoMensual.objects.filter(anio=year, concepto__in=conceptos)
    by_key = {(gasto.concepto_id, gasto.mes): gasto for gasto in gastos}
    rows = []
    for concepto in conceptos:
        months = []
        total = Decimal("0")
        for month, _ in MONTHS:
            gasto = by_key.get((concepto.id, month))
            amount = gasto.monto if gasto else Decimal("0")
            total += amount
            months.append({"numero": month, "monto": amount})
        rows.append(
            {
                "concepto": concepto,
                "meses": months,
                "total": total,
                "can_rename": True,
                "can_delete": True,
            }
        )
    return rows


def automatic_expense_rows(year):
    fuel = money_by_month(
        FuelEntry.objects.filter(date__year=year),
        "date",
        "total_cost",
    )
    maintenance = money_by_month(
        MaintenanceRecord.objects.filter(date__year=year),
        "date",
        "cost",
    )
    rows = []
    for name, values in (("Bencina", fuel), ("Repuestos", maintenance)):
        rows.append(
            {
                "nombre": name,
                "meses": [{"numero": month, "monto": values[month]} for month, _ in MONTHS],
                "total": sum(values.values(), Decimal("0")),
            }
        )
    return rows


def create_varios_concept(detail=""):
    existing_count = ConceptoGasto.objects.filter(nombre__istartswith="Varios").count()
    next_number = max(existing_count, 1)
    detail = (detail or "").strip()
    base_name = f"Varios {next_number}"
    name = f"{base_name} - {detail}" if detail else base_name

    while ConceptoGasto.objects.filter(nombre__iexact=name).exists():
        next_number += 1
        base_name = f"Varios {next_number}"
        name = f"{base_name} - {detail}" if detail else base_name

    return ConceptoGasto.objects.create(
        nombre=name,
        origen=ConceptoGasto.Origen.MANUAL,
        orden=90 + next_number,
        activo=True,
    )


class BalanceDashboardView(LoginRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "balance/dashboard.html"
    login_url = reverse_lazy("login")

    def get_year(self):
        current_year = timezone.localdate().year
        try:
            year = int(self.request.GET.get("anio", current_year))
        except (TypeError, ValueError):
            year = current_year
        return max(2013, min(year, current_year + 1))

    def post(self, request, *args, **kwargs):
        year = self.get_year()
        if request.POST.get("action") == "add_varios":
            concepto = create_varios_concept(request.POST.get("varios_detalle"))
            messages.success(request, f"Concepto {concepto.nombre} agregado.")
            return redirect(f"{request.path}?anio={year}#gastos")

        conceptos = ConceptoGasto.objects.filter(
            activo=True,
            origen=ConceptoGasto.Origen.MANUAL,
        )
        for concepto in conceptos:
            if request.POST.get(f"delete_concepto_{concepto.id}") == "1":
                concepto.activo = False
                concepto.save(update_fields=["activo"])
                continue

            name_field = f"concepto_nombre_{concepto.id}"
            if name_field in request.POST:
                new_name = (request.POST.get(name_field) or "").strip()
                if new_name and new_name != concepto.nombre:
                    duplicate = ConceptoGasto.objects.filter(
                        nombre__iexact=new_name,
                    ).exclude(pk=concepto.pk).exists()
                    if duplicate:
                        messages.warning(
                            request,
                            f"No se renombro {concepto.nombre}: ya existe {new_name}.",
                        )
                    else:
                        concepto.nombre = new_name
                        concepto.save(update_fields=["nombre"])
            for month, _ in MONTHS:
                field_name = f"gasto_{concepto.id}_{month}"
                if field_name not in request.POST:
                    continue
                amount = parse_money(request.POST.get(field_name))
                gasto = GastoMensual.objects.filter(
                    concepto=concepto,
                    anio=year,
                    mes=month,
                ).first()
                if amount == 0:
                    if gasto:
                        gasto.delete()
                    continue
                GastoMensual.objects.update_or_create(
                    concepto=concepto,
                    anio=year,
                    mes=month,
                    defaults={"monto": amount, "updated_by": request.user},
                )
        messages.success(request, f"Gastos manuales {year} actualizados.")
        return redirect(f"{request.path}?anio={year}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = self.get_year()
        product_rows = product_rows_for_year(year)
        manual_rows = manual_expense_rows(year)
        automatic_rows = automatic_expense_rows(year)

        income_by_month = {month: Decimal("0") for month, _ in MONTHS}
        product_count_by_month = {month: 0 for month, _ in MONTHS}
        for row in product_rows:
            for month, value in row["meses"].items():
                income_by_month[month] += value["total"]
                product_count_by_month[month] += value["cantidad"]

        expenses_by_month = {month: Decimal("0") for month, _ in MONTHS}
        for row in manual_rows + automatic_rows:
            for item in row["meses"]:
                expenses_by_month[item["numero"]] += item["monto"]

        balance_months = []
        for month, name in MONTHS:
            balance_months.append(
                {
                    "numero": month,
                    "nombre": name,
                    "ingresos": income_by_month[month],
                    "gastos": expenses_by_month[month],
                    "resultado": income_by_month[month] - expenses_by_month[month],
                    "productos": product_count_by_month[month],
                }
            )

        context.update(
            {
                "year": year,
                "year_options": range(timezone.localdate().year + 1, 2012, -1),
                "months": MONTHS,
                "product_rows": product_rows,
                "manual_expense_rows": manual_rows,
                "automatic_expense_rows": automatic_rows,
                "balance_months": balance_months,
                "total_income": sum(income_by_month.values(), Decimal("0")),
                "total_expenses": sum(expenses_by_month.values(), Decimal("0")),
                "total_result": sum(income_by_month.values(), Decimal("0"))
                - sum(expenses_by_month.values(), Decimal("0")),
                "total_products": sum(product_count_by_month.values()),
            }
        )
        return context
