# transactions/views.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from budgets.models import BudgetCategory  # ✅ NUEVO
from cards.models import Card
from transactions.fx import get_usd_to_clp
from transactions.models import Transaction


def _parse_decimal(s: str) -> Optional[Decimal]:
    try:
        s = (s or "").strip().replace(" ", "")
        if not s:
            return None
        # soporta "320.240" o "320,240" o "320240"
        s = s.replace(".", "").replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _load_user_categories(user) -> List[Tuple[BudgetCategory, List[str]]]:
    """
    Carga categorías activas del usuario y sus keywords en minúscula.
    """
    cats = BudgetCategory.objects.filter(user=user, is_active=True).order_by("name", "id")
    out: List[Tuple[BudgetCategory, List[str]]] = []
    for c in cats:
        kws = []
        raw = (c.match_keywords or "").strip()
        if raw:
            kws = [p.strip().lower() for p in raw.split(",") if p.strip()]
        out.append((c, kws))
    return out


def _infer_category_from_description(
    categories: List[Tuple[BudgetCategory, List[str]]],
    description: str,
) -> Optional[BudgetCategory]:
    """
    Regla MVP: asigna la primera categoría cuyo keyword aparezca en la descripción.
    (Puedes cambiar luego a “mejor match” si quieres).
    """
    text = (description or "").strip().lower()
    if not text:
        return None

    for cat, kws in categories:
        for kw in kws:
            if kw and kw in text:
                return cat
    return None


@login_required
def transaction_list(request):
    qs = (
        Transaction.objects
        .filter(user=request.user)
        .select_related("card")  # ✅ solo relaciones reales
        .order_by("-occurred_at", "-id")
    )

    kind = (request.GET.get("kind") or "").strip()
    cur = (request.GET.get("cur") or "").strip()
    q = (request.GET.get("q") or "").strip()

    date_from = (request.GET.get("from") or "").strip()
    date_to = (request.GET.get("to") or "").strip()

    card_id = (request.GET.get("card") or "").strip()

    if kind in (Transaction.KIND_EXPENSE, Transaction.KIND_INCOME):
        qs = qs.filter(kind=kind)

    if cur in ("CLP", "USD"):
        qs = qs.filter(currency_original=cur)

    if q:
        qs = qs.filter(Q(description__icontains=q))

    if card_id:
        try:
            qs = qs.filter(card_id=int(card_id))
        except Exception:
            pass

    if date_from:
        try:
            d = timezone.datetime.fromisoformat(date_from).date()
            qs = qs.filter(occurred_at__date__gte=d)
        except Exception:
            pass

    if date_to:
        try:
            d = timezone.datetime.fromisoformat(date_to).date()
            qs = qs.filter(occurred_at__date__lte=d)
        except Exception:
            pass

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page") or 1)

    # ✅ NUEVO: calcular categoría por keywords y “inyectar” t.category para el template
    user_categories = _load_user_categories(request.user)
    for t in page.object_list:
        # Solo tiene sentido categorizar gastos, pero si quieres para income también, quita el if
        if getattr(t, "kind", None) == Transaction.KIND_EXPENSE:
            t.category = _infer_category_from_description(user_categories, getattr(t, "description", "") or "")
        else:
            t.category = None

    cards = Card.objects.filter(user=request.user).order_by("-is_active", "name")

    return render(
        request,
        "transactions/transaction_list.html",
        {
            "page": page,
            "kind": kind,
            "cur": cur,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "cards": cards,
            "card_id": card_id,
        },
    )


@login_required
def transaction_create(request):
    cards = Card.objects.filter(user=request.user, is_active=True).order_by("name")

    if request.method == "POST":
        kind = (request.POST.get("kind") or Transaction.KIND_EXPENSE).strip()
        currency = (request.POST.get("currency_original") or "CLP").strip()
        amount = _parse_decimal(request.POST.get("amount_original") or "")
        desc = (request.POST.get("description") or "").strip()
        occurred_at_raw = (request.POST.get("occurred_at") or "").strip()

        card_id_raw = (request.POST.get("card_id") or "").strip()
        card_obj = None
        if card_id_raw:
            try:
                card_obj = Card.objects.get(pk=int(card_id_raw), user=request.user)
            except Exception:
                messages.error(request, _("Tarjeta inválida."))
                return render(
                    request,
                    "transactions/transaction_form.html",
                    {"cards": cards, "selected_card_id": card_id_raw, "mode": "create"},
                )

        if kind not in (Transaction.KIND_EXPENSE, Transaction.KIND_INCOME):
            kind = Transaction.KIND_EXPENSE

        if currency not in ("CLP", "USD"):
            currency = "CLP"

        if amount is None or amount <= 0:
            messages.error(request, _("Monto inválido."))
            return render(
                request,
                "transactions/transaction_form.html",
                {"cards": cards, "selected_card_id": card_id_raw, "mode": "create"},
            )

        occurred_at = timezone.now()
        if occurred_at_raw:
            try:
                occurred_at = timezone.make_aware(timezone.datetime.fromisoformat(occurred_at_raw))
            except Exception:
                occurred_at = timezone.now()

        # normalización CLP
        if currency == "USD":
            fx = get_usd_to_clp()
            fx_rate = (fx.rate or Decimal("1"))
            if fx_rate <= 0:
                fx_rate = Decimal("1")
            amount_clp = (amount * fx_rate).quantize(Decimal("1"))
            fx_source = fx.source or "fx"
            fx_timestamp = timezone.now()
        else:
            amount_clp = Decimal(amount).quantize(Decimal("1"))
            fx_rate = Decimal("1")
            fx_source = "base"
            fx_timestamp = timezone.now()

        tx = Transaction.objects.create(
            user=request.user,
            kind=kind,
            amount_original=amount,
            currency_original=currency,
            amount_clp=amount_clp,
            fx_rate=fx_rate,
            fx_source=fx_source,
            fx_timestamp=fx_timestamp,
            description=desc,
            source="web",
            occurred_at=occurred_at,
            card=card_obj,
        )

        messages.success(request, _("Movimiento creado (ID %(id)s) ✅") % {"id": tx.id})
        return redirect("transactions:list")

    return render(request, "transactions/transaction_form.html", {"cards": cards, "mode": "create"})


