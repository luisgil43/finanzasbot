# budgets/notifications.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, List, Optional, Tuple

import requests
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _t

from budgets.models import \
    BudgetAlertState  # creado en tu 0002_budgetalertstate
from budgets.models import BudgetCategory, MonthlyBudget
from transactions.models import Transaction

logger = logging.getLogger(__name__)


# =========================
# Config
# =========================

NEAR_PCT_DEFAULT = 80  # aviso cuando va en >=80% del presupuesto
TIMEOUT_SECONDS = 8


# =========================
# Helpers
# =========================

def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_label(month_start: date) -> str:
    """
    Retorna un label humano (respetando idioma activo).
    Ej: "December 2025" / "diciembre 2025"
    """
    # date_format usa el idioma activo si está activado translation.activate(...)
    return date_format(month_start, "F Y")


def _to_int_clp(n: Decimal | int | float | None) -> int:
    if n is None:
        return 0
    if isinstance(n, Decimal):
        return int(n)
    return int(n)


def _fmt_clp(n: int) -> str:
    # Mantén simple y estable para i18n + Telegram
    # (si quieres, después lo mejoramos con separador de miles por locale)
    return f"{n:,}".replace(",", ".")


def _normalize_text(s: str) -> str:
    return (s or "").strip().casefold()


def _split_keywords(keywords: str) -> List[str]:
    """
    Admite: "uber, comida en la calle, rappi"
    -> ["uber", "comida en la calle", "rappi"]
    """
    if not keywords:
        return []
    parts = [p.strip() for p in keywords.split(",")]
    return [p for p in parts if p]


def _tx_amount_clp(tx: Transaction) -> int:
    """
    Intenta obtener el monto CLP del Transaction.
    Ajusté esto para que funcione aunque tu modelo tenga nombres distintos.
    """
    # nombres típicos
    for attr in ("amount_clp", "clp_amount", "amount_base_clp", "amount"):
        if hasattr(tx, attr):
            try:
                v = getattr(tx, attr)
                # si viene Decimal/float/int
                return _to_int_clp(v)
            except Exception:
                pass

    # fallback: si hay un método/prop
    if hasattr(tx, "get_amount_clp"):
        try:
            return _to_int_clp(tx.get_amount_clp())
        except Exception:
            pass

    return 0


def _tx_is_expense(tx: Transaction) -> bool:
    """
    Determina si el transaction es gasto.
    Ajusta si tu modelo usa 'direction' o 'tx_type'.
    """
    # casos típicos:
    # tx.type == "expense"/"income"
    # tx.direction == "out"/"in"
    # tx.is_income bool, etc.
    for attr in ("type", "tx_type", "kind", "direction"):
        if hasattr(tx, attr):
            v = getattr(tx, attr)
            if isinstance(v, str):
                vv = v.lower()
                if vv in ("expense", "gasto", "out", "debit"):
                    return True
                if vv in ("income", "ingreso", "in", "credit"):
                    return False

    # si existe un boolean típico
    if hasattr(tx, "is_income"):
        try:
            return not bool(tx.is_income)
        except Exception:
            pass

    # default: asume gasto si no sabemos
    return True


def _tx_description(tx: Transaction) -> str:
    for attr in ("description", "desc", "detalle", "text"):
        if hasattr(tx, attr):
            try:
                return str(getattr(tx, attr) or "")
            except Exception:
                pass
    return ""


def _get_user_language(tx: Transaction) -> Optional[str]:
    """
    Lee idioma preferido del usuario si existe.
    """
    user = getattr(tx, "user", None)
    if not user:
        return None

    # patrones típicos
    # user.profile.language, user.userprofile.language, etc.
    for path in (
        ("profile", "language"),
        ("userprofile", "language"),
        ("perfil", "idioma"),
        ("settings", "language"),
    ):
        obj = user
        ok = True
        for p in path:
            if hasattr(obj, p):
                obj = getattr(obj, p)
            else:
                ok = False
                break
        if ok and isinstance(obj, str) and obj:
            return obj

    # si el user tiene campo directo
    if hasattr(user, "language"):
        v = getattr(user, "language")
        if isinstance(v, str) and v:
            return v

    return None


