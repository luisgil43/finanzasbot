# transactions/views.py

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

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


@login_required
def transaction_list(request):
    qs = Transaction.objects.filter(user=request.user).order_by("-occurred_at", "-id")

    kind = (request.GET.get("kind") or "").strip()
    cur = (request.GET.get("cur") or "").strip()
    q = (request.GET.get("q") or "").strip()

    date_from = (request.GET.get("from") or "").strip()
    date_to = (request.GET.get("to") or "").strip()

    # 👇 NUEVO
    card_id = (request.GET.get("card") or "").strip()

    if kind in (Transaction.KIND_EXPENSE, Transaction.KIND_INCOME):
        qs = qs.filter(kind=kind)

    if cur in ("CLP", "USD"):
        qs = qs.filter(currency_original=cur)

    if q:
        qs = qs.filter(Q(description__icontains=q))

    # 👇 NUEVO: filtro por tarjeta
    if card_id:
        try:
            qs = qs.filter(card_id=int(card_id))
        except Exception:
            pass

    # fechas (YYYY-MM-DD)
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

    # 👇 NUEVO: tarjetas para filtro (todas, activas o no)
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
            "cards": cards,     # 👈 NUEVO
            "card_id": card_id, # 👈 NUEVO
        },
    )


@login_required
def transaction_create(request):
    # mostramos tarjetas activas para asignar (si quieres mostrar inactivas también dime)
    cards = Card.objects.filter(user=request.user, is_active=True).order_by("name")

    if request.method == "POST":
        kind = (request.POST.get("kind") or Transaction.KIND_EXPENSE).strip()
        currency = (request.POST.get("currency_original") or "CLP").strip()
        amount = _parse_decimal(request.POST.get("amount_original") or "")
        desc = (request.POST.get("description") or "").strip()
        occurred_at_raw = (request.POST.get("occurred_at") or "").strip()

        # 👇 NUEVO
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
                    {"cards": cards, "selected_card_id": card_id_raw},
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
                {"cards": cards, "selected_card_id": card_id_raw},
            )

        occurred_at = timezone.now()
        if occurred_at_raw:
            try:
                occurred_at = timezone.make_aware(
                    timezone.datetime.fromisoformat(occurred_at_raw)
                )
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
            card=card_obj,  # 👈 NUEVO
        )

        messages.success(request, _("Movimiento creado (ID %(id)s) ✅") % {"id": tx.id})
        return redirect("transactions:list")

    return render(request, "transactions/transaction_form.html", {"cards": cards})


@login_required
def transaction_delete(request, pk: int):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    if request.method == "POST":
        tx.delete()
        messages.success(request, _("Movimiento eliminado 🗑️"))
        return redirect("transactions:list")
    return redirect("transactions:list")