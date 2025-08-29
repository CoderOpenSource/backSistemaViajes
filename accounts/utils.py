# users/utils/audit.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Optional

from django.db import connection
from .models import AuditLog


__all__ = [
    "client_ip_from_request",
    "set_db_audit_context",
    "clear_db_audit_context",
    "audit_context",
    "audit_event",
    "audit",  # alias compatible con tu helper anterior (para eventos sin DML)
]


# ----------------------------
# Helpers de red / request
# ----------------------------
def client_ip_from_request(request) -> Optional[str]:
    """
    Extrae la IP del request (X-Forwarded-For o REMOTE_ADDR).
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")


# -------------------------------------------
# Contexto de auditoría a nivel de conexión
# (para que los TRIGGERS de Postgres lo lean)
# -------------------------------------------
def set_db_audit_context(*, user_id: Optional[int] = None, username: Optional[str] = None, ip: Optional[str] = None) -> None:
    """
    Úsalo manualmente en tareas/commands cuando NO hay request.
    El middleware ya hace esto automáticamente para cada request web.
    """
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', %s, true)", [str(user_id or "")])
        cur.execute("SELECT set_config('app.user', %s, true)", [username or ""])
        cur.execute("SELECT set_config('app.ip', %s, true)", [ip or ""])


def clear_db_audit_context() -> None:
    """
    Limpia el contexto en la sesión de DB (importante si usas pool/conexiones persistentes).
    """
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', '', true)")
        cur.execute("SELECT set_config('app.user', '', true)")
        cur.execute("SELECT set_config('app.ip', '', true)")


@contextmanager
def audit_context(*, user_id: Optional[int] = None, username: Optional[str] = None, ip: Optional[str] = None):
    """
    Context manager para envolver bloques de código (tareas, scripts)
    que harán INSERT/UPDATE/DELETE y quieres que los TRIGGERS registren user/ip.
    """
    set_db_audit_context(user_id=user_id, username=username, ip=ip)
    try:
        yield
    finally:
        clear_db_audit_context()


# -----------------------------------------------------
# Auditoría directa a la tabla (para eventos sin DML)
# -----------------------------------------------------
def audit_event(
    *,
    action: str,
    entity: str,
    record_id: Any = None,
    extra: Optional[Dict[str, Any]] = None,
    user=None,
    ip: Optional[str] = None,
) -> AuditLog:
    """
    Inserta una fila en users_auditlog para EVENTOS SIN DML (p.ej. LOGIN/LOGOUT).
    Para CRUD normal NO la uses: eso ya lo cubren los TRIGGERS.
    """
    payload: Dict[str, Any] = {"ip": ip, "source": "app_event"}
    if isinstance(extra, dict):
        payload.update(extra)

    return AuditLog.objects.create(
        user=user,
        action=action,
        entity=entity,
        record_id=str(record_id) if record_id is not None else None,
        extra=payload,
    )


# -----------------------------------------------------
# Alias compatible con tu helper anterior
# (para eventos sin DML desde vistas con request)
# -----------------------------------------------------
def audit(
    request,
    *,
    action: str,
    entity: str,
    record_id: Any = None,
    extra: Optional[Dict[str, Any]] = None,
    user=None,
):
    """
    Compatibilidad con tu helper anterior para eventos SIN DML.
    Ej: audit(request, action="LOGIN", entity="Auth", record_id=user.id, user=user)
    """
    # user: si no se pasa, toma el autenticado del request (si existe)
    u = user if user is not None else (request.user if getattr(request, "user", None) and request.user.is_authenticated else None)

    # agrega path/method al extra
    payload = {**(extra or {}), "path": getattr(request, "path", None), "method": getattr(request, "method", None)}

    return audit_event(
        action=action,
        entity=entity,
        record_id=record_id,
        extra=payload,
        user=u,
        ip=client_ip_from_request(request) if request else None,
    )
