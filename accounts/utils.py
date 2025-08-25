def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")

def audit(request, *, action: str, entity: str, record_id=None, extra=None, user=None):
    """
    Crea un AuditLog coherente en cualquier vista.
    - user: opcional; si no se pasa, usa request.user (si está autenticado)
    - record_id: id del recurso afectado (str/int)
    - extra: dict con detalles
    """
    from .models import AuditLog  # evitar ciclos
    u = user if user is not None else (request.user if request.user.is_authenticated else None)
    payload = {"ip": _client_ip(request), "path": request.path, "method": request.method}
    if isinstance(extra, dict):
        payload.update(extra)
    AuditLog.objects.create(
        user=u,
        action=action,
        entity=entity,
        record_id=str(record_id) if record_id is not None else None,
        extra=payload,
    )
def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