@login_required
def transaction_edit(request, pk: int):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)

    # al editar, permitimos seleccionar cualquier tarjeta del usuario (activa o no)
    cards = Card.objects.filter(user=request.user).order_by("-is_active", "name")

    if request.method == "POST":
        kind = (request.POST.get("kind") or tx.kind).strip()
        currency = (request.POST.get("currency_original") or tx.currency_original or "CLP").strip()
        amount = _parse_decimal(request.POST.get("amount_original") or "")
        desc = (request.POST.get("description") or "").strip()
        occurred_at_raw = (request.POST.get("occurred_at") or "").strip()

        card_id_raw = (request.POST.get("card_id") or "").strip()
        card_obj = None
        if card_id_raw:
            try:
                card_obj = Card.objects.get(pk=int(card_id_raw), user=request.user)
            except Exception:
                messages.error(request, _("Tarjeta inválida."))
                return render(
                    request,
                    "transactions/transaction_form.html",
                    {
                        "cards": cards,
                        "mode": "edit",
                        "tx": tx,
                        "selected_card_id": card_id_raw,
                    },
                )

        if kind not in (Transaction.KIND_EXPENSE, Transaction.KIND_INCOME):
            kind = Transaction.KIND_EXPENSE

        if currency not in ("CLP", "USD"):
            currency = "CLP"

        if amount is None or amount <= 0:
            messages.error(request, _("Monto inválido."))
            return render(
                request,
                "transactions/transaction_form.html",
                {
                    "cards": cards,
                    "mode": "edit",
                    "tx": tx,
                    "selected_card_id": card_id_raw,
                },
            )

        occurred_at = tx.occurred_at
        if occurred_at_raw:
            try:
                occurred_at = timezone.make_aware(timezone.datetime.fromisoformat(occurred_at_raw))
            except Exception:
                occurred_at = tx.occurred_at

        # recalcular CLP base si cambia monto/moneda
        if currency == "USD":
            fx = get_usd_to_clp()
            fx_rate = (fx.rate or Decimal("1"))
            if fx_rate <= 0:
                fx_rate = Decimal("1")
            amount_clp = (amount * fx_rate).quantize(Decimal("1"))
            fx_source = fx.source or "fx"
            fx_timestamp = timezone.now()
        else:
            amount_clp = Decimal(amount).quantize(Decimal("1"))
            fx_rate = Decimal("1")
            fx_source = "base"
            fx_timestamp = timezone.now()

        tx.kind = kind
        tx.currency_original = currency
        tx.amount_original = amount
        tx.amount_clp = amount_clp
        tx.fx_rate = fx_rate
        tx.fx_source = fx_source
        tx.fx_timestamp = fx_timestamp
        tx.description = desc
        tx.occurred_at = occurred_at
        tx.card = card_obj
        tx.save()

        messages.success(request, _("Movimiento actualizado ✅"))
        return redirect("transactions:list")

    # GET: precargar form
    occurred_at_local = timezone.localtime(tx.occurred_at) if tx.occurred_at else timezone.localtime(timezone.now())
    occurred_at_str = occurred_at_local.strftime("%Y-%m-%dT%H:%M")

    # ✅ NUEVO: categoría inferida para mostrar en el form (solo lectura)
    user_categories = _load_user_categories(request.user)
    if tx.kind == Transaction.KIND_EXPENSE:
        tx.category = _infer_category_from_description(user_categories, tx.description or "")
    else:
        tx.category = None

    return render(
        request,
        "transactions/transaction_form.html",
        {
            "cards": cards,
            "mode": "edit",
            "tx": tx,
            "selected_card_id": str(tx.card_id or ""),
            "occurred_at_str": occurred_at_str,
        },
    )


@login_required
def transaction_delete(request, pk: int):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    if request.method == "POST":
        tx.delete()
        messages.success(request, _("Movimiento eliminado 🗑️"))
        return redirect("transactions:list")
    return redirect("transactions:list")