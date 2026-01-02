# accounts/middleware.py
from __future__ import annotations

from django.conf import settings
from django.utils import translation


class ProfileLanguageMiddleware:
    """
    Aplica el idioma preferido del usuario (UserProfile.language) a cada request.

    Problemas que resuelve:
    - El selector del header cambiaba solo sesión/cookie, pero NO persistía en perfil,
      por lo que Telegram seguía en el idioma anterior.
    - Al volver a iniciar sesión, el idioma volvía a 'es' (LANGUAGE_CODE), aunque el
      usuario tuviera profile.language='en'.

    Esta capa deja el idioma pegado al usuario logueado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                prof = getattr(user, "userprofile", None)
                lang = getattr(prof, "language", None)

                if lang and lang in dict(settings.LANGUAGES):
                    request.session[translation.LANGUAGE_SESSION_KEY] = lang
                    translation.activate(lang)
                    request.LANGUAGE_CODE = lang
        except Exception:
            # No romper navegación por un tema de idioma
            pass

        return self.get_response(request)