from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ReceiptConfirmForm, ReceiptUploadForm
from .models import ReceiptUpload
from .services import (create_transaction_from_receipt,
                       extract_text_from_image, parse_receipt_text)


@login_required
def receipt_upload(request):
    if request.method == "POST":
        form = ReceiptUploadForm(request.POST, request.FILES)
        if form.is_valid():
            obj = ReceiptUpload.objects.create(
                user=request.user,
                image=form.cleaned_data["image"],
                status=ReceiptUpload.STATUS_PENDING,
            )

            text, err = extract_text_from_image(obj.image.name)
            if err:
                obj.status = ReceiptUpload.STATUS_FAILED
                obj.error = err[:255]
                obj.ocr_text = text or ""
                obj.save(update_fields=["status", "error", "ocr_text", "updated_at"])
                # Igual lo mandamos a confirmación para carga manual
                return redirect("receipts:confirm", pk=obj.pk)

            parsed = parse_receipt_text(text)

            obj.ocr_text = parsed.raw_text
            obj.suggested_amount = parsed.amount
            obj.suggested_currency = parsed.currency or "CLP"
            obj.suggested_date = parsed.occurred_date
            obj.suggested_merchant = parsed.merchant or ""
            obj.suggested_description = parsed.description or ""
            obj.status = ReceiptUpload.STATUS_PARSED
            obj.save()

            return redirect("receipts:confirm", pk=obj.pk)
    else:
        form = ReceiptUploadForm()

    return render(request, "receipts/upload.html", {"form": form})


@login_required
def receipt_confirm(request, pk: int):
    obj = get_object_or_404(ReceiptUpload, pk=pk, user=request.user)

    if obj.status in (ReceiptUpload.STATUS_CONFIRMED, ReceiptUpload.STATUS_CANCELED):
        return redirect("transactions:list")  # ajusta si tu url name es distinto

    initial = {
        "kind": "expense",
        "amount": (str(obj.suggested_amount) if obj.suggested_amount else ""),
        "currency": obj.suggested_currency or "CLP",
        "occurred_date": obj.suggested_date,
        "description": (obj.suggested_description or obj.suggested_merchant or "Boleta"),
        "card_id": (str(obj.confirmed_card_id) if obj.confirmed_card_id else ""),
    }

    if request.method == "POST":
        if "cancel" in request.POST:
            obj.status = ReceiptUpload.STATUS_CANCELED
            obj.save(update_fields=["status", "updated_at"])
            return redirect("transactions:list")

        form = ReceiptConfirmForm(request.POST, user=request.user)
        if form.is_valid():
            kind = form.cleaned_data["kind"]
            amount: Decimal = form.cleaned_data["amount"]
            currency = form.cleaned_data["currency"]
            d = form.cleaned_data.get("occurred_date") or timezone.localdate()
            desc = (form.cleaned_data.get("description") or "Boleta").strip()
            card_id = (form.cleaned_data.get("card_id") or "").strip()
            card = None
            if card_id:
                from cards.models import Card
                card = Card.objects.filter(user=request.user, is_active=True, id=int(card_id)).first()

            tx = create_transaction_from_receipt(
                user=request.user,
                kind=kind,
                amount=amount,
                currency=currency,
                occurred_at=timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.min.time())),
                description=desc,
                card=card,
            )

            obj.confirmed_amount = amount
            obj.confirmed_currency = currency
            obj.confirmed_date = d
            obj.confirmed_description = desc
            obj.confirmed_card = card
            obj.created_transaction = tx
            obj.status = ReceiptUpload.STATUS_CONFIRMED
            obj.save()

            return redirect("transactions:list")  # o redirect al detail del movimiento
    else:
        form = ReceiptConfirmForm(initial=initial, user=request.user)

    ctx = {
        "obj": obj,
        "form": form,
    }
    return render(request, "receipts/confirm.html", ctx)