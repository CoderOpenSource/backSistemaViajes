from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from cloudinary.models import CloudinaryField
# apps/catalog/models.py
from django.db import models

class Office(models.Model):
    # Identidad
    code = models.CharField(max_length=20, unique=True, db_index=True)   # p.ej. LPZ-01
    name = models.CharField(max_length=100)                               # p.ej. "La Paz Central"

    # División político-administrativa
    department = models.CharField(max_length=80, blank=True)             # Departamento
    province   = models.CharField(max_length=80, blank=True)             # Provincia
    municipality = models.CharField(max_length=80, blank=True)           # Municipio
    locality   = models.CharField(max_length=80, blank=True)             # Localidad / zona / barrio

    # Contacto / ubicación
    address = models.CharField(max_length=160, blank=True)               # calle, número, referencia
    phone = models.CharField(max_length=30, blank=True)
    location_url = models.URLField(blank=True)                           # enlace a Google Maps/Waze (NO iframe)

    # Estado
    active = models.BooleanField(default=True)

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["department"]),
            models.Index(fields=["province"]),
            models.Index(fields=["municipality"]),
            models.Index(fields=["locality"]),
            models.Index(fields=["active"]),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


# -------------------------
# Buses
# -------------------------
class Bus(models.Model):
    code = models.CharField(max_length=20, unique=True, db_index=True)   # código interno (pegatina)
    model = models.CharField(max_length=60)                               # ej. "Marcopolo G7"
    year = models.PositiveIntegerField(
        validators=[MinValueValidator(1980), MaxValueValidator(2100)]
    )
    plate = models.CharField(max_length=20, unique=True)                  # placa (única)
    chassis_number = models.CharField(max_length=50, unique=True)         # número de chasis (único)
    capacity = models.PositiveIntegerField(default=44)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["plate"]),
        ]

    def __str__(self):
        return f"{self.code} ({self.plate})"


# -------------------------
# Rutas + Paradas (las paradas son oficinas)
# -------------------------
class Route(models.Model):
    name = models.CharField(max_length=120, unique=True, db_index=True)   # ej. "LPZ-ORU"
    origin = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="routes_origin")
    destination = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="routes_destination")
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # origen y destino no pueden ser iguales
            models.CheckConstraint(
                check=~models.Q(origin=models.F("destination")),
                name="route_origin_destination_distinct",
            ),
        ]

    def __str__(self):
        return self.name


class RouteStop(models.Model):
    """
    Paradas ordenadas de una ruta.
    TIP: usa office como parada (simple y consistente con oficinas reales).
    scheduled_offset_min: minutos desde la salida programada del Departure (opcional).
      ej: 0 = origen, 45 = llegada estimada a la parada 2 a los 45min.
    """
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="stops")
    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    order = models.PositiveIntegerField()                                 # 0..N
    scheduled_offset_min = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("route", "order"), ("route", "office")]
        ordering = ["order"]
        indexes = [
            models.Index(fields=["route", "order"]),
        ]

    def __str__(self):
        return f"{self.route.name} • {self.order} • {self.office.code}"

# -------------------------
# Departures (salidas programadas)
# -------------------------
class Departure(models.Model):
    """
    Una salida programada de un BUS por una RUTA en un día/hora.
    - scheduled_departure_at: hora programada (venta / planning)
    - actual_departure_at:   hora real de salida
    - status: SCHEDULED / BOARDING / DEPARTED / CLOSED / CANCELLED
    - capacity_snapshot: capacidad del bus en ese momento (histórico)
    """
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_BOARDING = "BOARDING"
    STATUS_DEPARTED = "DEPARTED"
    STATUS_CLOSED = "CLOSED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_BOARDING, "Boarding"),
        (STATUS_DEPARTED, "Departed"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    route = models.ForeignKey("catalog.Route", on_delete=models.PROTECT, related_name="departures")
    bus = models.ForeignKey("catalog.Bus", on_delete=models.PROTECT, related_name="departures")

    # (DEPRECATED) Campo antiguo de chofer único (lo mantenemos temporalmente para compat)
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="driven_departures",
        help_text="DEPRECATED: usar DepartureCrew."
    )

    scheduled_departure_at = models.DateTimeField(db_index=True)
    actual_departure_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    capacity_snapshot = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_departure_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_departure_at"]),
            models.Index(fields=["route", "scheduled_departure_at"]),
        ]

    def __str__(self):
        return f"{self.route.name} @ {timezone.localtime(self.scheduled_departure_at).strftime('%Y-%m-%d %H:%M')}"

    def save(self, *args, **kwargs):
        if self.capacity_snapshot is None and self.bus_id:
            self.capacity_snapshot = self.bus.capacity
        super().save(*args, **kwargs)

