from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView


def healthz(request):
    return JsonResponse({"ok": True})

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    

    # Raíz -> dashboard
    path("", RedirectView.as_view(url="/usuarios/", permanent=False)),

    # Todo accounts bajo /usuarios/
    path("usuarios/", include("accounts.urls")),

    # Webhook bot
    path("bot/telegram/", include("bot_telegram.urls")),

    path("owner/", include("owner_panel.urls")),

    path("movimientos/", include(("transactions.urls", "transactions"), namespace="transactions")),
    path("prestamos/", include(("loans.urls", "loans"), namespace="loans")),
    path("budgets/", include("budgets.urls")),
    path("cards/", include("cards.urls")),
    path("", include("ocr_receipts.urls")),
    path("healthz/", healthz, name="healthz"),
]