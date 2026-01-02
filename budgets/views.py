# budgets/views.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from budgets.models import BudgetCategory, MonthlyBudget, month_start
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


def _parse_month_yyyy_mm(val: str):
    """
    Recibe 'YYYY-MM' y retorna date YYYY-MM-01
    """
    val = (val or "").strip()
    if not val:
        return month_start(timezone.localdate())
    try:
        y, m = val.split("-")
        y = int(y)
        m = int(m)
        return timezone.datetime(y, m, 1).date()
    except Exception:
        return month_start(timezone.localdate())


def _month_range(d):
    start = month_start(d)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _spent_for_category(user, cat: BudgetCategory, month_date) -> Decimal:
    """
    MVP: suma gastos (amount_clp) de Transaction donde description contiene keywords de la categoría.
    Si la categoría no tiene keywords => 0.
    """
    start, end = _month_range(month_date)

    base = Transaction.objects.filter(
        user=user,
        kind=Transaction.KIND_EXPENSE,
        occurred_at__gte=start,
        occurred_at__lt=end,
    )

    kws = cat.keywords_list()
    if not kws:
        return Decimal("0")

    q = Q()
    for kw in kws:
        q |= Q(description__icontains=kw)

    total = base.filter(q).aggregate(total=Sum("amount_clp")).get("total") or Decimal("0")
    try:
        return Decimal(total)
    except Exception:
        return Decimal("0")


@login_required
def budget_list(request):
    # mes actual o ?month=YYYY-MM
    month_val = request.GET.get("month") or ""
    month_date = _parse_month_yyyy_mm(month_val)

    categories = BudgetCategory.objects.filter(user=request.user, is_active=True).order_by("name", "id")

    budgets = (
        MonthlyBudget.objects
        .filter(user=request.user, month=month_start(month_date))
        .select_related("category")
        .order_by("category__name", "id")
    )
    budget_by_cat = {b.category_id: b for b in budgets}

    rows = []
    total_budget = Decimal("0")
    total_spent = Decimal("0")

    for cat in categories:
        b = budget_by_cat.get(cat.id)
        budget_amount = (b.amount_clp if b else Decimal("0")) or Decimal("0")
        spent = _spent_for_category(request.user, cat, month_date)

        remaining = budget_amount - spent
        pct = Decimal("0")
        if budget_amount and budget_amount > 0:
            pct = (spent / budget_amount) * Decimal("100")

        status = "ok"
        if budget_amount > 0 and spent >= budget_amount:
            status = "over"
        elif budget_amount > 0 and pct >= 80:
            status = "near"

        rows.append({
            "category": cat,
            "budget": b,
            "budget_amount": budget_amount,
            "spent": spent,
            "remaining": remaining,
            "pct": pct,
            "status": status,
        })

        total_budget += budget_amount
        total_spent += spent

    ctx = {
        "month_date": month_date,
        "month_value": month_date.strftime("%Y-%m"),
        "categories": categories,
        "rows": rows,
        "total_budget": total_budget,
        "total_spent": total_spent,
        "total_remaining": total_budget - total_spent,
    }
    return render(request, "budgets/budget_list.html", ctx)


@login_required
def budget_create(request):
    month_val = request.GET.get("month") or ""
    month_date = _parse_month_yyyy_mm(month_val)

    categories = BudgetCategory.objects.filter(user=request.user, is_active=True).order_by("name", "id")

    if request.method == "POST":
        cat_id = (request.POST.get("category_id") or "").strip()
        amount_raw = request.POST.get("amount_clp") or ""
        note = (request.POST.get("note") or "").strip()
        month_post = _parse_month_yyyy_mm(request.POST.get("month") or "")

        cat = BudgetCategory.objects.filter(user=request.user, id=cat_id).first()
        if not cat:
            messages.error(request, _("Selecciona una categoría válida."))
            return render(request, "budgets/budget_form.html", {
                "mode": "create",
                "month_value": month_post.strftime("%Y-%m"),
                "categories": categories,
                "data": request.POST,
            })

        amount = _parse_decimal(amount_raw)
        if amount is None or amount < 0:
            messages.error(request, _("Monto inválido."))
            return render(request, "budgets/budget_form.html", {
                "mode": "create",
                "month_value": month_post.strftime("%Y-%m"),
                "categories": categories,
                "data": request.POST,
            })

        b, created = MonthlyBudget.objects.get_or_create(
            user=request.user,
            category=cat,
            month=month_start(month_post),
            defaults={"amount_clp": amount, "note": note},
        )
        if not created:
            b.amount_clp = amount
            b.note = note
            b.save(update_fields=["amount_clp", "note", "updated_at"])

        messages.success(request, _("Presupuesto guardado ✅"))
        return redirect(f"/budgets/?month={month_start(month_post).strftime('%Y-%m')}")

    return render(request, "budgets/budget_form.html", {
        "mode": "create",
        "month_value": month_date.strftime("%Y-%m"),
        "categories": categories,
        "data": {},
    })


