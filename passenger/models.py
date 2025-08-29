import uuid
from datetime import date
from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.postgres.indexes import GinIndex

TIPO_DOC = [
    ("CI", "CI"),
    ("PASAPORTE", "Pasaporte"),
    ("OTRO", "Otro"),
]

class Passenger(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tipo_doc = models.CharField(max_length=12, choices=TIPO_DOC)
    nro_doc = models.CharField(max_length=32)
    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120, blank=True, null=True)
    fecha_nac = models.DateField(blank=True, null=True)
    telefono = models.CharField(max_length=32, blank=True, null=True)
    email = models.EmailField(max_length=120, blank=True, null=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    apoderados = models.ManyToManyField(
        "self",
        through="PassengerRelation",
        symmetrical=False,
        related_name="menores",
        blank=True,
    )

    class Meta:
        unique_together = ("tipo_doc", "nro_doc")
        indexes = [
            models.Index(fields=["telefono"]),
            models.Index(fields=["tipo_doc", "nro_doc"]),
            # Requiere pg_trgm habilitado y opclass explícita:
            GinIndex(
                name="ix_passenger_nombres_trgm",
                fields=["nombres"],
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                name="ix_passenger_apellidos_trgm",
                fields=["apellidos"],
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.nombres} {self.apellidos or ''} ({self.tipo_doc} {self.nro_doc})"

    @property
    def es_menor(self) -> bool:
        if not self.fecha_nac:
            return False
        today = date.today()
        edad = today.year - self.fecha_nac.year - (
            (today.month, today.day) < (self.fecha_nac.month, self.fecha_nac.day)
        )
        return edad < 18


class PassengerRelation(models.Model):
    """Relación permanente menor ↔ apoderado/tutor."""
    menor = models.ForeignKey(
        Passenger, on_delete=models.CASCADE, related_name="relaciones_como_menor"
    )
    apoderado = models.ForeignKey(
        Passenger, on_delete=models.CASCADE, related_name="relaciones_como_apoderado"
    )
    parentesco = models.CharField(max_length=40, blank=True, null=True)
    es_tutor_legal = models.BooleanField(default=False)
    vigente_desde = models.DateField(blank=True, null=True)
    vigente_hasta = models.DateField(blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["menor", "apoderado", "vigente_hasta"], name="uq_relacion_periodo"
            ),
        ]

    def clean(self):
        if self.menor_id == self.apoderado_id:
            raise ValidationError("Un pasajero no puede ser su propio apoderado.")

    def __str__(self):
        return f"{self.menor} ↔ {self.apoderado} ({self.parentesco})"
