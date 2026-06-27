from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import FichaAlumno, FichaMovimiento
from odo.models import FuelEntry, MaintenanceRecord, Vehicle

from .models import ConceptoGasto, GastoMensual
from .views import automatic_expense_rows, product_rows_for_year


class BalanceCalculationsTests(TestCase):
    def test_product_rows_group_fichas_by_income_type(self):
        FichaAlumno.objects.create(
            fecha_inscripcion="2026-01-10",
            nombre="Alumno base",
            curso="Curso base mecanico",
            valor_pagado=180000,
        )
        FichaAlumno.objects.create(
            fecha_inscripcion="2026-01-12",
            nombre="Clase extra",
            curso="Clase extra",
            valor_pagado=25000,
        )
        FichaAlumno.objects.create(
            fecha_inscripcion="2026-02-05",
            nombre="Ensayo",
            curso="Ensayo sicotecnico",
            valor_pagado=30000,
        )
        FichaAlumno.objects.create(
            fecha_inscripcion="2026-02-08",
            nombre="Simulador",
            curso="Simulador",
            valor_pagado=15000,
        )
        FichaAlumno.objects.create(
            fecha_inscripcion="2026-02-10",
            nombre="Libro",
            curso="Libro del conductor",
            valor_pagado=12000,
        )

        rows = {row["nombre"]: row for row in product_rows_for_year(2026)}

        self.assertEqual(rows["Alumnos matriculados"]["cantidad_total"], 1)
        self.assertEqual(rows["Alumnos matriculados"]["ingreso_total"], Decimal("180000"))
        self.assertEqual(rows["Clases extras"]["cantidad_total"], 1)
        self.assertEqual(rows["Ensayos sicotecnicos"]["cantidad_total"], 1)
        self.assertEqual(rows["Simulador"]["cantidad_total"], 1)
        self.assertEqual(rows["Simulador"]["ingreso_total"], Decimal("15000"))
        self.assertEqual(rows["Libro"]["cantidad_total"], 1)
        self.assertEqual(rows["Libro"]["ingreso_total"], Decimal("12000"))

    def test_product_rows_group_movements_in_same_ficha(self):
        ficha = FichaAlumno.objects.create(
            fecha_inscripcion="2026-01-10",
            nombre="Alumno base con extra",
            curso="Curso base mecanico",
            valor_pagado=180000,
        )
        FichaMovimiento.sync_pago_inicial(ficha)
        FichaMovimiento.objects.create(
            ficha=ficha,
            fecha="2026-01-20",
            tipo=FichaMovimiento.Tipo.CLASE_EXTRA,
            concepto="Clase extra",
            monto=25000,
        )

        rows = {row["nombre"]: row for row in product_rows_for_year(2026)}

        self.assertEqual(rows["Alumnos matriculados"]["cantidad_total"], 1)
        self.assertEqual(rows["Alumnos matriculados"]["ingreso_total"], Decimal("180000"))
        self.assertEqual(rows["Clases extras"]["cantidad_total"], 1)
        self.assertEqual(rows["Clases extras"]["ingreso_total"], Decimal("25000"))

    def test_automatic_expenses_use_odo_records(self):
        user = get_user_model().objects.create_user(
            username="staff@example.cl",
            email="staff@example.cl",
            password="testpass123",
        )
        vehicle = Vehicle.objects.create(owner=user, plate="ABCD12")
        FuelEntry.objects.create(
            vehicle=vehicle,
            date="2026-03-01",
            odometer=1000,
            liters=Decimal("20"),
            price_per_liter=Decimal("1200"),
            total_cost=Decimal("24000"),
        )
        MaintenanceRecord.objects.create(
            vehicle=vehicle,
            date="2026-03-02",
            odometer=1010,
            name="Cambio aceite",
            cost=Decimal("50000"),
        )

        rows = {row["nombre"]: row for row in automatic_expense_rows(2026)}

        self.assertEqual(rows["Bencina"]["meses"][2]["monto"], Decimal("24000"))
        self.assertEqual(rows["Repuestos"]["meses"][2]["monto"], Decimal("50000"))


class BalanceDashboardTests(TestCase):
    def test_staff_can_open_dashboard(self):
        user = get_user_model().objects.create_user(
            username="owner@example.cl",
            email="owner@example.cl",
            password="testpass123",
            is_staff=True,
        )
        client = Client()
        client.force_login(user)

        response = client.get(reverse("balance:dashboard"), {"anio": "2026"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Balance mensual")

    def test_staff_can_save_manual_expense(self):
        user = get_user_model().objects.create_user(
            username="admin@example.cl",
            email="admin@example.cl",
            password="testpass123",
            is_staff=True,
        )
        concepto = ConceptoGasto.objects.create(nombre="Arriendo test", orden=1)
        client = Client()
        client.force_login(user)

        response = client.post(
            f"{reverse('balance:dashboard')}?anio=2026",
            {f"gasto_{concepto.id}_1": "500.000"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GastoMensual.objects.filter(
                concepto=concepto,
                anio=2026,
                mes=1,
                monto=Decimal("500000"),
            ).exists()
        )

    def test_staff_can_add_and_rename_varios_concept(self):
        user = get_user_model().objects.create_user(
            username="balance@example.cl",
            email="balance@example.cl",
            password="testpass123",
            is_staff=True,
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            f"{reverse('balance:dashboard')}?anio=2026",
            {"action": "add_varios", "varios_detalle": "Patente comercial"},
        )

        self.assertEqual(response.status_code, 302)
        concepto = ConceptoGasto.objects.get(nombre__icontains="Patente comercial")

        response = client.post(
            f"{reverse('balance:dashboard')}?anio=2026",
            {
                "action": "save_gastos",
                f"concepto_nombre_{concepto.id}": "Varios 1 - Patente municipal",
                f"gasto_{concepto.id}_4": "120.000",
            },
        )

        self.assertEqual(response.status_code, 302)
        concepto.refresh_from_db()
        self.assertEqual(concepto.nombre, "Varios 1 - Patente municipal")
        self.assertTrue(
            GastoMensual.objects.filter(
                concepto=concepto,
                anio=2026,
                mes=4,
                monto=Decimal("120000"),
            ).exists()
        )

    def test_staff_can_rename_and_hide_fixed_manual_concept(self):
        user = get_user_model().objects.create_user(
            username="fixed@example.cl",
            email="fixed@example.cl",
            password="testpass123",
            is_staff=True,
        )
        concepto = ConceptoGasto.objects.create(nombre="Internet test", orden=2)
        GastoMensual.objects.create(
            concepto=concepto,
            anio=2026,
            mes=1,
            monto=Decimal("45000"),
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            f"{reverse('balance:dashboard')}?anio=2026",
            {
                "action": "save_gastos",
                f"concepto_nombre_{concepto.id}": "Internet oficina",
                f"gasto_{concepto.id}_1": "45.000",
            },
        )

        self.assertEqual(response.status_code, 302)
        concepto.refresh_from_db()
        self.assertEqual(concepto.nombre, "Internet oficina")

        response = client.post(
            f"{reverse('balance:dashboard')}?anio=2026",
            {
                "action": "save_gastos",
                f"delete_concepto_{concepto.id}": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        concepto.refresh_from_db()
        self.assertFalse(concepto.activo)
        self.assertTrue(GastoMensual.objects.filter(concepto=concepto).exists())