@login_required
def budget_edit(request, pk: int):
    b = get_object_or_404(MonthlyBudget, pk=pk, user=request.user)
    categories = BudgetCategory.objects.filter(user=request.user, is_active=True).order_by("name", "id")

    if request.method == "POST":
        cat_id = (request.POST.get("category_id") or "").strip()
        amount_raw = request.POST.get("amount_clp") or ""
        note = (request.POST.get("note") or "").strip()
        month_post = _parse_month_yyyy_mm(request.POST.get("month") or "")

        cat = BudgetCategory.objects.filter(user=request.user, id=cat_id).first()
        if not cat:
            messages.error(request, _("Selecciona una categoría válida."))
            return render(request, "budgets/budget_form.html", {
                "mode": "edit",
                "budget": b,
                "month_value": month_post.strftime("%Y-%m"),
                "categories": categories,
                "data": request.POST,
            })

        amount = _parse_decimal(amount_raw)
        if amount is None or amount < 0:
            messages.error(request, _("Monto inválido."))
            return render(request, "budgets/budget_form.html", {
                "mode": "edit",
                "budget": b,
                "month_value": month_post.strftime("%Y-%m"),
                "categories": categories,
                "data": request.POST,
            })

        b.category = cat
        b.month = month_start(month_post)
        b.amount_clp = amount
        b.note = note
        b.save()

        messages.success(request, _("Presupuesto actualizado ✅"))
        return redirect(f"/budgets/?month={b.month.strftime('%Y-%m')}")

    return render(request, "budgets/budget_form.html", {
        "mode": "edit",
        "budget": b,
        "month_value": b.month.strftime("%Y-%m"),
        "categories": categories,
        "data": {
            "category_id": b.category_id,
            "amount_clp": str(b.amount_clp),
            "note": b.note,
            "month": b.month.strftime("%Y-%m"),
        },
    })


@login_required
def budget_delete(request, pk: int):
    b = get_object_or_404(MonthlyBudget, pk=pk, user=request.user)
    if request.method != "POST":
        return HttpResponseForbidden("POST only")
    month_str = b.month.strftime("%Y-%m")
    b.delete()
    messages.success(request, _("Presupuesto eliminado 🗑️"))
    return redirect(f"/budgets/?month={month_str}")


@login_required
def category_create(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only")

    name = (request.POST.get("name") or "").strip()
    kw = (request.POST.get("match_keywords") or "").strip()
    next_month = (request.POST.get("month") or "").strip()

    if not name:
        messages.error(request, _("Nombre de categoría requerido."))
        return redirect(f"/budgets/?month={next_month}" if next_month else "/budgets/")

    obj, created = BudgetCategory.objects.get_or_create(
        user=request.user,
        name=name,
        defaults={"match_keywords": kw, "is_active": True},
    )
    if not created:
        # si existe, actualizamos keywords si venía algo
        if kw and obj.match_keywords != kw:
            obj.match_keywords = kw
            obj.save(update_fields=["match_keywords"])
            messages.success(request, _("Categoría actualizada ✅"))
        else:
            messages.info(request, _("La categoría ya existe."))
    else:
        messages.success(request, _("Categoría creada ✅"))

    return redirect(f"/budgets/?month={next_month}" if next_month else "/budgets/")

@login_required
def category_edit(request, pk):
    cat = get_object_or_404(BudgetCategory, user=request.user, pk=pk)

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        match_keywords = (request.POST.get("match_keywords") or "").strip()

        if not name:
            messages.error(request, _("Nombre de categoría requerido."))
            return redirect("budgets:category_edit", pk=pk)

        # Evita duplicado por nombre (case-insensitive) dentro del usuario
        exists = (BudgetCategory.objects
                  .filter(user=request.user, name__iexact=name)
                  .exclude(pk=pk)
                  .exists())
        if exists:
            messages.error(request, _("La categoría ya existe."))
            return redirect("budgets:category_edit", pk=pk)

        cat.name = name
        cat.match_keywords = match_keywords
        cat.save(update_fields=["name", "match_keywords"])

        messages.success(request, _("Categoría actualizada ✅"))
        return redirect("budgets:list")

    return render(request, "budgets/category_form.html", {"cat": cat})