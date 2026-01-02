from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import requests
from django.core.cache import cache
from django.utils import timezone

CACHE_KEY = "fx:usd_to_clp"
CACHE_TTL_SECONDS = 60 * 60  # 1 hora


@dataclass(frozen=True)
class FxResult:
    rate: Decimal
    source: str
    ts: object  # datetime


def get_usd_to_clp(default_rate: Decimal = Decimal("950")) -> FxResult:
    """
    Retorna tasa USD->CLP desde mindicador.cl con cache.
    Si falla, usa default_rate.
    """
    cached = cache.get(CACHE_KEY)
    if cached:
        try:
            rate = Decimal(str(cached))
            return FxResult(rate=rate, source="cache", ts=timezone.now())
        except Exception:
            pass

    try:
        r = requests.get("https://mindicador.cl/api/dolar", timeout=10)
        r.raise_for_status()
        data = r.json()
        serie = data.get("serie") or []
        if serie:
            val = serie[0].get("valor")
            if val is not None:
                rate = Decimal(str(val))
                cache.set(CACHE_KEY, str(rate), CACHE_TTL_SECONDS)
                return FxResult(rate=rate, source="mindicador", ts=timezone.now())
    except Exception:
        pass

    return FxResult(rate=default_rate, source="default", ts=timezone.now())