# apps/catalog/models.py
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db import models

# ...

# ======================================================
# 1) Tripulación (con rol fijo)
# ======================================================
# apps/catalog/models.py

class CrewMember(models.Model):
    ROLE_DRIVER = "DRIVER"
    ROLE_ASSISTANT = "ASSISTANT"
    ROLE_CHOICES = [
        (ROLE_DRIVER, "Driver"),
        (ROLE_ASSISTANT, "Assistant"),
    ]

    code = models.CharField(max_length=20, unique=True, db_index=True)
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60, blank=True)

    national_id = models.CharField(max_length=30, unique=True, db_index=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=160, blank=True)
    birth_date = models.DateField(null=True, blank=True)

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_ASSISTANT, db_index=True)

    # 🔁 NUEVO: relación con Office (usar PROTECT para conservar integridad)
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name="crew_members",
        null=True, blank=True  # ← déjalo así para migrar sin romper; luego puedes hacerlo required
    )

    photo = CloudinaryField("photo", folder="crew/photos", blank=True, null=True)

    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["role"]),
            models.Index(fields=["active"]),
            models.Index(fields=["office"]),   # 👈 para filtrar por oficina
        ]

    def __str__(self):
        return f"{self.code} - {self.first_name} {self.last_name}".strip()


# ======================================================
# 2) Licencias (solo para DRIVER)
# ======================================================
class DriverLicense(models.Model):
    crew_member = models.ForeignKey(CrewMember, on_delete=models.CASCADE, related_name="licenses")
    number = models.CharField(max_length=40)
    category = models.CharField(max_length=20, blank=True)
    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)


    front_image = CloudinaryField("front_image", folder="licenses/front", blank=True, null=True)
    back_image = CloudinaryField("back_image", folder="licenses/back", blank=True, null=True)

    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-active", "-expires_at", "number"]
        unique_together = [("crew_member", "number")]
        indexes = [
            models.Index(fields=["crew_member", "number"]),
            models.Index(fields=["active"]),
        ]

    def __str__(self):
        return f"{self.crew_member.code} • {self.number} ({self.category or 'N/A'})"

    def is_valid_on(self, dt: timezone.datetime) -> bool:
        if not dt:
            return True
        d = dt.date()
        if self.issued_at and d < self.issued_at:
            return False
        if self.expires_at and d > self.expires_at:
            return False
        return True

    def clean(self):
        from django.core.exceptions import ValidationError
        # Solo se permite crear licencias para miembros con rol DRIVER
        if self.crew_member and self.crew_member.role != CrewMember.ROLE_DRIVER:
            raise ValidationError("Solo los miembros con rol DRIVER pueden tener licencias.")


# ======================================================
# 3) Asignación a Departures (rol debe coincidir)
# ======================================================
class DepartureAssignment(models.Model):
    ROLE_DRIVER = "DRIVER"
    ROLE_ASSISTANT = "ASSISTANT"
    ROLE_CHOICES = [
        (ROLE_DRIVER, "Driver"),
        (ROLE_ASSISTANT, "Assistant"),
    ]

    departure = models.ForeignKey(
        "catalog.Departure", on_delete=models.CASCADE, related_name="crew_assignments"
    )
    crew_member = models.ForeignKey(
        CrewMember, on_delete=models.PROTECT, related_name="departure_assignments"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)

    slot = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(2)],
        help_text="1 o 2. Máximo 2 asignaciones por rol y departure."
    )

    assigned_at = models.DateTimeField(auto_now_add=True)
    unassigned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["departure", "role", "slot", "crew_member__code"]
        unique_together = [
            ("departure", "crew_member"),
            ("departure", "role", "slot"),
        ]
        indexes = [
            models.Index(fields=["departure", "role", "slot"]),
            models.Index(fields=["crew_member", "role"]),
        ]

    def __str__(self):
        return f"DEP:{self.departure_id} • {self.role} • slot {self.slot} • {self.crew_member.code}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if not self.crew_member.active:
            raise ValidationError("El miembro de tripulación está inactivo.")

        # 1) El rol asignado debe coincidir con el rol del miembro
        if self.crew_member.role != self.role:
            raise ValidationError("El rol del miembro no coincide con el rol de la asignación.")

        # 2) Reglas extra para DRIVER: licencia vigente
        if self.role == self.ROLE_DRIVER:
            dep = self.departure
            date_ref = dep.scheduled_departure_at if dep else None
            licenses = list(self.crew_member.licenses.all())
            if not licenses:
                raise ValidationError("El chofer no tiene licencias registradas.")
            if not any(lic.is_valid_on(date_ref) for lic in licenses):
                raise ValidationError("El chofer no tiene una licencia vigente para la fecha de salida.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
