from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from cloudinary.models import CloudinaryField
# apps/catalog/models.py
from django.db import models
from django.db.models import Q, F
from django.core.exceptions import ValidationError

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

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

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

    # 📷 Hasta 4 fotos (opcionales)
    photo1 = CloudinaryField("photo1", folder="buses/photos", blank=True, null=True)
    photo2 = CloudinaryField("photo2", folder="buses/photos", blank=True, null=True)
    photo3 = CloudinaryField("photo3", folder="buses/photos", blank=True, null=True)
    photo4 = CloudinaryField("photo4", folder="buses/photos", blank=True, null=True)

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
# Asientos físicos por Bus
# -------------------------

class Seat(models.Model):
    KIND_NORMAL     = "NORMAL"
    KIND_SEMI_CAMA  = "SEMI_CAMA"
    KIND_CAMA       = "CAMA"
    KIND_LEITO      = "LEITO"
    KIND_ESPECIAL   = "ESPECIAL"  # p.ej. accesible, panorámico, etc.

    KIND_CHOICES = [
        (KIND_NORMAL, "Normal"),
        (KIND_SEMI_CAMA, "Semi-cama"),
        (KIND_CAMA, "Cama"),
        (KIND_LEITO, "Leito"),
        (KIND_ESPECIAL, "Especial"),
    ]

    bus = models.ForeignKey(
        "catalog.Bus",
        on_delete=models.CASCADE,
        related_name="seats",
        db_index=True,
    )
    number = models.PositiveIntegerField(help_text="Número visible del asiento")
    deck = models.PositiveSmallIntegerField(default=1, help_text="Piso: 1 o 2")
    row = models.PositiveSmallIntegerField(null=True, blank=True)
    col = models.PositiveSmallIntegerField(null=True, blank=True)

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_NORMAL)
    is_accessible = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    notes = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["bus", "deck", "number"]
        unique_together = [
            ("bus", "number"),
            ("bus", "deck", "row", "col"),  # si mapeas grilla, evita duplicados
        ]
        indexes = [
            models.Index(fields=["bus", "deck"]),
            models.Index(fields=["bus", "kind"]),
            models.Index(fields=["active"]),
        ]

    def __str__(self):
        label = f"{self.bus.code} • Seat {self.number}"
        if self.deck and self.deck != 1:
            label += f" (Piso {self.deck})"
        if self.kind and self.kind != self.KIND_NORMAL:
            label += f" • {self.get_kind_display()}"
        return label

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.deck < 1 or self.deck > 2:
            raise ValidationError("deck debe ser 1 o 2.")
        # Si usas grilla, ambos row/col deben venir juntos (o ninguno)
        if (self.row is None) ^ (self.col is None):
            raise ValidationError("Si defines fila, debes definir columna (y viceversa).")

# -------------------------
# Rutas + Paradas (las paradas son oficinas)
# -------------------------

class Route(models.Model):
    name = models.CharField(max_length=120, unique=True, db_index=True)
    origin = models.ForeignKey('catalog.Office', on_delete=models.PROTECT, related_name='routes_origin')
    destination = models.ForeignKey('catalog.Office', on_delete=models.PROTECT, related_name='routes_destination')
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                check=~Q(origin=F("destination")),
                name="route_origin_destination_distinct",
            ),
        ]

    def clean(self):
        # (Opcional) obligar que origin y destination estén activos
        if self.origin and not self.origin.active:
            raise ValidationError("La oficina de origen está inactiva.")
        if self.destination and not self.destination.active:
            raise ValidationError("La oficina de destino está inactiva.")

    def __str__(self):
        return self.name


class RouteStop(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="stops")
    office = models.ForeignKey('catalog.Office', on_delete=models.PROTECT)
    order = models.PositiveIntegerField()          # 0..N (0 = origen)
    scheduled_offset_min = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["route", "order"], name="uix_routestop_route_order"),
            models.UniqueConstraint(fields=["route", "office"], name="uix_routestop_route_office"),
            models.CheckConstraint(check=Q(order__gte=0), name="chk_routestop_order_ge_0"),
        ]
        indexes = [
            models.Index(fields=["route", "order"]),
        ]

    def clean(self):
        # no repetir oficinas activas/inactivas lo maneja la FK PROTECT + UniqueConstraint
        if self.office and not self.office.active:
            raise ValidationError("La oficina de la parada está inactiva.")

    def __str__(self):
        return f"{self.route.name} • {self.order} • {self.office.code}"

# -------------------------
# Departures (salidas programadas)
# -------------------------
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

