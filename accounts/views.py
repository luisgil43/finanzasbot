# accounts/views.py
from __future__ import annotations

import secrets
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.encoding import force_bytes
from django.utils.http import (url_has_allowed_host_and_scheme,
                               urlsafe_base64_decode, urlsafe_base64_encode)
from django.views.decorators.http import require_POST

from .forms import SignUpForm

UserModel = get_user_model()


# En Django 5.x, usa la key directa (LANGUAGE_SESSION_KEY ya no existe)
LANG_SESSION_KEY = "django_language"


def _safe_next_url(request, next_url: str | None, fallback_name: str = "accounts:dashboard") -> str:
    fallback = reverse(fallback_name)
    raw = (next_url or "").strip() or fallback

    if not url_has_allowed_host_and_scheme(
        raw,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return fallback
    return raw


def _apply_language_to_request(request, lang: str) -> None:
    """
    Aplica idioma a request (thread-local) y deja sesión lista para LocaleMiddleware.
    """
    request.session[LANG_SESSION_KEY] = lang
    translation.activate(lang)
    request.LANGUAGE_CODE = lang


def _set_language_cookie(resp: HttpResponseRedirect, lang: str) -> None:
    """
    Guarda cookie para que el idioma persista aunque cambie la sesión.
    """
    resp.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang)


def login_view(request):
    next_url = _safe_next_url(
        request,
        request.GET.get("next") or request.POST.get("next"),
        fallback_name="accounts:dashboard",
    )

    if request.method == "POST":
        identifier = (request.POST.get("username") or "").strip()  # username o email
        password = request.POST.get("password") or ""

        user = authenticate(request, username=identifier, password=password)

        # si no autenticó por username, intentamos por email
        if user is None and identifier:
            u = UserModel.objects.filter(email__iexact=identifier).first()
            if u:
                user = authenticate(request, username=u.get_username(), password=password)

        if user is None:
            messages.error(request, "Usuario/correo o contraseña incorrectos.")
            return render(request, "accounts/login.html", {"next": next_url})

        if not user.is_active:
            messages.error(request, "Tu cuenta está inactiva. Revisa el correo de verificación.")
            return render(request, "accounts/login.html", {"next": next_url})

        login(request, user)

        # ✅ Aplicar idioma guardado en UserProfile al iniciar sesión
        lang_to_set = None
        try:
            from accounts.models import \
                UserProfile  # local import para evitar ciclos
            prof, _ = UserProfile.objects.get_or_create(user=user)
            lang = (prof.language or "").strip()
            if lang and lang in dict(settings.LANGUAGES):
                lang_to_set = lang
                _apply_language_to_request(request, lang_to_set)
        except Exception:
            pass

        resp = redirect(next_url)

        # cookie para persistir idioma (si existe idioma guardado)
        if lang_to_set:
            _set_language_cookie(resp, lang_to_set)

        return resp

    return render(request, "accounts/login.html", {"next": next_url})


def signup(request):
    from accounts.models import UserProfile

    if request.method == "POST":
        form = SignUpForm(request.POST)

        # ✅ Si intentan registrarse con un email ya existente:
        email = (request.POST.get("email") or "").strip().lower()
        if email:
            existing = UserModel.objects.filter(email__iexact=email).first()
            if existing:
                if existing.is_active:
                    messages.error(request, "Este correo ya tiene cuenta. Inicia sesión.")
                    return render(request, "accounts/signup.html", {"form": form})

                # Si existe pero está inactiva => reenviar verificación
                try:
                    _send_verification_email(existing)
                    messages.success(request, "Te reenviamos el correo de verificación ✅")
                    return render(request, "accounts/signup_done.html", {"email": existing.email})
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Resend verification failed")
                    messages.error(request, "No pudimos reenviar el correo ahora. Intenta nuevamente.")
                    return render(request, "accounts/signup.html", {"form": form})

        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            prof, _ = UserProfile.objects.get_or_create(user=user)
            prof.email_verified = False
            prof.save(update_fields=["email_verified"])

            try:
                _send_verification_email(user)
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Email verification send failed: %s", e)
                messages.error(
                    request,
                    "No pudimos enviar el correo de verificación (SMTP). "
                    "Intenta nuevamente en unos minutos."
                )
                # opcional: evitar cuentas muertas
                # user.delete()
                return render(request, "accounts/signup.html", {"form": form})

            return render(request, "accounts/signup_done.html", {"email": user.email})

        return render(request, "accounts/signup.html", {"form": form})

    form = SignUpForm()
    return render(request, "accounts/signup.html", {"form": form})


