from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.conf import settings

class User(AbstractUser):
    """
    Usuario del sistema con rol y política de contraseña.
    Hereda username, password, first_name, last_name, email, is_active, etc.
    """
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('VEND', 'Vendedor'),
        ('CAJE', 'Cajero'),
    ]
    email = models.EmailField(unique=True, blank=True, null=True)
    role = models.CharField(max_length=5, choices=ROLE_CHOICES, default='VEND')

    # Política de seguridad
    last_password_change = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)

    def mark_password_changed(self):
        self.last_password_change = timezone.now()
        self.must_change_password = False
        self.save(update_fields=['last_password_change', 'must_change_password'])

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    class Meta:
        indexes = [models.Index(fields=['role'])]
        ordering = ['id']


class AuditLog(models.Model):
    """
    Bitácora de auditoría: sólo la escribe el sistema (señales/vistas),
    y se consulta en admin/API (read-only para Admin).
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
        indexes = [
            models.Index(fields=['entity', 'record_id']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        u = self.user.username if self.user else 'anon'
        return f'[{self.created_at:%Y-%m-%d %H:%M}] {u} {self.action} {self.entity}#{self.record_id}'
