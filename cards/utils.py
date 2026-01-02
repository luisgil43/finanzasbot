# cards/utils.py
from calendar import monthrange
from datetime import date, timedelta


def _add_month_clamped(d: date) -> date:
    y, m = d.year, d.month
    if m == 12:
        y += 1
        m = 1
    else:
        m += 1
    last_day = monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))

def current_cycle_range(billing_day: int, ref: date) -> tuple[date, date]:
    """
    billing_day = día del mes en que INICIA el ciclo (corte).
    Ciclo: [cycle_start, cycle_end] (end inclusive).
    """
    if ref.day >= billing_day:
        start = date(ref.year, ref.month, billing_day)
    else:
        # mes anterior
        y, m = ref.year, ref.month
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1
        last_day = monthrange(y, m)[1]
        start = date(y, m, min(billing_day, last_day))

    next_start = _add_month_clamped(start)
    end = next_start - timedelta(days=1)
    return start, end