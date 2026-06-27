from decimal import Decimal

from django import template


register = template.Library()


@register.filter
def clp(value):
    try:
        number = int(Decimal(value or 0))
    except (ArithmeticError, ValueError):
        number = 0
    sign = "-" if number < 0 else ""
    formatted = f"{abs(number):,}".replace(",", ".")
    return f"{sign}${formatted}"


@register.filter
def signed_clp(value):
    try:
        number = int(Decimal(value or 0))
    except (ArithmeticError, ValueError):
        number = 0
    sign = "+" if number > 0 else ""
    formatted = f"{abs(number):,}".replace(",", ".")
    if number < 0:
        return f"-${formatted}"
    return f"{sign}${formatted}"
