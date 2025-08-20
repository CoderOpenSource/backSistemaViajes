# accounts/utils.py
from typing import Any, Dict, Optional
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from .models import AuditLog

User = get_user_model()

def audit(
    user: Optional[User],
    action: str,
    entity: str,
    record_id: Any,
    extra: Optional[Dict[str, Any]] = None,
    request: Optional[HttpRequest] = None,
) -> AuditLog:
    """
    Registra un evento en la bitácora.
    - user: User o None (ej. tareas automáticas)
    - action: 'CREATE' | 'UPDATE' | 'DELETE' | 'LOGIN' | 'LOGOUT'
    - entity: nombre de la entidad ('Boleto', 'Ruta', 'User', etc)
    - record_id: id del registro afectado
    - extra: dict con datos adicionales (antes/después, campos, etc)
    - request: opcional, para capturar IP o User-Agent
    """
    extra = dict(extra or {})
    if request is not None:
        extra.setdefault("ip", _get_ip(request))
        ua = request.META.get("HTTP_USER_AGENT")
        if ua:
            extra.setdefault("ua", ua[:200])

    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        entity=entity,
        record_id=str(record_id),
        extra=extra,
    )

def audit_login(user: User, request: Optional[HttpRequest] = None) -> AuditLog:
    return audit(user=user, action="LOGIN", entity="Auth", record_id=user.pk, request=request)

def audit_logout(user: User, request: Optional[HttpRequest] = None) -> AuditLog:
    return audit(user=user, action="LOGOUT", entity="Auth", record_id=user.pk, request=request)

def _get_ip(request: HttpRequest) -> str:
    ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR", "")
    )
    return ip or "0.0.0.0"
