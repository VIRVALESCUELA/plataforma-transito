from datetime import date
from decimal import Decimal

from django.core import mail
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    MaintenanceAlertSeverity,
    MaintenanceRecord,
    MaintenanceSchedule,
    MaintenanceScheduleStatus,
    OdometerReadingSource,
    Vehicle,
    VehicleAccess,
    VehicleDocument,
)
from .serializers import FuelEntrySerializer
from .services import record_odometer


class OdoModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="odo-user",
            email="odo@example.com",
            password="testpass123",
        )

    def test_vehicle_plate_is_globally_unique(self):
        other_user = get_user_model().objects.create_user(
            username="odo-user-2",
            email="odo2@example.com",
            password="testpass123",
        )
        Vehicle.objects.create(owner=self.user, plate="ab-cd-12")

        with self.assertRaises(IntegrityError):
            Vehicle.objects.create(owner=other_user, plate="AB-CD-12")


class OdoAlertTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alert-user",
            email="alert@example.com",
            password="testpass123",
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="ODO123",
            current_odometer=9000,
        )

    def test_creates_warning_when_crossing_odometer_threshold(self):
        schedule = MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Cambio de aceite",
            due_odometer=10000,
        )

        record_odometer(
            self.vehicle,
            odometer=9600,
            source=OdometerReadingSource.MANUAL,
        )

        alert = schedule.alerts.get(threshold_value=500)
        self.assertEqual(alert.severity, MaintenanceAlertSeverity.WARNING)
        self.assertEqual(alert.message, "Cambio de aceite vence en 500 km.")

    def test_marks_schedule_overdue_when_odometer_is_exceeded(self):
        schedule = MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Frenos",
            due_odometer=9500,
        )

        record_odometer(
            self.vehicle,
            odometer=9601,
            source=OdometerReadingSource.MANUAL,
        )

        schedule.refresh_from_db()
        alert = schedule.alerts.get(threshold_value=-1)
        self.assertEqual(schedule.status, MaintenanceScheduleStatus.OVERDUE)
        self.assertEqual(alert.severity, MaintenanceAlertSeverity.CRITICAL)
        self.assertEqual(
            alert.message,
            "Aviso de vencimiento: Frenos superado por 101 km.",
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ODO_ALERT_NOTIFICATION_EMAIL="virvalescuela@gmail.com",
    )
    def test_sends_email_when_fuel_odometer_reaches_scheduled_alert(self):
        MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Aceite motor",
            due_odometer=9500,
        )

        with self.captureOnCommitCallbacks(execute=True):
            record_odometer(
                self.vehicle,
                odometer=9500,
                source=OdometerReadingSource.FUEL,
            )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["virvalescuela@gmail.com"])
        self.assertIn("ODO alerta ODO123: Aceite motor", mail.outbox[0].subject)
        self.assertIn("Aviso de vencimiento", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ODO_ALERT_NOTIFICATION_EMAIL="virvalescuela@gmail.com",
    )
    def test_sends_email_when_fuel_date_reaches_scheduled_alert(self):
        MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Revision tecnica",
            due_date=date(2026, 6, 12),
            notes="Llevar certificado anterior.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            record_odometer(
                self.vehicle,
                odometer=9100,
                source=OdometerReadingSource.FUEL,
                date=date(2026, 6, 12),
            )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Revision tecnica", mail.outbox[0].subject)
        self.assertIn("vence hoy", mail.outbox[0].body)
        self.assertIn("Llevar certificado anterior.", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ODO_ALERT_NOTIFICATION_EMAIL="virvalescuela@gmail.com",
    )
    def test_sends_email_for_selected_odometer_warning_thresholds_with_note(self):
        MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Bateria",
            due_odometer=10000,
            notes="Arranque lento en frio.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            record_odometer(
                self.vehicle,
                odometer=9700,
                source=OdometerReadingSource.MANUAL,
            )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Bateria vence en 300 km.", mail.outbox[0].body)
        self.assertIn("Arranque lento en frio.", mail.outbox[0].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ODO_ALERT_NOTIFICATION_EMAIL="virvalescuela@gmail.com",
    )
    def test_skips_email_for_non_selected_odometer_warning_thresholds(self):
        MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Aceite motor",
            due_odometer=10000,
        )

        with self.captureOnCommitCallbacks(execute=True):
            record_odometer(
                self.vehicle,
                odometer=9500,
                source=OdometerReadingSource.MANUAL,
            )

        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ODO_ALERT_NOTIFICATION_EMAIL="virvalescuela@gmail.com",
    )
    def test_sends_email_for_selected_date_warning_thresholds_with_note(self):
        MaintenanceSchedule.objects.create(
            vehicle=self.vehicle,
            name="Revision tecnica",
            due_date=date(2026, 6, 17),
            notes="Pedir hora en planta.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            record_odometer(
                self.vehicle,
                odometer=9100,
                source=OdometerReadingSource.MANUAL,
                date=date(2026, 6, 12),
            )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Revision tecnica vence en 5 dias.", mail.outbox[0].body)
        self.assertIn("Pedir hora en planta.", mail.outbox[0].body)


class OdoFuelEntrySerializerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="odo-api-user",
            email="odo-api@example.com",
            password="testpass123",
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="API123",
            current_odometer=1000,
        )

    def test_api_calculates_price_per_liter_from_total_and_liters(self):
        serializer = FuelEntrySerializer(
            data={
                "date": "2026-06-10",
                "odometer": 1200,
                "liters": "20.00",
                "price_per_liter": "1.00",
                "total_cost": "30000.00",
                "notes": "",
            },
            context={"vehicle": self.vehicle},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        entry = serializer.save(vehicle=self.vehicle)

        self.assertEqual(entry.price_per_liter, Decimal("1500.00"))

    def test_api_rejects_odometer_below_vehicle_current_odometer(self):
        serializer = FuelEntrySerializer(
            data={
                "date": "2026-06-10",
                "odometer": 999,
                "liters": "20.00",
                "total_cost": "30000.00",
                "notes": "",
            },
            context={"vehicle": self.vehicle},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("odometer", serializer.errors)


class OdoDashboardWebTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="odo-web-user",
            email="odo-web@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_superuser_can_create_vehicle_from_dashboard(self):
        superuser = get_user_model().objects.create_superuser(
            username="odo-superuser",
            email="odo-super@example.com",
            password="testpass123",
        )
        self.client.force_login(superuser)

        response = self.client.post(
            reverse("odo_web:vehicles"),
            {
                "action": "create_vehicle",
                "plate": "ab-cd-12",
                "alias": "1GCEG16Z0E123456",
                "brand": "Toyota",
                "model": "Yaris",
                "year": 2020,
                "current_odometer": 1000,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        vehicle = Vehicle.objects.get(owner=superuser)
        self.assertEqual(vehicle.plate, "ABCD12")
        self.assertContains(response, "ABCD12")

    def test_staff_cannot_create_vehicle_from_dashboard(self):
        response = self.client.post(
            reverse("odo_web:vehicles"),
            {
                "action": "create_vehicle",
                "plate": "ZZYY99",
                "alias": "1GCEG16Z0E123456",
                "brand": "Toyota",
                "model": "Yaris",
                "year": 2020,
                "current_odometer": 1000,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vehicle.objects.filter(plate="ZZYY99").exists())

    def test_superuser_can_assign_vehicle_access_to_staff(self):
        user_model = get_user_model()
        superuser = user_model.objects.create_superuser(
            username="odo-access-superuser",
            email="odo-access-super@example.com",
            password="testpass123",
        )
        staff = user_model.objects.create_user(
            username="odo-assigned-staff",
            email="assigned@example.com",
            password="testpass123",
            is_staff=True,
        )
        vehicle = Vehicle.objects.create(
            owner=superuser,
            plate="ASIG12",
            current_odometer=1000,
        )
        self.client.force_login(superuser)

        response = self.client.post(
            reverse("odo_web:access"),
            {
                "user": staff.id,
                "vehicle": vehicle.id,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(VehicleAccess.objects.filter(user=staff, vehicle=vehicle).exists())
        self.assertContains(response, "ASIG12")

        self.client.force_login(staff)
        response = self.client.get(reverse("odo_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ASIG12")

    def test_staff_cannot_open_vehicle_access_page(self):
        response = self.client.get(reverse("odo_web:access"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("odo_web:dashboard"))

    def test_user_can_create_fuel_entry_from_dashboard(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="ODO123",
            current_odometer=1000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)

        response = self.client.post(
            reverse("odo_web:dashboard"),
            {
                "action": "create_fuel",
                "vehicle": vehicle.id,
                "date": "2026-06-10",
                "odometer": 1250,
                "liters": "30.00",
                "total_cost": "30000.00",
                "notes": "Prueba",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.current_odometer, 1250)
        entry = vehicle.fuel_entries.get()
        self.assertEqual(entry.price_per_liter, 1000)
        self.assertContains(response, "30,00 L")

    def test_user_can_create_maintenance_schedule_from_alerts(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="ODO456",
            current_odometer=9000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)

        response = self.client.post(
            reverse("odo_web:alerts"),
            {
                "action": "create_schedule",
                "vehicle": vehicle.id,
                "name": "Aceite motor",
                "due_odometer": 9500,
                "due_date": "",
                "notes": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        schedule = vehicle.maintenance_schedules.get()
        self.assertEqual(schedule.name, "Aceite motor")
        self.assertContains(response, "Aceite motor")

    def test_user_can_create_custom_maintenance_schedule_from_alerts(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="CSTM12",
            current_odometer=9000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)

        response = self.client.post(
            reverse("odo_web:alerts"),
            {
                "action": "create_schedule",
                "vehicle": vehicle.id,
                "name": [],
                "custom_name": "Bateria",
                "due_odometer": 9300,
                "due_date": "",
                "notes": "Revisar porque cuesta arrancar.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        schedule = vehicle.maintenance_schedules.get()
        self.assertEqual(schedule.name, "Bateria")
        self.assertEqual(schedule.notes, "Revisar porque cuesta arrancar.")
        self.assertContains(response, "Bateria")

    def test_user_can_create_multiple_maintenance_schedules_from_alerts(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="ODO789",
            current_odometer=9000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)

        response = self.client.post(
            reverse("odo_web:alerts"),
            {
                "action": "create_schedule",
                "vehicle": vehicle.id,
                "name": [
                    "Aceite motor",
                    "Revision tecnica",
                    "Permiso circulacion",
                ],
                "due_odometer": 9500,
                "due_date": "2026-07-10",
                "notes": "Alertas principales",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(vehicle.maintenance_schedules.count(), 3)
        self.assertQuerySetEqual(
            vehicle.maintenance_schedules.order_by("name").values_list(
                "name",
                flat=True,
            ),
            [
                "Aceite motor",
                "Permiso circulacion",
                "Revision tecnica",
            ],
        )
        self.assertContains(response, "3 alerta(s)")

    def test_dashboard_shows_vehicle_oil_and_inspection_status(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="ODO321",
            current_odometer=9000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)
        MaintenanceSchedule.objects.create(
            vehicle=vehicle,
            name="Aceite motor",
            due_odometer=10000,
        )
        MaintenanceSchedule.objects.create(
            vehicle=vehicle,
            name="Revision tecnica",
            due_date=date(2026, 7, 10),
        )

        response = self.client.get(reverse("odo_web:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aceite")
        self.assertContains(response, "10000 km")
        self.assertContains(response, "Revision tecnica")
        self.assertContains(response, "10/07/2026")

    def test_user_can_create_multiple_maintenance_records_from_maintenance(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="ODO654",
            current_odometer=9000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)

        response = self.client.post(
            reverse("odo_web:maintenance"),
            {
                "action": "create_record",
                "vehicle": vehicle.id,
                "services": [
                    "Aceite motor",
                    "Filtro de aceite",
                    "Bujias",
                ],
                "date": "2026-06-12",
                "odometer": 9800,
                "cost": "85000.00",
                "notes": "Mantencion de taller",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(MaintenanceRecord.objects.filter(vehicle=vehicle).count(), 3)
        self.assertEqual(vehicle.odometer_readings.count(), 1)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.current_odometer, 9800)
        self.assertContains(response, "Aceite motor")
        self.assertContains(response, "3 mantencion(es) registrada(s)")

    def test_user_can_upload_vehicle_document(self):
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="DOCU12",
            current_odometer=9000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)
        uploaded_file = SimpleUploadedFile(
            "revision.pdf",
            b"documento de prueba",
            content_type="application/pdf",
        )

        response = self.client.post(
            reverse("odo_web:documents"),
            {
                "vehicle": vehicle.id,
                "document_type": "TECHNICAL_INSPECTION",
                "file": uploaded_file,
                "issued_at": "2026-06-01",
                "expires_at": "2027-06-01",
                "notes": "Revision cargada",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        document = VehicleDocument.objects.get(vehicle=vehicle)
        self.assertEqual(document.document_type, "TECHNICAL_INSPECTION")
        self.assertEqual(document.uploaded_by, self.user)
        self.assertContains(response, "Revision tecnica")

    def test_non_staff_cannot_access_odo(self):
        user_model = get_user_model()
        normal_user = user_model.objects.create_user(
            username="odo-normal-user",
            email="normal@example.com",
            password="testpass123",
        )
        self.client.force_login(normal_user)

        response = self.client.get(reverse("odo_web:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_staff_can_share_vehicle_by_plate_access(self):
        user_model = get_user_model()
        other_staff = user_model.objects.create_user(
            username="other-odo-staff",
            email="other-staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="SHAR12",
            current_odometer=1000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=other_staff)
        self.client.force_login(other_staff)

        response = self.client.post(
            reverse("odo_web:dashboard"),
            {
                "action": "create_fuel",
                "vehicle": vehicle.id,
                "date": "2026-06-10",
                "odometer": 1300,
                "liters": "20.00",
                "total_cost": "20000.00",
                "notes": "Turno compartido",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.current_odometer, 1300)
        self.assertEqual(vehicle.fuel_entries.get().created_by, other_staff)

    def test_staff_cannot_use_unassigned_vehicle(self):
        user_model = get_user_model()
        other_staff = user_model.objects.create_user(
            username="unassigned-odo-staff",
            email="unassigned-staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        vehicle = Vehicle.objects.create(
            owner=self.user,
            plate="PRIV12",
            current_odometer=1000,
        )
        VehicleAccess.objects.create(vehicle=vehicle, user=self.user)
        self.client.force_login(other_staff)

        response = self.client.post(
            reverse("odo_web:dashboard"),
            {
                "action": "create_fuel",
                "vehicle": vehicle.id,
                "date": "2026-06-10",
                "odometer": 1300,
                "liters": "20.00",
                "total_cost": "20000.00",
                "notes": "Sin acceso",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(vehicle.fuel_entries.count(), 0)
