# accounts/middleware.py
from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Set

from django.conf import settings
from django.http import JsonResponse, HttpResponsePermanentRedirect
from django.urls import reverse
from django.utils import timezone

from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication


# ---------------- PasswordExpiryEnforcer (sin cambios funcionales) ----------------
DEFAULTS = {
    "ENABLED": True,
    "API_PREFIX": "/api/",
    "AUTO_EXPIRE": True,
    "MAX_AGE_DAYS": 60,
    "ALLOWED_PATHS": {
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/change-password",
        "/admin/login/",
        "/admin/logout/",
        "/admin/password_change/",
    },
    "HTML_CHANGE_PASSWORD_URLNAME": None,
}

def _cfg(key, default=None):
    data = getattr(settings, "PASSWORD_ENFORCER", {})
    return data.get(key, DEFAULTS.get(key, default))

def _norm_paths(paths: Iterable[str]) -> Set[str]:
    return {(p.rstrip("/") or "/") for p in paths}

def _is_static_or_media(path: str) -> bool:
    return path.startswith("/static/") or path.startswith("/media/")

def _is_allowed_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    allowed = _norm_paths(_cfg("ALLOWED_PATHS"))
    return p in allowed or _is_static_or_media(p)

def _is_api_request(request) -> bool:
    api_prefix = _cfg("API_PREFIX")
    if api_prefix and request.path.startswith(api_prefix):
        return True
    accept = (request.META.get("HTTP_ACCEPT") or "").lower()
    return "application/json" in accept or "application/*+json" in accept

class PasswordExpiryEnforcer:
    """Bloquea el acceso si el usuario debe cambiar contraseña."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _cfg("ENABLED"):
            return self.get_response(request)

        if request.method == "OPTIONS" or _is_static_or_media(request.path):
            return self.get_response(request)

        user = getattr(request, "user", None)

        if not (user and user.is_authenticated):
            return self.get_response(request)

        if _is_allowed_path(request.path):
            return self.get_response(request)

        if _cfg("AUTO_EXPIRE"):
            last = getattr(user, "last_password_change", None)
            max_age = int(_cfg("MAX_AGE_DAYS") or 0)
            if max_age > 0:
                if (last is None) or (timezone.now() - last > timedelta(days=max_age)):
                    if not getattr(user, "must_change_password", False):
                        user.must_change_password = True
                        user.save(update_fields=["must_change_password"])

        if getattr(user, "must_change_password", False):
            if _is_api_request(request):
                return JsonResponse({"detail": "Debe cambiar su contraseña"}, status=403)
            urlname = _cfg("HTML_CHANGE_PASSWORD_URLNAME")
            if urlname:
                try:
                    change_url = reverse(urlname)
                    return HttpResponsePermanentRedirect(change_url)
                except Exception:
                    pass
            return JsonResponse({"detail": "Debe cambiar su contraseña"}, status=403)

        return self.get_response(request)


# ---------------- Contexto de auditoría para triggers (DBAuditContextMiddleware) ----------------
def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")

def _set_db_audit_context(*, user_id: int | None, username: str | None, ip: str | None):
    # ❗ Sesión (persistente durante el request): tercer parámetro = false
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', %s, false)", [str(user_id or "")])
        cur.execute("SELECT set_config('app.user', %s, false)", [username or ""])
        cur.execute("SELECT set_config('app.ip', %s, false)", [ip or ""])

def _clear_db_audit_context():
    # Limpia al finalizar el request (local a la transacción es suficiente aquí)
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', '', true)")
        cur.execute("SELECT set_config('app.user', '', true)")
        cur.execute("SELECT set_config('app.ip', '', true)")

class DBAuditContextMiddleware:
    """
    Inyecta (user_id, username, ip) en la sesión de PostgreSQL para que
    auditlog_row_change() lo grabe en cada INSERT/UPDATE/DELETE.
    Debe ir DESPUÉS de AuthenticationMiddleware.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            # Fallback a JWT si no hay sesión
            try:
                pair = JWTAuthentication().authenticate(request)
                if pair:
                    user, _ = pair
            except Exception:
                user = None

        _set_db_audit_context(
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
            ip=_client_ip(request),
        )
        try:
            return self.get_response(request)
        finally:
            _clear_db_audit_context()
