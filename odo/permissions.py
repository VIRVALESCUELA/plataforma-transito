from .models import Vehicle


def user_can_use_odo(user):
    return bool(user and user.is_authenticated and user.is_staff)


def accessible_vehicles_for(user):
    if not user_can_use_odo(user):
        return Vehicle.objects.none()
    if user.is_superuser:
        return Vehicle.objects.all().order_by("plate")
    return Vehicle.objects.filter(staff_access__user=user).distinct().order_by("plate")


def user_can_access_vehicle(user, vehicle):
    if not user_can_use_odo(user):
        return False
    if user.is_superuser:
        return True
    return vehicle.staff_access.filter(user=user).exists()