def _send_verification_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    verify_url = base + reverse("accounts:verify_email", args=[uid, token])

    subject = "Verifica tu correo"
    body = (
        f"Hola {user.username},\n\n"
        f"Verifica tu correo aquí:\n{verify_url}\n\n"
        "Si no fuiste tú, ignora este mensaje."
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


def verify_email(request, uidb64, token):
    from accounts.models import UserProfile

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = UserModel.objects.get(pk=uid)
    except Exception:
        user = None

    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save(update_fields=["is_active"])

        prof, _ = UserProfile.objects.get_or_create(user=user)
        prof.email_verified = True
        prof.save(update_fields=["email_verified"])

        messages.success(request, "Correo verificado ✅ Ya puedes iniciar sesión.")
        return redirect("accounts:login")

    messages.error(request, "Link inválido o expirado. Intenta registrarte nuevamente.")
    return redirect("accounts:signup")


@login_required
def dashboard(request):
    from accounts.models import UserProfile
    from transactions.fx import get_usd_to_clp
    from transactions.models import Transaction

    prof, _ = UserProfile.objects.get_or_create(user=request.user)

    # Mes actual (hora local)
    now = timezone.localtime(timezone.now())
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    qs_month = Transaction.objects.filter(
        user=request.user,
        occurred_at__gte=start,
        occurred_at__lt=end,
    )

    total_expense_clp = (
        qs_month.filter(kind=Transaction.KIND_EXPENSE).aggregate(total=Sum("amount_clp")).get("total")
        or Decimal("0")
    )
    total_income_clp = (
        qs_month.filter(kind=Transaction.KIND_INCOME).aggregate(total=Sum("amount_clp")).get("total")
        or Decimal("0")
    )
    balance_clp = total_income_clp - total_expense_clp

    fx = get_usd_to_clp()
    fx_rate = fx.rate if getattr(fx, "rate", None) and fx.rate > 0 else Decimal("1")

    total_expense_usd = (total_expense_clp / fx_rate) if fx_rate else Decimal("0")
    total_income_usd = (total_income_clp / fx_rate) if fx_rate else Decimal("0")
    balance_usd = (balance_clp / fx_rate) if fx_rate else Decimal("0")

    recent = Transaction.objects.filter(user=request.user).order_by("-occurred_at", "-id")[:15]

    pref = (prof.currency or "CLP").upper()
    if pref == "USD":
        display_currency = "USD"
        display_expense = total_expense_usd
        display_income = total_income_usd
        display_balance = balance_usd
    else:
        display_currency = "CLP"
        display_expense = total_expense_clp
        display_income = total_income_clp
        display_balance = balance_clp

    return render(
        request,
        "accounts/dashboard.html",
        {
            "profile": prof,
            "fx": fx,
            "total_expense_clp": total_expense_clp,
            "total_income_clp": total_income_clp,
            "balance_clp": balance_clp,
            "total_expense_usd": total_expense_usd,
            "total_income_usd": total_income_usd,
            "balance_usd": balance_usd,
            "display_currency": display_currency,
            "display_expense": display_expense,
            "display_income": display_income,
            "display_balance": display_balance,
            "recent": recent,
        },
    )


@login_required
def profile(request):
    from accounts.models import UserProfile

    prof, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        currency = (request.POST.get("currency") or prof.currency or "CLP").upper()
        language = (request.POST.get("language") or prof.language or "").strip()

        if currency in ("CLP", "USD"):
            prof.currency = currency

        allowed_langs = dict(settings.LANGUAGES).keys()
        lang_to_set = None
        if language in allowed_langs:
            prof.language = language
            lang_to_set = language
            _apply_language_to_request(request, lang_to_set)

        prof.save(update_fields=["currency", "language"])
        messages.success(request, "Perfil actualizado ✅")

        resp = redirect("accounts:profile")
        if lang_to_set:
            _set_language_cookie(resp, lang_to_set)
        return resp

    return render(request, "accounts/profile.html", {"profile": prof})


@login_required
def telegram_link(request):
    if not getattr(settings, "TELEGRAM_BOT_USERNAME", ""):
        messages.error(request, "Falta configurar TELEGRAM_BOT_USERNAME en .env")
        return redirect("accounts:dashboard")

    from accounts.models import UserProfile

    code = secrets.token_urlsafe(16)

    prof, _ = UserProfile.objects.get_or_create(user=request.user)
    prof.telegram_link_code = code
    prof.save(update_fields=["telegram_link_code"])

    deep_link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={code}"
    start_command = f"/start {code}"

    return render(
        request,
        "accounts/telegram_link.html",
        {
            "deep_link": deep_link,
            "code": code,
            "start_command": start_command,  # ✅ NUEVO
            "profile": prof,
        },
    )


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@require_POST
def set_language(request):
    """
    Cambia el idioma desde el selector del header.

    - Setea sesión/cookie para que LocaleMiddleware traduzca toda la UI.
    - Si el usuario está logueado, persiste en UserProfile.language.
    """
    from accounts.models import UserProfile

    lang = (request.POST.get("language") or "").strip()
    next_url = _safe_next_url(
        request,
        request.POST.get("next") or request.META.get("HTTP_REFERER") or "/",
        fallback_name="accounts:dashboard",
    )

    allowed = dict(settings.LANGUAGES).keys()
    if lang not in allowed:
        return redirect(next_url)

    # 1) sesión + activar
    _apply_language_to_request(request, lang)

    # 2) persistir en perfil si autenticado
    if request.user.is_authenticated:
        prof, _ = UserProfile.objects.get_or_create(user=request.user)
        if prof.language != lang:
            prof.language = lang
            prof.save(update_fields=["language"])

    # 3) cookie
    resp = redirect(next_url)
    _set_language_cookie(resp, lang)
    return resp