def _get_user_telegram_chat_id(tx: Transaction) -> Optional[str]:
    """
    Obtiene el telegram_chat_id del usuario (si está vinculado).
    """
    user = getattr(tx, "user", None)
    if not user:
        return None

    # patrones típicos en tu proyecto: UserProfile.telegram_chat_id
    for path in (
        ("profile", "telegram_chat_id"),
        ("userprofile", "telegram_chat_id"),
        ("perfil", "telegram_chat_id"),
    ):
        obj = user
        ok = True
        for p in path:
            if hasattr(obj, p):
                obj = getattr(obj, p)
            else:
                ok = False
                break
        if ok and obj:
            return str(obj)

    # si el user tiene campo directo
    if hasattr(user, "telegram_chat_id"):
        v = getattr(user, "telegram_chat_id")
        if v:
            return str(v)

    return None


def _get_bot_token() -> Optional[str]:
    return (
        getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        or getattr(settings, "TELEGRAM_BOT_TOKEN_GZ", None)
    )


def _send_telegram(chat_id: str, text: str) -> bool:
    """
    Envía mensaje y retorna True/False sin lanzar excepción.
    """
    token = _get_bot_token()
    if not token:
        logger.warning("Telegram token no configurado (TELEGRAM_BOT_TOKEN).")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, data=payload, timeout=TIMEOUT_SECONDS)
        if r.status_code != 200:
            logger.warning("Telegram sendMessage fallo %s: %s", r.status_code, r.text[:500])
            return False
        return True
    except Exception as e:
        logger.exception("Telegram sendMessage excepción: %s", e)
        return False


def _safe_set_fields(obj, **fields) -> None:
    """
    Setea fields solo si existen en el modelo (para compatibilidad).
    """
    for k, v in fields.items():
        if hasattr(obj, k):
            try:
                setattr(obj, k, v)
            except Exception:
                pass


# =========================
# Core computation
# =========================

@dataclass(frozen=True)
class BudgetCheckResult:
    category: BudgetCategory
    month: date
    budget_clp: int
    spent_clp: int
    remaining_clp: int
    pct: int
    status: str  # "ok" | "near" | "over"


def _categories_for_user(user) -> QuerySet[BudgetCategory]:
    qs = BudgetCategory.objects.all()
    # Si tu BudgetCategory está asociada a user/owner, filtramos.
    # Si no existe ese campo, lo dejamos global.
    if hasattr(BudgetCategory, "user_id"):
        qs = qs.filter(user=user)
    elif hasattr(BudgetCategory, "owner_id"):
        qs = qs.filter(owner=user)
    return qs


def _budgets_for_user_month(user, month_start: date) -> QuerySet[MonthlyBudget]:
    qs = MonthlyBudget.objects.all()
    # filtros por user
    if hasattr(MonthlyBudget, "user_id"):
        qs = qs.filter(user=user)
    elif hasattr(MonthlyBudget, "owner_id"):
        qs = qs.filter(owner=user)

    # filtro por mes (puede ser DateField month o Char YYYY-MM)
    if hasattr(MonthlyBudget, "month"):
        qs = qs.filter(month=month_start)
    elif hasattr(MonthlyBudget, "month_start"):
        qs = qs.filter(month_start=month_start)
    elif hasattr(MonthlyBudget, "month_value"):
        # "YYYY-MM"
        qs = qs.filter(month_value=month_start.strftime("%Y-%m"))

    return qs


def _budget_amount_clp(b: MonthlyBudget) -> int:
    for attr in ("amount_clp", "amount", "budget_amount", "value_clp"):
        if hasattr(b, attr):
            try:
                return _to_int_clp(getattr(b, attr))
            except Exception:
                pass
    return 0


def _budget_category(b: MonthlyBudget) -> Optional[BudgetCategory]:
    for attr in ("category", "budget_category"):
        if hasattr(b, attr):
            try:
                return getattr(b, attr)
            except Exception:
                pass
    return None


