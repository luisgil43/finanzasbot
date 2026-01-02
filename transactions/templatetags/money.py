from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


@register.filter(name="money")
def money(value, currency="CLP") -> str:
    """
    Formato estilo CL:
    - Miles con punto: 320.240
    - Decimales con coma: 1.234,56
    CLP => 0 decimales
    USD => 2 decimales
    """
    cur = (currency or "CLP").upper()
    v = _to_decimal(value)

    decimals = 0 if cur == "CLP" else 2
    q = Decimal("1") if decimals == 0 else Decimal("0.01")
    v = v.quantize(q, rounding=ROUND_HALF_UP)

    # Python: 1,234.56 (miles coma, decimal punto)
    s = f"{v:,.{decimals}f}"

    if cur == "CLP":
        # 320,240 -> 320.240
        return s.replace(",", ".")

    # 1,234.56 -> 1.234,56
    return s.replace(",", "X").replace(".", ",").replace("X", ".")