class Departure(models.Model):
    """
    Una salida programada de un BUS por una RUTA en un día/hora.
    - scheduled_departure_at: hora programada (venta / planning)
    - actual_departure_at:   hora real de salida
    - status: SCHEDULED / BOARDING / DEPARTED / CLOSED / CANCELLED
    - capacity_snapshot: capacidad del bus en ese momento (histórico)
    """
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_BOARDING  = "BOARDING"
    STATUS_DEPARTED  = "DEPARTED"
    STATUS_CLOSED    = "CLOSED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_BOARDING,  "Boarding"),
        (STATUS_DEPARTED,  "Departed"),
        (STATUS_CLOSED,    "Closed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # ventana para detectar colisiones del mismo bus en horarios cercanos
    COLLISION_WINDOW_MIN = 30

    route = models.ForeignKey("catalog.Route", on_delete=models.PROTECT, related_name="departures")
    bus   = models.ForeignKey("catalog.Bus",   on_delete=models.PROTECT, related_name="departures")

    # (DEPRECATED) Campo antiguo de chofer único (lo mantenemos temporalmente para compat)
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="driven_departures",
        help_text="DEPRECATED: usar DepartureAssignment."
    )

    scheduled_departure_at = models.DateTimeField(db_index=True)
    actual_departure_at    = models.DateTimeField(null=True, blank=True)

    status            = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    capacity_snapshot = models.PositiveIntegerField(null=True, blank=True)
    notes             = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_departure_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_departure_at"]),
            models.Index(fields=["route",  "scheduled_departure_at"]),
            models.Index(fields=["bus",    "scheduled_departure_at"]),  # NUEVO: consultas por bus+fecha
        ]

    def __str__(self):
        return f"{self.route.name} @ {timezone.localtime(self.scheduled_departure_at).strftime('%Y-%m-%d %H:%M')}"

    # ---------- Validaciones de negocio ----------
    def clean(self):
        super().clean()

        if self.route and not self.route.active:
            raise ValidationError("La ruta está inactiva.")
        if self.bus and not self.bus.active:
            raise ValidationError("El bus está inactivo.")

        # (Opcional) evitar programar muy en el pasado
        if self.scheduled_departure_at and self.scheduled_departure_at < timezone.now() - timedelta(minutes=5):
            raise ValidationError("No puedes programar salidas en el pasado.")

        # Evitar colisiones del mismo bus cerca del horario programado
        if self.bus_id and self.scheduled_departure_at:
            start = self.scheduled_departure_at - timedelta(minutes=self.COLLISION_WINDOW_MIN)
            end   = self.scheduled_departure_at + timedelta(minutes=self.COLLISION_WINDOW_MIN)
            clash = (
                Departure.objects
                .filter(bus_id=self.bus_id,
                        scheduled_departure_at__gte=start,
                        scheduled_departure_at__lte=end)
                .exclude(pk=self.pk)
                .exists()
            )
            if clash:
                raise ValidationError("El bus ya tiene una salida en un horario cercano.")

    # ---------- Persistencia ----------
    def save(self, *args, **kwargs):
        if self.capacity_snapshot is None and self.bus_id:
            self.capacity_snapshot = self.bus.capacity
        self.full_clean()  # asegura correr clean() también en saves directos
        super().save(*args, **kwargs)

    # ---------- Helpers de tripulación activa ----------
    @property
    def crew_assignments_active(self):
        # related_name en DepartureAssignment: "crew_assignments"
        return self.crew_assignments.filter(unassigned_at__isnull=True).select_related("crew_member")

    @property
    def crew_drivers(self):
        return [a.crew_member for a in self.crew_assignments_active.filter(role="DRIVER")]

    @property
    def crew_assistants(self):
        return [a.crew_member for a in self.crew_assignments_active.filter(role="ASSISTANT")]

    # ---------- Workflow de estados (opcional) ----------
    ALLOWED_TRANSITIONS = {
        STATUS_SCHEDULED:  {STATUS_BOARDING, STATUS_CANCELLED},
        STATUS_BOARDING:   {STATUS_DEPARTED, STATUS_CANCELLED},
        STATUS_DEPARTED:   {STATUS_CLOSED},
        STATUS_CLOSED:     set(),
        STATUS_CANCELLED:  set(),
    }

    def can_transition(self, new_status: str) -> bool:
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, set())

    def set_status(self, new_status: str, when=None):
        if not self.can_transition(new_status):
            raise ValidationError(f"Transición inválida {self.status} → {new_status}")
        self.status = new_status
        if new_status == self.STATUS_DEPARTED and when and not self.actual_departure_at:
            self.actual_departure_at = when

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
