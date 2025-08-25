# users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.db import models
from django.contrib.postgres.indexes import GinIndex, BTreeIndex, BrinIndex

# 👇 Indexes específicos de Postgres
from django.contrib.postgres.indexes import GinIndex, BTreeIndex

class User(AbstractUser):
    """
    Índices pensados para filtros y búsqueda:
    - BTREE(role, office): filtro combinado muy común en listados.
    - BTREE(must_change_password, is_active): encuentra rápido “debe cambiar clave”.
    - BTREE(last_password_change): ordenar/filtrar por fecha.
    - GIN (trigram) sobre username y email (opcional) para búsquedas por texto.
    """
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('VEND',  'Vendedor'),
        ('CAJE',  'Cajero'),
    ]

    email = models.EmailField(unique=True, blank=True, null=True)  # unique = índice único BTREE
    role = models.CharField(max_length=5, choices=ROLE_CHOICES, default='VEND', db_index=True)
    office = models.ForeignKey('catalog.Office', on_delete=models.PROTECT,
                               null=True, blank=True, related_name='users', db_index=True)

    # Política de seguridad
    last_password_change = models.DateTimeField(null=True, blank=True, db_index=True)
    must_change_password = models.BooleanField(default=False)

    def mark_password_changed(self):
        self.last_password_change = timezone.now()
        self.must_change_password = False
        self.save(update_fields=['last_password_change', 'must_change_password'])

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    class Meta:
        ordering = ['id']
        indexes = [
            # Filtros combinados frecuentes en listados
            BTreeIndex(fields=['role', 'office'], name='user_role_office_btree'),

            # Para panel de “usuarios que deben cambiar contraseña”
            BTreeIndex(fields=['must_change_password', 'is_active'], name='user_pwdflag_active_btree'),

            # Ya está individualmente en el campo, pero es útil dejar explícito el objetivo:
            BTreeIndex(fields=['last_password_change'], name='user_last_pwd_change_btree'),

            # 🔎 Opcional (si harás búsquedas por texto “contiene” o “parecido” en username/email):
            # Requiere extensión pg_trgm (ver nota de migraciones más abajo).
            GinIndex(fields=['username'], name='user_username_trgm_gin', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['email'],    name='user_email_trgm_gin',    opclasses=['gin_trgm_ops']),
        ]

class AuditLog(models.Model):
    """
    Índices para auditoría (tabla grande y append-only):
    - BTREE(entity, record_id): lookup de un registro auditado.
    - BRIN(created_at): escaneo por rangos de fecha muy barato (ideal para logs).
    - BTREE(user, created_at) y BTREE(action, created_at): listados/timelines.
    - GIN(extra): si consultas por claves/valores dentro del JSON.
    """
    ACTION_CHOICES = [
        ('CREATE', 'CREATE'),
        ('UPDATE', 'UPDATE'),
        ('DELETE', 'DELETE'),
        ('LOGIN',  'LOGIN'),
        ('LOGOUT', 'LOGOUT'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        help_text='Usuario que originó la acción (si aplica).'
    )
    action = models.CharField(max_length=12, choices=ACTION_CHOICES)
    entity = models.CharField(max_length=100, help_text='Nombre de la entidad afectada, p.ej. "Boleto".')
    record_id = models.CharField(max_length=64, help_text='ID del registro afectado en esa entidad.')
    extra = models.JSONField(default=dict, blank=True, help_text='Datos adicionales (antes/después, IP, etc).')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            BTreeIndex(fields=['entity', 'record_id'], name='audit_entity_record_btree'),

            # BRIN: excelente para rangos de fecha en tablas grandes (mucho más liviano que BTREE).
            BrinIndex(fields=['created_at'], name='audit_created_brin'),

            BTreeIndex(fields=['user', 'created_at'],   name='audit_user_created_btree'),
            BTreeIndex(fields=['action', 'created_at'], name='audit_action_created_btree'),

            # Sólo si vas a filtrar/buscar por contenido de 'extra':
            GinIndex(fields=['extra'], name='audit_extra_gin'),
        ]

    def __str__(self):
        u = self.user.username if self.user else 'anon'
        return f'[{self.created_at:%Y-%m-%d %H:%M}] {u} {self.action} {self.entity}#{self.record_id}'