def _estimate_spent_for_category(user, month_start: date, category: BudgetCategory) -> int:
    """
    Estima el gasto del mes para una categoría por match de keywords.
    """
    keywords = _split_keywords(getattr(category, "match_keywords", "") or "")
    if not keywords:
        return 0

    # transactions del mes
    tx_qs = Transaction.objects.filter(user=user)
    # filtra por fecha (si el modelo tiene created_at / occurred_at / dt)
    start = month_start
    end = (month_start.replace(day=28) + timezone.timedelta(days=4)).replace(day=1)  # next month start

    # buscamos un campo de fecha existente
    date_field = None
    for f in ("occurred_at", "date", "created_at", "timestamp", "dt"):
        if hasattr(Transaction, f):
            date_field = f
            break

    if date_field:
        tx_qs = tx_qs.filter(**{f"{date_field}__date__gte": start, f"{date_field}__date__lt": end})

    total = 0
    for tx in tx_qs.iterator():
        if not _tx_is_expense(tx):
            continue
        desc = _normalize_text(_tx_description(tx))
        if not desc:
            continue
        if any(k.casefold() in desc for k in keywords):
            total += _tx_amount_clp(tx)

    return total


def _check_budget_for_tx(tx: Transaction) -> List[BudgetCheckResult]:
    """
    Para el tx entrante, revisa solo categorías donde hace match por keywords.
    """
    user = getattr(tx, "user", None)
    if not user:
        return []

    if not _tx_is_expense(tx):
        return []

    month = _month_start(timezone.localdate())
    desc = _normalize_text(_tx_description(tx))

    results: List[BudgetCheckResult] = []
    if not desc:
        return results

    # categorías del usuario (o globales)
    categories = _categories_for_user(user)

    # presupuestos del mes
    budgets_qs = _budgets_for_user_month(user, month)
    budgets_by_cat_id = {}
    for b in budgets_qs:
        cat = _budget_category(b)
        if cat:
            budgets_by_cat_id[getattr(cat, "id")] = b

    for cat in categories:
        keywords = _split_keywords(getattr(cat, "match_keywords", "") or "")
        if not keywords:
            continue

        if not any(k.casefold() in desc for k in keywords):
            continue

        b = budgets_by_cat_id.get(getattr(cat, "id"))
        if not b:
            # no hay presupuesto para esa categoría ese mes
            continue

        budget_clp = _budget_amount_clp(b)
        if budget_clp <= 0:
            continue

        spent = _estimate_spent_for_category(user, month, cat)
        remaining = budget_clp - spent
        pct = int((spent / budget_clp) * 100) if budget_clp > 0 else 0

        status = "ok"
        if spent > budget_clp:
            status = "over"
        elif pct >= NEAR_PCT_DEFAULT:
            status = "near"

        results.append(
            BudgetCheckResult(
                category=cat,
                month=month,
                budget_clp=budget_clp,
                spent_clp=spent,
                remaining_clp=max(0, remaining),
                pct=pct,
                status=status,
            )
        )

    return results


# =========================
# Public entrypoint (called by signals)
# =========================

def handle_new_transaction(tx: Transaction) -> None:
    """
    Se ejecuta cuando se crea un Transaction (via signal).
    Envía notificaciones por Telegram (si el usuario está vinculado).
    Nunca debe lanzar excepción (para no botar /webhook/).
    """
    try:
        user = getattr(tx, "user", None)
        if not user:
            return

        chat_id = _get_user_telegram_chat_id(tx)
        if not chat_id:
            return  # no está vinculado

        # activar idioma usuario (si existe)
        lang = _get_user_language(tx)
        if lang:
            translation.activate(lang)

        checks = _check_budget_for_tx(tx)
        if not checks:
            return

        for res in checks:
            _notify_for_result(tx, chat_id, res)

    except Exception as e:
        logger.exception("handle_new_transaction fallo (no debe botar webhook): %s", e)
    finally:
        try:
            translation.deactivate()
        except Exception:
            pass


