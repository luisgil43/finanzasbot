from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from loans.models import Loan, LoanInstallment
from transactions.fx import get_usd_to_clp


def _parse_decimal(s: str) -> Optional[Decimal]:
    try:
        s = (s or "").strip().replace(" ", "")
        if not s:
            return None
        s = s.replace(".", "").replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


@login_required
def loan_list(request):
    qs = Loan.objects.filter(user=request.user).order_by("-id")
    status = (request.GET.get("status") or "").strip()

    if status in (Loan.STATUS_ACTIVE, Loan.STATUS_CLOSED, Loan.STATUS_CANCELED):
        qs = qs.filter(status=status)

    # refresca atrasos “on view” (MVP)
    for inst in LoanInstallment.objects.filter(
        loan__user=request.user,
        status__in=[LoanInstallment.STATUS_PENDING, LoanInstallment.STATUS_OVERDUE],
    ).select_related("loan"):
        inst.refresh_overdue_status()

    return render(request, "loans/loan_list.html", {"loans": qs, "status": status})


@login_required
def loan_create(request):
    if request.method == "POST":
        direction = (request.POST.get("direction") or "").strip()
        person = (request.POST.get("person_name") or "").strip()
        currency = (request.POST.get("currency_original") or "CLP").strip()
        principal = _parse_decimal(request.POST.get("principal_original") or "")
        installments = (request.POST.get("installments_count") or "").strip()
        frequency = (request.POST.get("frequency") or Loan.FREQ_MONTHLY).strip()
        first_due = (request.POST.get("first_due_date") or "").strip()
        note = (request.POST.get("note") or "").strip()

        if direction not in (Loan.DIRECTION_LENT, Loan.DIRECTION_BORROWED):
            messages.error(request, "Dirección inválida.")
            return render(request, "loans/loan_form.html")

        if not person:
            messages.error(request, "Debes indicar la persona.")
            return render(request, "loans/loan_form.html")

        if currency not in ("CLP", "USD"):
            currency = "CLP"

        if principal is None or principal <= 0:
            messages.error(request, "Monto inválido.")
            return render(request, "loans/loan_form.html")

        try:
            installments_n = int(installments)
            if installments_n < 1 or installments_n > 120:
                raise ValueError()
        except Exception:
            messages.error(request, "Cuotas inválidas (1 a 120).")
            return render(request, "loans/loan_form.html")

        if frequency not in (Loan.FREQ_MONTHLY, Loan.FREQ_WEEKLY, Loan.FREQ_BIWEEKLY):
            frequency = Loan.FREQ_MONTHLY

        first_due_date = None
        if first_due:
            try:
                first_due_date = timezone.datetime.fromisoformat(first_due).date()
            except Exception:
                first_due_date = None

        # principal_clp
        if currency == "USD":
            fx = get_usd_to_clp()
            rate = fx.rate or Decimal("1")
            if rate <= 0:
                rate = Decimal("1")
            principal_clp = (principal * rate).quantize(Decimal("1"))
            note_fx = f"FX {fx.source or 'fx'} {rate}"
        else:
            principal_clp = Decimal(principal).quantize(Decimal("1"))
            note_fx = ""

        with transaction.atomic():
            loan = Loan.objects.create(
                user=request.user,
                direction=direction,
                person_name=person,
                principal_original=principal,
                currency_original=currency,
                principal_clp=principal_clp,
                start_date=timezone.localdate(),
                first_due_date=first_due_date,
                installments_count=installments_n,
                frequency=frequency,
                note=(note_fx + ("\n" + note if note else "")).strip(),
                status=Loan.STATUS_ACTIVE,
            )
            loan.build_installments(replace_if_safe=True)

        messages.success(request, f"Préstamo creado (ID {loan.id}) ✅")
        return redirect("loans:detail", pk=loan.id)

    return render(request, "loans/loan_form.html")


@login_required
def loan_detail(request, pk: int):
    loan = get_object_or_404(Loan, pk=pk, user=request.user)
    installments = loan.installments.all().order_by("due_date", "n")

    # refresca atrasos “on view”
    for inst in installments:
        inst.refresh_overdue_status()

    return render(
        request,
        "loans/loan_detail.html",
        {
            "loan": loan,
            "installments": installments,
        },
    )


@login_required
def installment_pay(request, pk: int):
    inst = get_object_or_404(LoanInstallment, pk=pk, loan__user=request.user)
    loan = inst.loan

    if request.method == "POST":
        if inst.status == LoanInstallment.STATUS_PAID:
            messages.info(request, "Esa cuota ya estaba pagada.")
            return redirect("loans:detail", pk=loan.id)

        with transaction.atomic():
            inst.status = LoanInstallment.STATUS_PAID
            inst.paid_at = timezone.now()
            inst.paid_amount_original = inst.amount_original
            inst.paid_amount_clp = inst.amount_clp
            inst.save(
                update_fields=[
                    "status",
                    "paid_at",
                    "paid_amount_original",
                    "paid_amount_clp",
                    "updated_at",
                ]
            )

        messages.success(request, "Cuota marcada como pagada ✅")
        return redirect("loans:detail", pk=loan.id)

    return redirect("loans:detail", pk=loan.id)


@login_required
def loan_close(request, pk: int):
    loan = get_object_or_404(Loan, pk=pk, user=request.user)
    if request.method == "POST":
        loan.status = Loan.STATUS_CLOSED
        loan.save(update_fields=["status", "updated_at"])
        messages.success(request, "Préstamo cerrado ✅")
        return redirect("loans:detail", pk=loan.id)
    return redirect("loans:detail", pk=loan.id)