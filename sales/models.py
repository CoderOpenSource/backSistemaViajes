# apps/ventas/models.py
import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

# ⬇️ Importa las clases del catálogo y úsalas directo
from catalog.models import Departure, Seat, Office
# (Opcional) si tu app passengers está instalada y quieres evitar la string:
from passenger.models import Passenger

class Ticket(models.Model):
    STATUS_RESERVED = "RESERVED"
    STATUS_PAID = "PAID"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_NO_SHOW = "NO_SHOW"

    STATUS_CHOICES = [
        (STATUS_RESERVED, "Reservado"),
        (STATUS_PAID, "Pagado"),
        (STATUS_CANCELLED, "Anulado"),
        (STATUS_NO_SHOW, "No se presentó"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    passenger = models.ForeignKey(Passenger, on_delete=models.PROTECT, related_name="tickets")

    # ⬇️ Usando las clases importadas del catálogo (no strings "catalog.X")
    departure   = models.ForeignKey(Departure, on_delete=models.PROTECT, related_name="tickets")
    seat        = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="tickets")

    origin      = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="tickets_origin")
    destination = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="tickets_destination")

    office_sold = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="tickets_sold")

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets_sold_by")

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_RESERVED)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["departure", "seat"]),
            models.Index(fields=["status"]),
            models.Index(fields=["departure", "origin", "destination"]),
        ]
        unique_together = ("departure", "seat", "origin", "destination")

    def __str__(self):
        return f"{self.passenger} • {self.seat} • {self.origin.code}->{self.destination.code}"

    # --- Validaciones ---
    def clean(self):
        super().clean()

        # 1) El asiento debe pertenecer al bus de la salida
        if self.seat_id and self.departure_id:
            dep_bus_id = self.departure.bus_id
            seat_bus_id = self.seat.bus_id
            if dep_bus_id and seat_bus_id and dep_bus_id != seat_bus_id:
                raise ValidationError("El asiento seleccionado no pertenece al bus de esta salida.")

        # 2) Origen y destino válidos en la ruta (y orden correcto)
        if self.departure_id and self.origin_id and self.destination_id:
            route = self.departure.route
            stops = {rs.office_id: rs.order for rs in route.stops.all()}
            if self.origin_id not in stops or self.destination_id not in stops:
                raise ValidationError("Origen y/o destino no pertenecen a la ruta de la salida.")
            if stops[self.origin_id] >= stops[self.destination_id]:
                raise ValidationError("El origen debe ser anterior al destino en la ruta.")

        # 3) Asiento activo
        if self.seat_id and self.seat and not self.seat.active:
            raise ValidationError("El asiento está inactivo.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