def _notify_for_result(tx: Transaction, chat_id: str, res: BudgetCheckResult) -> None:
    """
    Maneja state + envío de mensajes (over/near).
    """
    user = getattr(tx, "user", None)
    if not user:
        return

    cat = res.category
    month = res.month

    # Estado persistente (para saber si ya avisamos y cuánto era el exceso antes)
    # Evitar: state, _ = ... (bug). Usar nombres explícitos.
    state, state_created = BudgetAlertState.objects.get_or_create(
        user=user if hasattr(BudgetAlertState, "user") else None,
        category=cat if hasattr(BudgetAlertState, "category") else None,
        month=month if hasattr(BudgetAlertState, "month") else None,
    )

    # Si tu modelo no tiene esos campos, el get_or_create arriba podría fallar.
    # En ese caso, no persistimos y solo avisamos “best effort”.
    # (Pero en tu proyecto sí existe por la migración.)
    # Guardamos campos si existen:
    prev_status = getattr(state, "status", None) or getattr(state, "state", None) or ""

    # over delta actual
    over_now = max(0, res.spent_clp - res.budget_clp)

    # leer "old over" si existe
    old_over = None
    for fld in ("last_over_clp", "over_clp", "last_over", "over_amount"):
        if hasattr(state, fld):
            try:
                old_over = int(getattr(state, fld) or 0)
            except Exception:
                old_over = 0
            break

    # =========================
    # OVER
    # =========================
    if res.status == "over":
        if prev_status != "over":
            # Primer cruce a excedido
            title = _t("🚨 Presupuesto excedido: %(category)s (%(month)s)") % {
                "category": cat.name,
                "month": _month_label(month),
            }
            body = _t("Te pasaste por %(over)s CLP. Presupuesto: %(budget)s CLP · Gastado: %(spent)s CLP.") % {
                "over": _fmt_clp(over_now),
                "budget": _fmt_clp(res.budget_clp),
                "spent": _fmt_clp(res.spent_clp),
            }
            tip = _t("💡 Consejo: si ajustas hoy un gasto pequeño, vuelves al plan más rápido.")
            text = f"{title}\n\n{body}\n{tip}"
            _send_telegram(chat_id, text)
        else:
            # Ya estaba excedido: “sigues excedido” + conciencia
            # Solo lo mandamos si efectivamente cambió el exceso (para evitar spam inútil)
            if old_over is None or over_now != old_over:
                title = _t("🚨 Sigues excedido en %(category)s (%(month)s).") % {
                    "category": cat.name,
                    "month": _month_label(month),
                }
                body = _t("Antes ibas pasado por %(old)s CLP, ahora por %(new)s CLP.") % {
                    "old": _fmt_clp(old_over or 0),
                    "new": _fmt_clp(over_now),
                }
                awareness = _t("Esto te ayuda a tomar conciencia: cada gasto extra aumenta el desfase del plan.")
                text = f"{title}\n\n{body}\n{awareness}"
                _send_telegram(chat_id, text)

        # persistimos status + métricas
        _safe_set_fields(
            state,
            status="over",
            state="over",
            last_over_clp=over_now,
            over_clp=over_now,
            last_spent_clp=res.spent_clp,
            last_budget_clp=res.budget_clp,
            last_pct=res.pct,
            updated_at=timezone.now(),
        )
        try:
            state.save()
        except Exception:
            pass

        return

    # =========================
    # NEAR
    # =========================
    if res.status == "near":
        # Aviso solo si antes era "ok" (o vacío)
        if prev_status not in ("near", "over"):
            title = _t("⚠️ Vas en %(pct)s%% del presupuesto de %(category)s (%(month)s).") % {
                "pct": res.pct,
                "category": cat.name,
                "month": _month_label(month),
            }
            body = _t("Te queda aprox. %(remaining)s CLP.") % {
                "remaining": _fmt_clp(res.remaining_clp),
            }
            text = f"{title}\n\n{body}"
            _send_telegram(chat_id, text)

        _safe_set_fields(
            state,
            status="near",
            state="near",
            last_over_clp=0,
            over_clp=0,
            last_spent_clp=res.spent_clp,
            last_budget_clp=res.budget_clp,
            last_pct=res.pct,
            updated_at=timezone.now(),
        )
        try:
            state.save()
        except Exception:
            pass

        return

    # =========================
    # OK
    # =========================
    # Si vuelve a OK, guardamos para que futuros near/over vuelvan a notificar.
    if prev_status:
        _safe_set_fields(
            state,
            status="ok",
            state="ok",
            last_over_clp=0,
            over_clp=0,
            last_spent_clp=res.spent_clp,
            last_budget_clp=res.budget_clp,
            last_pct=res.pct,
            updated_at=timezone.now(),
        )
        try:
            state.save()
        except Exception:
            pass