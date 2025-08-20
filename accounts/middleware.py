# accounts/middleware.py
from datetime import timedelta
from typing import Iterable, Set

from django.conf import settings
from django.http import JsonResponse, HttpResponsePermanentRedirect
from django.urls import reverse

from django.utils import timezone

DEFAULTS = {
    "ENABLED": True,                 # apágalo en tests si quieres
    "API_PREFIX": "/api/",           # cómo detectar rutas API
    "AUTO_EXPIRE": True,             # marcar must_change_password automáticamente por antigüedad
    "MAX_AGE_DAYS": 60,              # política de caducidad
    "ALLOWED_PATHS": {               # rutas SIEMPRE permitidas
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/change-password",
        "/admin/login/",
        "/admin/logout/",
        "/admin/password_change/",
    },
    # Si usas una vista HTML para cambiar clave, nómbrala aquí (opcional)
    "HTML_CHANGE_PASSWORD_URLNAME": None,  # e.g. "accounts:change_password_page"
}

def _cfg(key, default=None):
    data = getattr(settings, "PASSWORD_ENFORCER", {})
    return data.get(key, DEFAULTS.get(key, default))

def _norm_paths(paths: Iterable[str]) -> Set[str]:
    return { (p.rstrip("/") or "/") for p in paths }

def _is_static_or_media(path: str) -> bool:
    return path.startswith("/static/") or path.startswith("/media/")

def _is_allowed_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    allowed = _norm_paths(_cfg("ALLOWED_PATHS"))
    return p in allowed or _is_static_or_media(p)

def _is_api_request(request) -> bool:
    # Heurística: por prefijo o por Accept header
    api_prefix = _cfg("API_PREFIX")
    if api_prefix and request.path.startswith(api_prefix):
        return True
    accept = (request.META.get("HTTP_ACCEPT") or "").lower()
    return "application/json" in accept or "application/*+json" in accept

class PasswordExpiryEnforcer:
    """
    - Si el usuario está autenticado y (must_change_password=True) ⇒
        * API: JSON 403 {"detail": "Debe cambiar su contraseña"}
        * HTML: Redirect a la vista de cambio de contraseña (si está configurada) o 403 JSON
    - (Opcional) AUTO_EXPIRE: si last_password_change es None o venció, marca must_change_password=True.
    - Excepciones: rutas de auth, admin login, static/media, OPTIONS (CORS), y anónimos.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _cfg("ENABLED"):
            return self.get_response(request)

        # Permitir preflight y recursos estáticos
        if request.method == "OPTIONS" or _is_static_or_media(request.path):
            return self.get_response(request)

        user = getattr(request, "user", None)

        # Anónimos: no aplicamos bloqueo (ya lo manejará la auth/permiso de cada vista)
        if not (user and user.is_authenticated):
            return self.get_response(request)

        # Rutas whitelisted (auth/admin)
        if _is_allowed_path(request.path):
            return self.get_response(request)

        # (Opcional) marcar expirado automáticamente por antigüedad
        if _cfg("AUTO_EXPIRE"):
            last = getattr(user, "last_password_change", None)
            max_age = int(_cfg("MAX_AGE_DAYS") or 0)
            if max_age > 0:
                if (last is None) or (timezone.now() - last > timedelta(days=max_age)):
                    if not getattr(user, "must_change_password", False):
                        user.must_change_password = True
                        user.save(update_fields=["must_change_password"])

        # Si debe cambiar contraseña, bloquear
        if getattr(user, "must_change_password", False):
            if _is_api_request(request):
                return JsonResponse({"detail": "Debe cambiar su contraseña"}, status=403)
            # Navegación HTML: intenta redirigir a una página de cambio de clave
            urlname = _cfg("HTML_CHANGE_PASSWORD_URLNAME")
            if urlname:
                try:
                    change_url = reverse(urlname)
                    # redirección permanente para evitar loops
                    return HttpResponsePermanentRedirect(change_url)
                except Exception:
                    pass
            # fallback JSON si no hay url de cambio HTML
            return JsonResponse({"detail": "Debe cambiar su contraseña"}, status=403)

        return self.get_response(request)
