from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from transactions.models import Transaction

from .forms import CardForm
from .models import Card


def _month_label(d):
    return d.strftime("%Y-%m")


def _spent_for_card_in_cycle(card: Card, start, end) -> Decimal:
    agg = (
        Transaction.objects
        .filter(
            user=card.user,
            card=card,
            kind=Transaction.KIND_EXPENSE,
            occurred_at__date__gte=start,
            occurred_at__date__lte=end,
        )
        .aggregate(s=Sum("amount_clp"))
    )
    return agg["s"] or Decimal("0")


@login_required
def card_list(request):
    cards = Card.objects.filter(user=request.user).order_by("-is_active", "name")
    today = timezone.localdate()

    rows = []
    total_limit = Decimal("0.00")
    total_spent = Decimal("0.00")

    for c in cards:
        start = c.cycle_start_for(today)
        end = c.cycle_end_for(today)
        spent = _spent_for_card_in_cycle(c, start, end)
        available = (c.credit_limit or Decimal("0.00")) - spent

        total_limit += (c.credit_limit or Decimal("0.00"))
        total_spent += spent

        rows.append({
            "card": c,
            "cycle_start": start,
            "cycle_end": end,
            "spent": spent,
            "available": available,
        })

    ctx = {
        "rows": rows,
        "total_limit": total_limit,
        "total_spent": total_spent,
        "total_available": total_limit - total_spent,
    }
    return render(request, "cards/card_list.html", ctx)


@login_required
def card_detail(request, pk: int):
    card = get_object_or_404(Card, pk=pk, user=request.user)
    today = timezone.localdate()
    start = card.cycle_start_for(today)
    end = card.cycle_end_for(today)
    spent = _spent_for_card_in_cycle(card, start, end)
    available = (card.credit_limit or Decimal("0.00")) - spent

    return render(request, "cards/card_detail.html", {
        "card": card,
        "cycle_start": start,
        "cycle_end": end,
        "spent": spent,
        "available": available,
    })


@login_required
def card_create(request):
    if request.method == "POST":
        form = CardForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, _("Tarjeta creada ✅"))
            return redirect("cards:list")
    else:
        form = CardForm()

    return render(request, "cards/card_form.html", {
        "form": form,
        "is_edit": False,
    })


@login_required
def card_edit(request, pk: int):
    card = get_object_or_404(Card, pk=pk, user=request.user)

    if request.method == "POST":
        form = CardForm(request.POST, instance=card)
        if form.is_valid():
            form.save()
            messages.success(request, _("Tarjeta actualizada ✅"))
            return redirect("cards:list")
    else:
        form = CardForm(instance=card)

    return render(request, "cards/card_form.html", {
        "form": form,
        "is_edit": True,
        "card": card,
    })


@login_required
@require_POST
def card_delete(request, pk: int):
    card = get_object_or_404(Card, pk=pk, user=request.user)
    card.delete()
    messages.success(request, _("Tarjeta eliminada 🗑️"))
    return redirect("cards:list")